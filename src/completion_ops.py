"""Submission-only grading. No LLM or student-file downloads."""
from __future__ import annotations

import csv
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def full_credit(assignment):
    kind = getattr(assignment, "grading_type", None)
    if kind == "not_graded":
        return None
    if kind == "pass_fail":
        return "complete"
    if kind not in {"points", "percent", "letter_grade", "gpa_scale"}:
        raise ValueError(f"Unsupported grading_type: {kind!r}")
    points = getattr(assignment, "points_possible", None)
    if points is None or not math.isfinite(float(points)) or float(points) < 0:
        raise ValueError("Assignment has invalid points_possible")
    # Canvas converts percentages through the assignment's own grading scheme.
    return "100%" if kind != "points" else str(points)


def submission_status(assignment, submission):
    if submission is None:
        return "unknown"  # Missing API record is not proof of non-submission.
    if getattr(submission, "assignment_visible", True) is False:
        return "not_assigned"
    if getattr(submission, "excused", False):
        return "excused"
    state = getattr(submission, "workflow_state", None)
    if state in {"submitted", "pending_review"} or (
        state == "graded" and getattr(submission, "submitted_at", None)
    ):
        return "submitted"
    types = set(getattr(assignment, "submission_types", []))
    if types & {"external_tool", "on_paper", "none"}:
        return "unknown"
    if state in {"unsubmitted", "graded"} and not getattr(submission, "submitted_at", None):
        return "missing"
    return "unknown"


def save_report(report, output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    report["counts"] = dict(Counter(row["status"] for row in report["students"]))
    report["actions"] = dict(Counter(row["action"] for row in report["students"]))
    target = output_dir / "completion_report.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)
    for filename, rows in (
        ("completion_report.csv", report["students"]),
        ("missing_students.csv", [r for r in report["students"] if r["status"] == "missing"]),
    ):
        with (output_dir / filename).open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=[
                "user_id", "name", "status", "submitted_at", "previous_grade",
                "target_grade", "action", "error",
            ])
            writer.writeheader()
            writer.writerows(rows)


def grade_completion(course, assignment, output_dir, *, apply=False, section=None, sections=None):
    selected_sections = sections if sections is not None else ([section] if section is not None else None)
    section_ids = {int(s.id) for s in selected_sections} if selected_sections is not None else None
    if section_ids == set():
        raise ValueError("Select at least one section")
    target = full_credit(assignment)
    if apply and getattr(assignment, "published", True) is False:
        raise ValueError("Cannot grade an unpublished assignment")
    if apply and getattr(assignment, "moderated_grading", False):
        raise ValueError("Moderated grading requires the Canvas moderation workflow")
    if apply and getattr(assignment, "group_category_id", None) and not getattr(assignment, "grade_group_students_individually", False):
        raise ValueError("Shared group grades require review in Canvas; use preview or individual grading")
    # SDK paginated iterators fetch every page; enrollments exclude Test Student.
    users = {}
    for enrollment in course.get_enrollments(type=["StudentEnrollment"], state=["active"]):
        if getattr(enrollment, "type", None) != "StudentEnrollment":
            continue
        if section_ids is not None and getattr(enrollment, "course_section_id", None) not in section_ids:
            continue
        user = enrollment.user
        users[int(enrollment.user_id)] = user.get("name", str(enrollment.user_id))
    submissions = {int(s.user_id): s for s in assignment.get_submissions(include=["visibility"], grouped=False)}
    visibility = getattr(assignment, "assignment_visibility", None)
    visible_ids = None if visibility is None else set(map(int, visibility))
    report = {
        "course_id": course.id, "assignment_id": assignment.id,
        "assignment_name": assignment.name,
        "section_id": int(section.id) if section is not None else None,
        "section_name": ", ".join(s.name for s in selected_sections) if selected_sections is not None else "All sections",
        "sections": [{"id": int(s.id), "name": s.name} for s in selected_sections] if selected_sections is not None else None,
        "grading_type": assignment.grading_type, "points_possible": getattr(assignment, "points_possible", None),
        "mode": "apply" if apply else "preview",
        "created_at": datetime.now(timezone.utc).isoformat(), "students": [],
    }
    for uid, name in sorted(users.items()):
        sub = submissions.get(uid)
        if visible_ids is not None and uid not in visible_ids:
            status = "not_assigned"
        elif visible_ids is None and getattr(assignment, "only_visible_to_overrides", False):
            status = "unknown"
        else:
            status = submission_status(assignment, sub)
        action = "skip"
        if status == "submitted" and target is not None:
            same_score = getattr(sub, "score", None) == getattr(assignment, "points_possible", None)
            if assignment.grading_type == "pass_fail":
                same_score = getattr(sub, "grade", None) in {"complete", "pass"}
            action = "already_full" if same_score and getattr(sub, "grade_matches_current_submission", False) else "would_grade"
        report["students"].append({
            "user_id": uid, "name": name, "status": status,
            "submitted_at": getattr(sub, "submitted_at", None),
            "previous_grade": getattr(sub, "grade", None),
            "target_grade": target if status == "submitted" else None,
            "action": action, "error": "",
        })
    save_report(report, output_dir)
    if apply:
        for row in report["students"]:
            if row["action"] != "would_grade":
                continue
            try:
                payload = {"posted_grade": target}
                sub = submissions[row["user_id"]]
                if getattr(sub, "late", False) or getattr(sub, "points_deducted", 0) or getattr(sub, "late_policy_status", None) in {"late", "missing"}:
                    # Submission-only credit includes late work: waive this
                    # submission's penalty, without changing the course policy.
                    payload["late_policy_status"] = "none"
                result = submissions[row["user_id"]].edit(
                    submission=payload,
                )
                row["action"] = "graded"
                row["error"] = ""
                if getattr(result, "points_deducted", 0):
                    row["action"] = "graded_with_late_penalty"
            except Exception as exc:
                row["action"] = "error"
                # API exception bodies can contain private data; record only type.
                row["error"] = type(exc).__name__
            save_report(report, output_dir)
    return report
