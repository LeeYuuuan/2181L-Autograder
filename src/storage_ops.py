"""
Storage classes for the Canvas autograder.

Design:
- ProjectStore manages the root directory.
- CourseStore manages one course directory, course_info, and roster.
- AssignmentStore manages one assignment directory, assignment_info,
  assignment_config, manifest, student records, submissions, and grade.json.

Data is stored as JSON files. Classes only manage paths and read/write logic.

Current grading design reminder:
- Grading is not implemented yet.
- When implemented, each student will have one grade.json.
- Each new grading result overwrites the old grade.json.
- The grader should write grade.json and record.json immediately after each student.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    """Return current UTC time in ISO format."""

    return datetime.now(timezone.utc).isoformat()


def ensure_dir(path: Path) -> Path:
    """Create a directory if it does not exist."""

    path.mkdir(parents=True, exist_ok=True)
    return path


def make_json_safe(obj: Any) -> Any:
    """Convert common Python/Canvas objects into JSON-safe values."""

    if obj is None:
        return None

    if isinstance(obj, (str, int, float, bool)):
        return obj

    if isinstance(obj, Path):
        return str(obj)

    if isinstance(obj, list):
        return [make_json_safe(item) for item in obj]

    if isinstance(obj, tuple):
        return [make_json_safe(item) for item in obj]

    if isinstance(obj, dict):
        return {str(key): make_json_safe(value) for key, value in obj.items()}

    if hasattr(obj, "isoformat"):
        try:
            return obj.isoformat()
        except Exception:
            pass

    if hasattr(obj, "__dict__"):
        data = {}

        for key, value in obj.__dict__.items():
            if key.startswith("_"):
                continue

            data[key] = make_json_safe(value)

        return data

    return str(obj)


def load_json(path: Path, default: Any) -> Any:
    """Load JSON file. Return default if the file does not exist."""

    if not path.exists():
        return default

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: Any) -> None:
    """Save data to JSON file."""

    ensure_dir(path.parent)

    with path.open("w", encoding="utf-8") as f:
        json.dump(make_json_safe(data), f, indent=2, ensure_ascii=False)


class ProjectStore:
    """Root storage manager for the whole autograder project."""

    def __init__(self, base_dir: str | Path | None = None):
        if base_dir is None:
            self.base_dir = Path("data") / "canvas_downloads"
        else:
            self.base_dir = Path(base_dir)

        ensure_dir(self.base_dir)

    def course(self, course_id: int) -> "CourseStore":
        """Get a CourseStore."""

        return CourseStore(base_dir=self.base_dir, course_id=course_id)


class CourseStore:
    """Storage manager for one Canvas course."""

    def __init__(self, base_dir: Path, course_id: int):
        self.base_dir = base_dir
        self.course_id = int(course_id)
        self.course_dir = self.base_dir / f"course_{self.course_id}"

        ensure_dir(self.course_dir)

    @property
    def course_info_path(self) -> Path:
        return self.course_dir / "course_info.json"

    @property
    def roster_path(self) -> Path:
        return self.course_dir / "roster.json"

    def assignment(self, assignment_id: int) -> "AssignmentStore":
        """Get an AssignmentStore."""

        return AssignmentStore(
            course_dir=self.course_dir,
            course_id=self.course_id,
            assignment_id=assignment_id,
        )

    def save_course_info_from_match(self, course_match: Any) -> None:
        """Save course metadata from MatchResult."""

        data = {
            "course_id": course_match.id,
            "name": course_match.name,
            "course_code": course_match.extra.get("course_code", ""),
            "workflow_state": course_match.extra.get("workflow_state", ""),
            "saved_at": utc_now_iso(),
        }

        save_json(self.course_info_path, data)

    def load_roster(self) -> dict[str, Any]:
        """Load course roster."""

        default_roster = {
            "course_id": self.course_id,
            "created_at": utc_now_iso(),
            "updated_at": None,
            "students": {},
        }

        return load_json(self.roster_path, default_roster)

    def save_roster(self, roster: dict[str, Any]) -> None:
        """Save course roster."""

        roster["course_id"] = self.course_id
        roster["updated_at"] = utc_now_iso()

        save_json(self.roster_path, roster)

    def upsert_student_in_roster(
        self,
        user_id: int,
        student_name: str = "",
        email: str | None = None,
        assignment_id: int | None = None,
        record_rel_path: str | None = None,
    ) -> None:
        """Add or update a student entry in roster.json."""

        roster = self.load_roster()

        students = roster.setdefault("students", {})
        user_key = str(int(user_id))

        student_entry = students.setdefault(
            user_key,
            {
                "user_id": int(user_id),
                "student_name": "",
                "email": None,
                "records": {},
            },
        )

        if student_name:
            student_entry["student_name"] = student_name

        if email:
            student_entry["email"] = email

        if assignment_id is not None and record_rel_path is not None:
            student_entry.setdefault("records", {})[str(int(assignment_id))] = record_rel_path

        self.save_roster(roster)


class AssignmentStore:
    """Storage manager for one Canvas assignment."""

    def __init__(self, course_dir: Path, course_id: int, assignment_id: int):
        self.course_dir = course_dir
        self.course_id = int(course_id)
        self.assignment_id = int(assignment_id)

        self.assignment_dir = self.course_dir / f"assignment_{self.assignment_id}"
        self.materials_dir = self.assignment_dir / "materials"
        self.students_dir = self.assignment_dir / "students"

        ensure_dir(self.assignment_dir)
        ensure_dir(self.materials_dir)
        ensure_dir(self.students_dir)

    @property
    def assignment_info_path(self) -> Path:
        return self.assignment_dir / "assignment_info.json"

    @property
    def assignment_config_path(self) -> Path:
        return self.assignment_dir / "assignment_config.json"

    @property
    def manifest_path(self) -> Path:
        return self.assignment_dir / "manifest.json"

    def clear_assignment_cache(self) -> None:
        """
        Delete the local cache for this assignment.

        This removes:
        - assignment_info.json
        - assignment_config.json
        - manifest.json
        - materials/
        - students/

        It does not remove course_info.json or roster.json.
        """

        if self.assignment_dir.exists():
            shutil.rmtree(self.assignment_dir)

        ensure_dir(self.assignment_dir)
        ensure_dir(self.materials_dir)
        ensure_dir(self.students_dir)

    def student_dir(self, user_id: int) -> Path:
        """Get one student's directory for this assignment."""

        return ensure_dir(self.students_dir / f"user_{int(user_id)}")

    def record_path(self, user_id: int) -> Path:
        """Get one student's record.json path."""

        return self.student_dir(user_id) / "record.json"

    def submission_pdf_path(self, user_id: int) -> Path:
        """Get one student's standard submission PDF path."""

        return self.student_dir(user_id) / "submission.pdf"

    def grade_path(self, user_id: int) -> Path:
        """Get one student's grade.json path."""

        return self.student_dir(user_id) / "grade.json"

    def load_grade_result(self, user_id: int) -> dict[str, Any]:
        """Load one student's grade.json."""

        return load_json(self.grade_path(user_id), default={})

    def save_grade_result(self, user_id: int, grade_data: dict[str, Any]) -> None:
        """
        Save one student's grade.json.

        Future grader should call this immediately after each student is graded.
        Existing grade.json will be overwritten.
        """

        save_json(self.grade_path(user_id), grade_data)

    def record_rel_path_from_course_dir(self, user_id: int) -> str:
        """Return record path relative to the course directory."""

        return str(self.record_path(user_id).relative_to(self.course_dir))

    def save_assignment_info_from_match(self, assignment_match: Any) -> None:
        """Save assignment metadata from MatchResult."""

        data = {
            "course_id": self.course_id,
            "assignment_id": assignment_match.id,
            "name": assignment_match.name,
            "points_possible": assignment_match.extra.get("points_possible"),
            "due_at": assignment_match.extra.get("due_at"),
            "unlock_at": assignment_match.extra.get("unlock_at"),
            "lock_at": assignment_match.extra.get("lock_at"),
            "workflow_state": assignment_match.extra.get("workflow_state", ""),
            "saved_at": utc_now_iso(),
        }

        save_json(self.assignment_info_path, data)

    def load_assignment_config(self) -> dict[str, Any]:
        """Load assignment_config.json."""

        return load_json(self.assignment_config_path, default={})

    def ensure_assignment_config(self, assignment_match: Any | None = None) -> dict[str, Any]:
        """
        Create assignment_config.json if it does not exist.

        This is our grading configuration file, not Canvas metadata.
        """

        existing = self.load_assignment_config()

        if existing:
            return existing

        points_possible = None

        if assignment_match is not None:
            points_possible = assignment_match.extra.get("points_possible")

        config = {
            "course_id": self.course_id,
            "assignment_id": self.assignment_id,
            "created_at": utc_now_iso(),
            "updated_at": utc_now_iso(),

            "grading_enabled": True,
            "expected_submission_type": "pdf",
            "use_latest_submission_only": True,

            "points_possible": points_possible,

            "materials": {
                "problem_set_pdf": "materials/problem_set.pdf",
                "rubric_pdf": None,
                "presence_prompt": "materials/prompt_presence.txt",
                "grading_prompt": "materials/prompt_grading.txt",
            },

            "grading_policy": {
                "presence_check_required": True,
                "grade_only_answered_parts": True,
                "allow_partial_credit": True,
                "default_missing_score": 0,
            },

            "llm": {
                "provider": None,
                "model": None,
                "temperature": 0,
            },

            "output": {
                "save_per_student_grade_json": True,
                "save_summary_csv": True,
                "post_to_canvas": False,
            },
        }

        save_json(self.assignment_config_path, config)
        return config

    def load_manifest(self) -> dict[str, Any]:
        """Load manifest.json."""

        default_manifest = {
            "course_id": self.course_id,
            "assignment_id": self.assignment_id,

            "created_at": utc_now_iso(),
            "last_checked_at": None,
            "last_downloaded_at": None,
            "last_graded_at": None,

            "download_runs": [],
            "grading_runs": [],

            "student_records": {},
            "stats": {},
        }

        return load_json(self.manifest_path, default_manifest)

    def save_manifest(self, manifest: dict[str, Any]) -> None:
        """Save manifest.json."""

        manifest["course_id"] = self.course_id
        manifest["assignment_id"] = self.assignment_id

        save_json(self.manifest_path, manifest)

    def load_student_record(self, user_id: int) -> dict[str, Any]:
        """Load one student's assignment record."""

        default_record = {
            "course_id": self.course_id,
            "assignment_id": self.assignment_id,
            "user_id": int(user_id),

            "student": {
                "name": "",
                "email": None,
            },

            "submission": {
                "workflow_state": None,
                "submitted_at": None,
                "attempt": None,
                "late": None,
                "missing": None,
                "attachments": [],
                "selected_file": None,
                "selected_attachment": None,
                "download_status": "not_checked",
                "downloaded_at": None,
                "checked_at": None,
            },

            "grading": {
                "status": "not_graded",
                "latest_grade_file": None,
                "latest_graded_at": None,
                "latest_score": None,
                "provider": None,
                "model": None,
            },

            "history": [],
        }

        return load_json(self.record_path(user_id), default_record)

    def save_student_record(self, user_id: int, record: dict[str, Any]) -> None:
        """Save one student's assignment record."""

        record["course_id"] = self.course_id
        record["assignment_id"] = self.assignment_id
        record["user_id"] = int(user_id)

        save_json(self.record_path(user_id), record)

    def update_manifest_student_record(self, manifest: dict[str, Any], user_id: int) -> None:
        """Update manifest with a pointer to one student's record.json."""

        manifest.setdefault("student_records", {})[str(int(user_id))] = str(
            self.record_path(user_id).relative_to(self.assignment_dir)
        )


def clear_assignment_cache(
    base_dir: str | Path | None,
    course_id: int,
    assignment_id: int,
) -> Path:
    project_store = ProjectStore(base_dir)
    course_store = project_store.course(course_id)
    assignment_store = course_store.assignment(assignment_id)

    assignment_store.clear_assignment_cache()

    return assignment_store.assignment_dir

