"""Configuration-driven grading for a union of sections and multiple assignments."""
import json
from pathlib import Path
import tomllib

from src.completion_ops import full_credit, grade_completion


def load_config(path):
    path = Path(path).resolve()
    with path.open("rb") as handle:
        config = tomllib.load(handle)
    unknown = set(config) - {"course_id", "assignment_ids", "section_ids", "mode", "output_dir"}
    if unknown:
        raise ValueError(f"Unknown config keys: {sorted(unknown)}")
    if type(config.get("course_id")) is not int or config["course_id"] <= 0:
        raise ValueError("Set course_id to a positive Canvas course ID")
    for key in ("assignment_ids", "section_ids"):
        value = config.get(key)
        if not isinstance(value, list) or not value or any(type(i) is not int or i <= 0 for i in value):
            raise ValueError(f"{key} must be a nonempty list of positive Canvas IDs")
        config[key] = list(dict.fromkeys(value))
    if config.get("mode", "preview") not in {"preview", "apply"}:
        raise ValueError('mode must be "preview" or "apply"')
    config.setdefault("mode", "preview")
    output = config.get("output_dir", "data/completion")
    if not isinstance(output, str) or not output.strip():
        raise ValueError("output_dir must be a nonempty path string")
    config["output_dir"] = path.parent / output
    return config


def print_summary(report):
    print(f"\n{report['assignment_name']} (ID {report['assignment_id']}) | {report['mode']}")
    for status in ("submitted", "missing", "excused", "not_assigned", "unknown"):
        print(f"{status}: {report['counts'].get(status, 0)}")
    print("Missing students (Canvas ID / name):")
    for row in report["students"]:
        if row["status"] == "missing":
            print(f"{row['user_id']}\t{row['name']}")
    print(f"Actions: {report['actions']}")


def run_batch(canvas, config):
    course = canvas.get_course(config["course_id"])
    available = {int(s.id): s for s in course.get_sections()}
    missing = set(config["section_ids"]) - set(available)
    if missing:
        raise ValueError(f"Sections are not accessible in this course: {sorted(missing)}")
    sections = [available[i] for i in config["section_ids"]]
    # Resolve and validate the entire selection before any writes.
    assignments = [course.get_assignment(i, include=["assignment_visibility"])
                   for i in config["assignment_ids"]]
    apply = config["mode"] == "apply"
    for assignment in assignments:
        full_credit(assignment)
        if apply and (getattr(assignment, "published", True) is False
                      or getattr(assignment, "moderated_grading", False)
                      or (getattr(assignment, "group_category_id", None)
                          and not getattr(assignment, "grade_group_students_individually", False))):
            raise ValueError(f"Assignment {assignment.id} cannot be automatically graded; use preview")
    print(f"Course: {getattr(course, 'name', course.id)} | Mode: {config['mode']}")
    for section in sections:
        print(f"Section: {section.name} (ID {section.id})")
    scope = "sections_" + "_".join(map(str, sorted(config["section_ids"])))
    root = config["output_dir"] / f"course_{course.id}" / scope
    root.mkdir(parents=True, exist_ok=True)
    summaries = []
    failed = False
    for assignment in assignments:
        output = root / f"assignment_{assignment.id}"
        report = grade_completion(course, assignment, output, apply=apply, sections=sections)
        print_summary(report)
        summaries.append({key: report[key] for key in (
            "assignment_id", "assignment_name", "mode", "sections", "counts", "actions")})
        summaries[-1]["report_dir"] = str(output.resolve())
        (root / "batch_summary.json").write_text(json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8")
        failed = failed or bool(report["actions"].get("error"))
    print(f"\nReports: {root.resolve()}")
    return 1 if failed else 0
