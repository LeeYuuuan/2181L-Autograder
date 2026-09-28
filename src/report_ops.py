"""
Report/export utilities for Canvas autograder.

Current feature:
- Export grades_summary.csv from local grade.json and record.json files.

This does NOT post grades to Canvas.
It only creates a CSV for review.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from src.storage_ops import ProjectStore, utc_now_iso


def load_json_safe(path: Path, default: Any) -> Any:
    """Load JSON safely. Return default if missing or invalid."""

    if not path.exists():
        return default

    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def get_assignment_points_possible(assignment_store: Any) -> float | None:
    """
    Get assignment points_possible.

    Priority:
    1. assignment_config.json
    2. assignment_info.json
    """

    config = assignment_store.load_assignment_config()
    points = config.get("points_possible")

    if points is not None:
        try:
            return float(points)
        except Exception:
            pass

    assignment_info = load_json_safe(assignment_store.assignment_info_path, default={})
    points = assignment_info.get("points_possible")

    if points is not None:
        try:
            return float(points)
        except Exception:
            pass

    return None


def collect_student_grade_rows(
    base_dir: str | Path | None,
    course_id: int,
    assignment_id: int,
) -> list[dict[str, Any]]:
    """
    Collect grade summary rows for one assignment.

    Each row represents one student record.
    """

    project_store = ProjectStore(base_dir)
    course_store = project_store.course(course_id)
    assignment_store = course_store.assignment(assignment_id)

    manifest = assignment_store.load_manifest()
    student_records = manifest.get("student_records", {})

    points_possible = get_assignment_points_possible(assignment_store)

    rows: list[dict[str, Any]] = []

    for user_id_str in sorted(student_records.keys(), key=lambda x: int(x)):
        user_id = int(user_id_str)

        record = assignment_store.load_student_record(user_id)
        grade = assignment_store.load_grade_result(user_id)

        student = record.get("student", {})
        submission = record.get("submission", {})
        grading = record.get("grading", {})

        total_score_0_1 = grade.get("total_score_0_1")
        total_score_sum = grade.get("total_score_sum")

        canvas_score = None
        if total_score_0_1 is not None and points_possible is not None:
            try:
                canvas_score = float(total_score_0_1) * points_possible
            except Exception:
                canvas_score = None

        grade_status = grading.get("status", "not_graded")

        row = {
            "course_id": course_id,
            "assignment_id": assignment_id,
            "user_id": user_id,
            "student_name": student.get("name", ""),
            "student_email": student.get("email", ""),

            "submission_status": submission.get("download_status", ""),
            "submitted_at": submission.get("submitted_at", ""),
            "downloaded_at": submission.get("downloaded_at", ""),

            "grading_status": grade_status,
            "graded_at": grading.get("latest_graded_at", ""),
            "provider": grading.get("provider", ""),
            "model": grading.get("model", ""),

            "score_0_1": total_score_0_1,
            "score_sum": total_score_sum,
            "points_possible": points_possible,
            "canvas_score": canvas_score,

            "grade_file": str(assignment_store.grade_path(user_id))
            if assignment_store.grade_path(user_id).exists()
            else "",

            "error": grading.get("error", ""),
        }

        rows.append(row)

    return rows


def export_grades_summary(
    base_dir: str | Path | None,
    course_id: int,
    assignment_id: int,
    output_csv: str | Path | None = None,
) -> dict[str, Any]:
    """
    Export grades_summary.csv for one assignment.

    If output_csv is None, save to:
    assignment_xxx/grades_summary.csv
    """

    project_store = ProjectStore(base_dir)
    assignment_store = project_store.course(course_id).assignment(assignment_id)

    rows = collect_student_grade_rows(
        base_dir=base_dir,
        course_id=course_id,
        assignment_id=assignment_id,
    )

    if output_csv is None:
        output_path = assignment_store.assignment_dir / "grades_summary.csv"
    else:
        output_path = Path(output_csv)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "course_id",
        "assignment_id",
        "user_id",
        "student_name",
        "student_email",
        "submission_status",
        "submitted_at",
        "downloaded_at",
        "grading_status",
        "graded_at",
        "provider",
        "model",
        "score_0_1",
        "score_sum",
        "points_possible",
        "canvas_score",
        "grade_file",
        "error",
    ]

    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for row in rows:
            writer.writerow(row)

    manifest = assignment_store.load_manifest()
    manifest.setdefault("report_runs", []).append(
        {
            "run_at": utc_now_iso(),
            "type": "grades_summary_csv",
            "output_csv": str(output_path),
            "rows": len(rows),
        }
    )
    assignment_store.save_manifest(manifest)

    return {
        "course_id": course_id,
        "assignment_id": assignment_id,
        "output_csv": str(output_path),
        "rows": len(rows),
    }