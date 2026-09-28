"""
Grading pipeline.

This module:
1. Loads prepared assignment materials.
2. Iterates through student records.
3. Calls the selected LLM grader.
4. Saves grade.json immediately after each student.
5. Updates record.json immediately after each student.
6. Catches LLM/file errors per student and continues.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.llm_grader_base import build_grader
from src.storage_ops import ProjectStore, save_json, utc_now_iso


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_material_path(assignment_store: Any, rel_path: str | None) -> Path | None:
    if not rel_path:
        return None

    path = assignment_store.assignment_dir / rel_path

    if not path.exists():
        return None

    return path


def should_grade_student(
    record: dict[str, Any],
    grade_file_exists: bool,
    force_grade: bool,
) -> bool:
    """Decide whether to grade one student."""

    if force_grade:
        return True

    if not grade_file_exists:
        return True

    grading = record.get("grading", {})
    submission = record.get("submission", {})

    if grading.get("status") != "graded":
        return True

    if grading.get("input_submitted_at") != submission.get("submitted_at"):
        return True

    return False


def build_final_grade_json(
    course_id: int,
    assignment_id: int,
    user_id: int,
    record: dict[str, Any],
    assignment_pdf: Path,
    submission_pdf: Path,
    presence_result: dict[str, Any],
    grade_result: dict[str, Any],
    provider: str,
    model: str,
) -> dict[str, Any]:
    """Build final grade.json saved for one student."""

    submission = record.get("submission", {})

    return {
        "course_id": course_id,
        "assignment_id": assignment_id,
        "user_id": user_id,
        "graded_at": utc_now_iso(),
        "student": record.get("student", {}),
        "input": {
            "assignment_pdf": str(assignment_pdf),
            "submission_pdf": str(submission_pdf),
            "input_submitted_at": submission.get("submitted_at"),
            "input_downloaded_at": submission.get("downloaded_at"),
        },
        "llm": {
            "provider": provider,
            "model": model,
        },
        "presence": presence_result,
        "grading": grade_result,
        "total_score_0_1": grade_result.get("unweighted_total_0_1"),
        "total_score_sum": grade_result.get("unweighted_total_sum"),
    }


def update_record_after_grade(
    record: dict[str, Any],
    grade_data: dict[str, Any],
) -> dict[str, Any]:
    """Update record.json after successful grading."""

    record["grading"] = {
        "status": "graded",
        "latest_grade_file": "grade.json",
        "latest_graded_at": grade_data.get("graded_at"),
        "latest_score": grade_data.get("total_score_0_1"),
        "latest_score_sum": grade_data.get("total_score_sum"),
        "provider": grade_data.get("llm", {}).get("provider"),
        "model": grade_data.get("llm", {}).get("model"),
        "input_submitted_at": grade_data.get("input", {}).get("input_submitted_at"),
    }

    record.setdefault("history", []).append(
        {
            "event": "graded",
            "time": utc_now_iso(),
            "details": {
                "score_0_1": grade_data.get("total_score_0_1"),
                "score_sum": grade_data.get("total_score_sum"),
                "provider": grade_data.get("llm", {}).get("provider"),
                "model": grade_data.get("llm", {}).get("model"),
            },
        }
    )

    return record


def update_record_after_grade_error(
    record: dict[str, Any],
    error: str,
    provider: str,
    model: str,
) -> dict[str, Any]:
    """Update record.json after grading error."""

    record["grading"] = {
        "status": "grade_error",
        "latest_grade_file": None,
        "latest_graded_at": None,
        "latest_score": None,
        "latest_score_sum": None,
        "provider": provider,
        "model": model,
        "error": error,
        "input_submitted_at": record.get("submission", {}).get("submitted_at"),
    }

    record.setdefault("history", []).append(
        {
            "event": "grade_error",
            "time": utc_now_iso(),
            "details": {
                "error": error,
                "provider": provider,
                "model": model,
            },
        }
    )

    return record


def grade_assignment_submissions(
    course_match: Any,
    assignment_match: Any,
    base_dir: str | Path | None = None,
    provider: str = "openai",
    model: str | None = None,
    force_grade: bool = False,
    max_students: int | None = None,
    dry_run_grade: bool = True,
) -> dict[str, Any]:
    """
    Grade downloaded submissions.

    dry_run_grade:
    - Currently only means "do not post to Canvas".
    - This function still writes local grade.json and record.json.
    - Canvas posting is not implemented yet.
    """

    course_id = int(course_match.id)
    assignment_id = int(assignment_match.id)

    project_store = ProjectStore(base_dir)
    course_store = project_store.course(course_id)
    assignment_store = course_store.assignment(assignment_id)

    assignment_config = assignment_store.ensure_assignment_config(assignment_match)
    materials = assignment_config.get("materials", {})

    assignment_pdf = resolve_material_path(assignment_store, materials.get("problem_set_pdf"))
    presence_prompt_path = resolve_material_path(assignment_store, materials.get("presence_prompt"))
    grading_prompt_path = resolve_material_path(assignment_store, materials.get("grading_prompt"))
    presence_schema_path = resolve_material_path(assignment_store, materials.get("presence_schema"))
    grading_schema_path = resolve_material_path(assignment_store, materials.get("grading_schema"))

    missing_materials = [
        name
        for name, path in {
            "problem_set_pdf": assignment_pdf,
            "presence_prompt": presence_prompt_path,
            "grading_prompt": grading_prompt_path,
            "presence_schema": presence_schema_path,
            "grading_schema": grading_schema_path,
        }.items()
        if path is None
    ]

    if missing_materials:
        raise FileNotFoundError(
            "Missing assignment materials. Run --prepare-assignment first. Missing: "
            + ", ".join(missing_materials)
        )

    presence_prompt = read_text(presence_prompt_path)
    grading_prompt = read_text(grading_prompt_path)
    presence_template = load_json(presence_schema_path)
    grading_template = load_json(grading_schema_path)

    grader = build_grader(provider=provider, model=model)

    manifest = assignment_store.load_manifest()
    student_records = manifest.get("student_records", {})
    user_ids = [int(user_id) for user_id in student_records.keys()]

    if max_students is not None:
        user_ids = user_ids[:max_students]

    stats = {
        "available_student_records": len(student_records),
        "processed": len(user_ids),
        "graded": 0,
        "skipped_already_graded": 0,
        "skipped_no_submission_pdf": 0,
        "skipped_not_submitted": 0,
        "errors": 0,
    }

    run_started_at = utc_now_iso()

    for index, user_id in enumerate(user_ids, start=1):
        record = assignment_store.load_student_record(user_id)
        student_name = record.get("student", {}).get("name") or ""
        display_name = student_name or f"user_{user_id}"

        submission = record.get("submission", {})
        submission_pdf = assignment_store.submission_pdf_path(user_id)

        prefix = f"[{index}/{len(user_ids)}] {user_id} | {display_name}"

        if submission.get("download_status") not in {"downloaded", "skipped_current"}:
            stats["skipped_not_submitted"] += 1
            print(f"{prefix} | skipped: not submitted")
            continue

        if not submission_pdf.exists():
            stats["skipped_no_submission_pdf"] += 1
            print(f"{prefix} | skipped: no submission.pdf")
            continue

        if not should_grade_student(
            record=record,
            grade_file_exists=assignment_store.grade_path(user_id).exists(),
            force_grade=force_grade,
        ):
            stats["skipped_already_graded"] += 1
            latest_score = record.get("grading", {}).get("latest_score")
            print(f"{prefix} | skipped: already graded | score={latest_score}")
            continue

        try:
            presence_result = grader.check_presence(
                assignment_pdf=assignment_pdf,
                submission_pdf=submission_pdf,
                presence_prompt=presence_prompt,
                presence_template=presence_template,
            )

            grade_result = grader.grade_submission(
                assignment_pdf=assignment_pdf,
                submission_pdf=submission_pdf,
                grading_prompt=grading_prompt,
                grading_template=grading_template,
                presence_result=presence_result,
            )

            grade_data = build_final_grade_json(
                course_id=course_id,
                assignment_id=assignment_id,
                user_id=user_id,
                record=record,
                assignment_pdf=assignment_pdf,
                submission_pdf=submission_pdf,
                presence_result=presence_result,
                grade_result=grade_result,
                provider=grader.provider,
                model=grader.model,
            )

            assignment_store.save_grade_result(user_id, grade_data)

            record = update_record_after_grade(record, grade_data)
            assignment_store.save_student_record(user_id, record)

            stats["graded"] += 1

            score = grade_data.get("total_score_0_1")
            score_sum = grade_data.get("total_score_sum")
            print(f"{prefix} | graded | score={score:.3f} | sum={score_sum:.3f}")

        except Exception as e:
            error_message = str(e)

            record = update_record_after_grade_error(
                record=record,
                error=error_message,
                provider=grader.provider,
                model=grader.model,
            )

            assignment_store.save_student_record(user_id, record)

            stats["errors"] += 1

            short_error = error_message.replace("\n", " ")[:180]
            print(f"{prefix} | error | {short_error}")

            continue

    run_finished_at = utc_now_iso()

    manifest["last_graded_at"] = run_finished_at
    manifest.setdefault("grading_runs", []).append(
        {
            "run_started_at": run_started_at,
            "run_finished_at": run_finished_at,
            "provider": grader.provider,
            "model": grader.model,
            "force_grade": force_grade,
            "max_students": max_students,
            "dry_run_grade": dry_run_grade,
            "stats": stats,
        }
    )

    assignment_store.save_manifest(manifest)

    return {
        "course_id": course_id,
        "assignment_id": assignment_id,
        "assignment_dir": str(assignment_store.assignment_dir),
        "provider": grader.provider,
        "model": grader.model,
        "dry_run_grade": dry_run_grade,
        "force_grade": force_grade,
        "max_students": max_students,
        "stats": stats,
    }