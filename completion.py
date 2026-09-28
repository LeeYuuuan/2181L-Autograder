"""CLI for full credit on submitted Canvas assignments."""
import argparse
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="Batch grading parameters (.toml)")
    course = parser.add_mutually_exclusive_group()
    course.add_argument("--course-id", type=int)
    course.add_argument("--course-keywords")
    assignment = parser.add_mutually_exclusive_group()
    assignment.add_argument("--assignment-id", type=int)
    assignment.add_argument("--assignment-keywords")
    parser.add_argument("--list-courses", action="store_true")
    parser.add_argument("--list-assignments", action="store_true")
    parser.add_argument("--list-sections", action="store_true", help="List course sections and exit")
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--section-id", type=int, help="Only process students enrolled in this section")
    scope.add_argument("--all-sections", action="store_true", help="Explicitly process the whole course")
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--apply", action="store_true", help="Write grades to Canvas (default: preview)")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    if args.config and any((args.course_id is not None, args.course_keywords is not None,
                            args.assignment_id is not None, args.assignment_keywords is not None,
                            args.section_id is not None, args.all_sections, args.apply,
                            args.output_dir is not None, args.list_courses, args.list_sections,
                            args.list_assignments)):
        parser.error("Use --config alone; set course, assignments, sections and mode in the config file")

    from dotenv import load_dotenv
    from src.canvas_ops import get_canvas_client, resolve_course, resolve_assignment
    from src.completion_ops import grade_completion
    from src.section_ops import list_sections, select_section

    load_dotenv(Path(__file__).with_name(".env"))
    try:
        if args.config:
            from src.batch_completion import load_config, run_batch
            config = load_config(args.config)
            return run_batch(get_canvas_client(), config)
        canvas = get_canvas_client()
        if args.list_courses:
            for item in canvas.get_courses():
                print(f"{item.id}\t{getattr(item, 'name', '')}\t{getattr(item, 'course_code', '')}")
            return 0
        course = resolve_course(canvas, args.course_id, args.course_keywords,
                                interactive=not args.non_interactive).raw
        if args.list_sections:
            list_sections(course)
            return 0
        if args.list_assignments:
            for item in course.get_assignments():
                print(f"{item.id}\t{item.name}\t{item.grading_type}\t{getattr(item, 'points_possible', None)}")
            return 0
        section = select_section(course, section_id=args.section_id,
                                 all_sections=args.all_sections, interactive=not args.non_interactive)
        scope_name = f"{section.name} (ID {section.id})" if section else "ALL SECTIONS"
        print(f"\nSelected scope: {scope_name}")
        selected = resolve_assignment(course, args.assignment_id, args.assignment_keywords,
                                      interactive=not args.non_interactive)
        assignment = course.get_assignment(selected.id, include=["assignment_visibility"])
        output = args.output_dir or Path("data/completion") / f"course_{course.id}" / f"assignment_{assignment.id}"
        if args.output_dir is None:
            output /= f"section_{section.id}" if section else "all_sections"
        report = grade_completion(course, assignment, output, apply=args.apply, section=section)
        print(f"\nMode: {report['mode']} | grading_type: {assignment.grading_type}")
        for status in ("submitted", "missing", "excused", "not_assigned", "unknown"):
            print(f"{status}: {report['counts'].get(status, 0)}")
        print("\nMissing students (Canvas user ID / name):")
        for row in report["students"]:
            if row["status"] == "missing":
                print(f"{row['user_id']}\t{row['name']}")
        print(f"Actions: {report['actions']}")
        print(f"Reports: {output.resolve()}")
        return 1 if report["actions"].get("error") else 0
    except ValueError as exc:
        parser.error(str(exc))
    except Exception as exc:
        print(f"Canvas operation failed ({type(exc).__name__}). Check credentials, permissions and network.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
