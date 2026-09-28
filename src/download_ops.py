"""
Download utilities for Canvas assignment submissions.

Current behavior:
1. Save course_info.json.
2. Save assignment_info.json.
3. Create assignment_config.json if missing.
4. Maintain course roster.
5. Download/update each student's latest PDF submission.
6. Maintain per-student record.json.
7. Maintain assignment manifest.json.
8. Support max_students, force_download.

No dry_run here:
- Download only affects local files.
- True dry-run behavior should be implemented later in grading/posting logic.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import requests
from tqdm import tqdm

from src.storage_ops import (
    ProjectStore,
    ensure_dir,
    make_json_safe,
    utc_now_iso,
)


def get_attr(obj: Any, key: str, default: Any = None) -> Any:
    """Get attribute from CanvasAPI object or dict."""

    if isinstance(obj, dict):
        return obj.get(key, default)

    return getattr(obj, key, default)


def object_to_dict(obj: Any) -> dict[str, Any]:
    """Convert an object into a JSON-safe dictionary."""

    safe_obj = make_json_safe(obj)

    if isinstance(safe_obj, dict):
        return safe_obj

    return {"value": safe_obj}


def get_student_info_from_submission(submission: Any) -> dict[str, Any]:
    """Extract student information from a submission object."""

    user = get_attr(submission, "user", None)

    if not user:
        return {
            "name": "",
            "email": None,
        }

    if isinstance(user, dict):
        name = user.get("name") or user.get("sortable_name") or ""
        email = user.get("email") or user.get("login_id")
    else:
        name = getattr(user, "name", "") or getattr(user, "sortable_name", "")
        email = getattr(user, "email", None) or getattr(user, "login_id", None)

    return {
        "name": name,
        "email": email,
    }


def get_submission_attachments(submission: Any) -> list[dict[str, Any]]:
    """Get submission attachments."""

    attachments = get_attr(submission, "attachments", None)

    if not attachments:
        return []

    return [object_to_dict(item) for item in attachments]


def pick_latest_pdf_attachment(attachments: list[dict[str, Any]]) -> dict[str, Any] | None:
    """
    Pick one PDF attachment.

    Rule:
    - Accept content_type == application/pdf or filename ending with .pdf.
    - If multiple PDFs exist, choose the last one.
    """

    pdfs: list[dict[str, Any]] = []

    for item in attachments:
        filename = str(item.get("filename") or item.get("display_name") or "")
        content_type = str(item.get("content-type") or item.get("content_type") or "")

        if content_type.lower() == "application/pdf" or filename.lower().endswith(".pdf"):
            pdfs.append(item)

    if not pdfs:
        return None

    return pdfs[-1]


def should_download_submission(
    local_pdf_path: Path,
    previous_record: dict[str, Any] | None,
    canvas_submitted_at: str | None,
    force: bool = False,
) -> bool:
    """
    Decide whether to download a submission.

    Download if:
    1. force=True
    2. local PDF does not exist
    3. previous record does not exist
    4. submitted_at changed
    """

    if force:
        return True

    if not local_pdf_path.exists():
        return True

    if not previous_record:
        return True

    previous_submission = previous_record.get("submission", {})
    cached_submitted_at = previous_submission.get("submitted_at")

    if canvas_submitted_at != cached_submitted_at:
        return True

    return False


def download_file(
    url: str,
    output_path: Path,
    canvas_token: str | None = None,
) -> None:
    """Download one file."""

    ensure_dir(output_path.parent)

    headers = {}

    if canvas_token:
        headers["Authorization"] = f"Bearer {canvas_token}"

    with requests.get(url, headers=headers, stream=True, timeout=120) as response:
        response.raise_for_status()

        with output_path.open("wb") as f:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)


def update_record_history(
    record: dict[str, Any],
    event: str,
    details: dict[str, Any] | None = None,
) -> None:
    """Append one event to record history."""

    record.setdefault("history", []).append(
        {
            "event": event,
            "time": utc_now_iso(),
            "details": details or {},
        }
    )


def download_assignment_submissions(
    course_match: Any,
    assignment_match: Any,
    base_dir: str | Path | None = None,
    canvas_token: str | None = None,
    force: bool = False,
    max_students: int | None = None,

) -> dict[str, Any]:
    """
    Download or update submissions for one assignment.

    Parameters:
    - course_match: MatchResult from resolve_course()
    - assignment_match: MatchResult from resolve_assignment()
    - base_dir: custom root directory
    - canvas_token: Canvas token for downloading file URLs
    - force: force redownload
    - max_students: only process first N submissions

    """

    course_id = int(course_match.id)
    assignment_id = int(assignment_match.id)

    project_store = ProjectStore(base_dir)
    course_store = project_store.course(course_id)
    assignment_store = course_store.assignment(assignment_id)

    course_store.save_course_info_from_match(course_match)
    assignment_store.save_assignment_info_from_match(assignment_match)
    assignment_store.ensure_assignment_config(assignment_match)

    manifest = assignment_store.load_manifest()

    run_started_at = utc_now_iso()
    manifest["last_checked_at"] = run_started_at

    assignment = assignment_match.raw

    submissions = list(
        assignment.get_submissions(
            include=["user"],
        )
    )

    canvas_total_submissions = len(submissions)

    if max_students is not None:
        submissions_to_process = submissions[:max_students]
    else:
        submissions_to_process = submissions

    stats = {
        "canvas_total_submissions": canvas_total_submissions,
        "processed": len(submissions_to_process),
        "downloaded": 0,
        "skipped_current": 0,
        "missing": 0,
        "no_pdf": 0,
        "errors": 0,
    }

    for submission in tqdm(submissions_to_process, desc="Downloading submissions"):
        user_id = get_attr(submission, "user_id")

        if user_id is None:
            stats["errors"] += 1
            continue

        user_id = int(user_id)

        student_info = get_student_info_from_submission(submission)
        student_name = student_info.get("name", "")
        student_email = student_info.get("email")

        record = assignment_store.load_student_record(user_id)

        record["student"] = {
            "name": student_name,
            "email": student_email,
        }

        submitted_at = get_attr(submission, "submitted_at")
        workflow_state = get_attr(submission, "workflow_state")
        attempt = get_attr(submission, "attempt")
        late = get_attr(submission, "late")
        missing = get_attr(submission, "missing")

        attachments = get_submission_attachments(submission)
        selected_pdf = pick_latest_pdf_attachment(attachments)

        local_pdf_path = assignment_store.submission_pdf_path(user_id)

        submission_record = {
            "workflow_state": workflow_state,
            "submitted_at": submitted_at,
            "attempt": attempt,
            "late": late,
            "missing": missing,
            "attachments": attachments,
            "selected_file": str(local_pdf_path.name),
            "selected_attachment": selected_pdf,
            "download_status": None,
            "downloaded_at": None,
            "checked_at": utc_now_iso(),
        }

        if not submitted_at or workflow_state == "unsubmitted" or missing:
            submission_record["download_status"] = "missing_or_unsubmitted"

            record["submission"] = submission_record
            update_record_history(
                record,
                event="submission_checked",
                details={
                    "status": "missing_or_unsubmitted",
                },
            )

            assignment_store.save_student_record(user_id, record)
            assignment_store.update_manifest_student_record(manifest, user_id)

            course_store.upsert_student_in_roster(
                user_id=user_id,
                student_name=student_name,
                email=student_email,
                assignment_id=assignment_id,
                record_rel_path=assignment_store.record_rel_path_from_course_dir(user_id),
            )

            stats["missing"] += 1
            continue

        if selected_pdf is None:
            submission_record["download_status"] = "no_pdf_attachment"

            record["submission"] = submission_record
            update_record_history(
                record,
                event="submission_checked",
                details={
                    "status": "no_pdf_attachment",
                },
            )

            assignment_store.save_student_record(user_id, record)
            assignment_store.update_manifest_student_record(manifest, user_id)

            course_store.upsert_student_in_roster(
                user_id=user_id,
                student_name=student_name,
                email=student_email,
                assignment_id=assignment_id,
                record_rel_path=assignment_store.record_rel_path_from_course_dir(user_id),
            )

            stats["no_pdf"] += 1
            continue

        file_url = selected_pdf.get("url")

        if not file_url:
            submission_record["download_status"] = "attachment_url_missing"

            record["submission"] = submission_record
            update_record_history(
                record,
                event="download_error",
                details={
                    "reason": "attachment_url_missing",
                },
            )

            assignment_store.save_student_record(user_id, record)
            assignment_store.update_manifest_student_record(manifest, user_id)

            course_store.upsert_student_in_roster(
                user_id=user_id,
                student_name=student_name,
                email=student_email,
                assignment_id=assignment_id,
                record_rel_path=assignment_store.record_rel_path_from_course_dir(user_id),
            )

            stats["errors"] += 1
            continue

        needs_download = should_download_submission(
            local_pdf_path=local_pdf_path,
            previous_record=record,
            canvas_submitted_at=submitted_at,
            force=force,
        )

        if not needs_download:
            previous_submission = record.get("submission", {})

            submission_record["download_status"] = "skipped_current"
            submission_record["downloaded_at"] = previous_submission.get("downloaded_at")

            record["submission"] = submission_record
            update_record_history(
                record,
                event="download_skipped",
                details={
                    "reason": "local_file_current",
                    "submitted_at": submitted_at,
                },
            )

            assignment_store.save_student_record(user_id, record)
            assignment_store.update_manifest_student_record(manifest, user_id)

            course_store.upsert_student_in_roster(
                user_id=user_id,
                student_name=student_name,
                email=student_email,
                assignment_id=assignment_id,
                record_rel_path=assignment_store.record_rel_path_from_course_dir(user_id),
            )

            stats["skipped_current"] += 1
            continue

        try:
            download_file(
                url=file_url,
                output_path=local_pdf_path,
                canvas_token=canvas_token,
            )

            submission_record["download_status"] = "downloaded"
            submission_record["downloaded_at"] = utc_now_iso()

            record["submission"] = submission_record
            update_record_history(
                record,
                event="downloaded",
                details={
                    "local_file": str(local_pdf_path),
                    "submitted_at": submitted_at,
                },
            )

            stats["downloaded"] += 1

        except Exception as e:
            submission_record["download_status"] = "download_error"

            record["submission"] = submission_record
            update_record_history(
                record,
                event="download_error",
                details={
                    "error": str(e),
                },
            )

            stats["errors"] += 1

        assignment_store.save_student_record(user_id, record)
        assignment_store.update_manifest_student_record(manifest, user_id)

        course_store.upsert_student_in_roster(
            user_id=user_id,
            student_name=student_name,
            email=student_email,
            assignment_id=assignment_id,
            record_rel_path=assignment_store.record_rel_path_from_course_dir(user_id),
        )

    run_finished_at = utc_now_iso()

    manifest["last_downloaded_at"] = run_finished_at
    manifest["stats"] = stats

    manifest.setdefault("download_runs", []).append(
        {
            "run_started_at": run_started_at,
            "run_finished_at": run_finished_at,
            "max_students": max_students,
            "force": force,
            "stats": stats,
        }
    )

    assignment_store.save_manifest(manifest)

    return {
        "course_id": course_id,
        "assignment_id": assignment_id,
        "assignment_dir": str(assignment_store.assignment_dir),
        "max_students": max_students,
        "force": force,
        "stats": stats,
    }