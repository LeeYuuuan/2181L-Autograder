"""
Main entry for the current run-all pipeline.

Current pipeline:
1. Connect to Canvas.
2. Match course.
3. Match assignment.
4. Optionally prepare assignment materials.
5. Download/update assignment submissions.
6. Optionally grade submissions.

Dry run note:
- Download has no dry-run because it only changes local files.
- Grade dry-run means do not post grades to Canvas.
- Local grade.json is still written.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from dotenv import load_dotenv

from src.assignment_prep_ops import prepare_assignment_materials
from src.canvas_ops import (
    get_canvas_client,
    resolve_assignment,
    resolve_course,
)
from src.download_ops import download_assignment_submissions
from src.grade_ops import grade_assignment_submissions
from src.storage_ops import clear_assignment_cache
from src.report_ops import export_grades_summary
from src.publish_ops import publish_assignment_grades

# ---------------------------------------------------------------------
# Default values for local testing
# ---------------------------------------------------------------------

DEFAULT_BASE_DIR = None

DEFAULT_COURSE_ID = None
DEFAULT_COURSE_KEYWORDS = None

DEFAULT_ASSIGNMENT_ID = None
DEFAULT_ASSIGNMENT_KEYWORDS = None

DEFAULT_FORCE_DOWNLOAD = False
DEFAULT_MAX_STUDENTS = None
DEFAULT_NON_INTERACTIVE = False
DEFAULT_CLEAR_ASSIGNMENT_CACHE = False

DEFAULT_PREPARE_ASSIGNMENT = False
DEFAULT_PREPARE_ONLY = False
DEFAULT_PREPARE_MODEL = "gpt-4.1"

DEFAULT_GRADE = False
DEFAULT_PROVIDER = "openai"
DEFAULT_MODEL = "gpt-4.1"
DEFAULT_FORCE_GRADE = False
DEFAULT_DRY_RUN_GRADE = True

DEFAULT_EXPORT_GRADES = False
DEFAULT_OUTPUT_CSV = None

DEFAULT_PUBLISH_GRADES = False
DEFAULT_DRY_RUN_PUBLISH = True
DEFAULT_MAX_POST_UPDATES = None
DEFAULT_PUBLISH_MESSAGE = None
DEFAULT_FORCE_PUBLISH = False



# ---------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------


def print_header(title: str) -> None:
    print()
    print("=" * 60)
    print(title)
    print("=" * 60)


def print_step(step: int, total: int, title: str) -> None:
    print()
    print(f"[{step}/{total}] {title}")
    print("-" * 60)


def print_download_summary(result: dict) -> None:
    stats = result["stats"]

    canvas_total = stats.get("canvas_total_submissions", 0)
    processed = stats.get("processed", 0)
    need_download = stats.get("need_download", 0)
    downloaded = stats.get("downloaded", 0)
    skipped = stats.get("skipped_current", 0)
    errors = stats.get("errors", 0)
    missing = stats.get("missing", 0)
    no_pdf = stats.get("no_pdf", 0)

    print()
    print("Download summary:")
    print("-" * 60)
    print(f"  Canvas submissions:     {canvas_total}")
    print(f"  Processed this run:     {processed}")

    if downloaded == 0 and errors == 0:
        print("  No new files downloaded.")
        print(f"  Skipped current files:  {skipped}")
    else:
        print(f"  Need download/update:   {need_download}")
        print(f"  Downloaded:             {downloaded}")
        print(f"  Skipped current files:  {skipped}")

    if missing:
        print(f"  Missing/unsubmitted:    {missing}")

    if no_pdf:
        print(f"  No PDF attachment:      {no_pdf}")

    if errors:
        print(f"  Errors:                 {errors}")


def print_grade_summary(result: dict) -> None:
    stats = result["stats"]

    print()
    print("Grade summary:")
    print("-" * 60)
    print(f"  Provider:                 {result['provider']}")
    print(f"  Model:                    {result['model']}")
    print(f"  Dry-run grade:            {result['dry_run_grade']}")
    print(f"  Available records:        {stats.get('available_student_records', 0)}")
    print(f"  Processed this run:       {stats.get('processed', 0)}")
    print(f"  Graded:                   {stats.get('graded', 0)}")
    print(f"  Skipped already graded:   {stats.get('skipped_already_graded', 0)}")

    if stats.get("skipped_no_submission_pdf", 0):
        print(f"  Skipped no PDF:           {stats.get('skipped_no_submission_pdf', 0)}")

    if stats.get("skipped_not_submitted", 0):
        print(f"  Skipped not submitted:    {stats.get('skipped_not_submitted', 0)}")

    if stats.get("errors", 0):
        print(f"  Errors:                   {stats.get('errors', 0)}")


def print_export_summary(result: dict) -> None:
    """Print export summary."""

    print()
    print("Export summary:")
    print("-" * 60)
    print(f"  Rows:        {result['rows']}")
    print(f"  Output CSV:  {result['output_csv']}")


def print_publish_summary(result: dict) -> None:
    """Print publish summary."""

    stats = result["stats"]

    print()
    print("Publish summary:")
    print("-" * 60)
    print(f"  Dry-run publish:            {result['dry_run_publish']}")
    print(f"  Max post updates:           {result['max_post_updates']}")
    print(f"  Processed this run:         {stats.get('processed', 0)}")
    print(f"  Published:                  {stats.get('published', 0)}")
    print(f"  Dry-run would publish:      {stats.get('dry_run_would_publish', 0)}")

    if stats.get("skipped_missing_grade_json", 0):
        print(f"  Skipped missing grade.json: {stats.get('skipped_missing_grade_json', 0)}")

    if stats.get("skipped_not_graded", 0):
        print(f"  Skipped not graded:         {stats.get('skipped_not_graded', 0)}")

    if stats.get("skipped_already_published", 0):
        print(f"  Skipped already published:  {stats.get('skipped_already_published', 0)}")

    if stats.get("skipped_no_score", 0):
        print(f"  Skipped no score:           {stats.get('skipped_no_score', 0)}")

    if stats.get("errors", 0):
        print(f"  Errors:                     {stats.get('errors', 0)}")


def resolve_problem_pdf_path(problem_pdf: str | None, assignment_name: str) -> str:
    if problem_pdf:
        return problem_pdf

    name = str(assignment_name).strip()
    compact = name.replace(" ", "")
    lower = compact.lower()

    candidates = [
        Path("hw") / f"{name}.pdf",
        Path("hw") / f"{compact}.pdf",
        Path("hw") / f"{lower}.pdf",
    ]

    # Special case: HW3 -> hw03.pdf
    if lower.startswith("hw"):
        number_part = lower.replace("hw", "", 1)

        if number_part.isdigit():
            candidates.append(Path("hw") / f"hw{int(number_part):02d}.pdf")
            candidates.append(Path("hw") / f"HW{int(number_part):02d}.pdf")

    for path in candidates:
        if path.exists():
            return str(path)

    candidate_text = "\n".join(f"  - {path}" for path in candidates)

    raise FileNotFoundError(
        "Missing problem PDF. Please provide --problem-pdf, "
        "or place the file in one of these default locations:\n"
        f"{candidate_text}"
    )


# ---------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Canvas autograder run-all pipeline."
    )

    parser.add_argument(
        "--base-dir",
        type=str,
        default=DEFAULT_BASE_DIR,
        help="Root directory for downloaded Canvas data. Default: data/canvas_downloads",
    )

    parser.add_argument(
        "--course-id",
        type=int,
        default=DEFAULT_COURSE_ID,
        help="Canvas course ID.",
    )

    parser.add_argument(
        "--course-keywords",
        type=str,
        default=DEFAULT_COURSE_KEYWORDS,
        help="Keywords to match Canvas course by name or course_code.",
    )

    parser.add_argument(
        "--assignment-id",
        type=int,
        default=DEFAULT_ASSIGNMENT_ID,
        help="Canvas assignment ID.",
    )

    parser.add_argument(
        "--assignment-keywords",
        type=str,
        default=DEFAULT_ASSIGNMENT_KEYWORDS,
        help="Keywords to match Canvas assignment by name.",
    )

    parser.add_argument(
        "--force-download",
        action="store_true",
        default=DEFAULT_FORCE_DOWNLOAD,
        help="Force redownload all available PDF submissions.",
    )

    parser.add_argument(
        "--max-students",
        type=int,
        default=DEFAULT_MAX_STUDENTS,
        help="Only process the first N submissions. Use 0 or negative value to process all.",
    )

    parser.add_argument(
        "--clear-assignment-cache",
        action="store_true",
        default=DEFAULT_CLEAR_ASSIGNMENT_CACHE,
        help="Clear local cache for the matched assignment, then exit.",
    )

    parser.add_argument(
        "--non-interactive",
        action="store_true",
        default=DEFAULT_NON_INTERACTIVE,
        help="Disable interactive selection if multiple matches are found.",
    )

    parser.add_argument(
        "--prepare-assignment",
        action="store_true",
        default=DEFAULT_PREPARE_ASSIGNMENT,
        help="Prepare assignment materials from official homework PDF.",
    )

    parser.add_argument(
        "--prepare-only",
        action="store_true",
        default=DEFAULT_PREPARE_ONLY,
        help="Only prepare assignment materials, then exit.",
    )

    parser.add_argument(
        "--problem-pdf",
        type=str,
        default=None,
        help="Path to official homework PDF used for assignment preparation.",
    )

    parser.add_argument(
        "--prepare-model",
        type=str,
        default=DEFAULT_PREPARE_MODEL,
        help="Model used to extract assignment structure.",
    )

    parser.add_argument(
        "--grade",
        action="store_true",
        default=DEFAULT_GRADE,
        help="Grade downloaded submissions after download/update.",
    )

    parser.add_argument(
        "--provider",
        type=str,
        default=DEFAULT_PROVIDER,
        help="Grader provider: openai or dummy.",
    )

    parser.add_argument(
        "--model",
        type=str,
        default=DEFAULT_MODEL,
        help="Model name for the grader.",
    )

    parser.add_argument(
        "--force-grade",
        action="store_true",
        default=DEFAULT_FORCE_GRADE,
        help="Force regrade even if grade.json already exists.",
    )

    parser.add_argument(
        "--no-dry-run-grade",
        dest="dry_run_grade",
        action="store_false",
        default=DEFAULT_DRY_RUN_GRADE,
        help="Disable grade dry run. Later this will allow posting grades to Canvas.",
    )

    parser.add_argument(
        "--export-grades",
        action="store_true",
        default=DEFAULT_EXPORT_GRADES,
        help="Export local grade.json files to grades_summary.csv.",
    )

    parser.add_argument(
        "--output-csv",
        type=str,
        default=DEFAULT_OUTPUT_CSV,
        help="Optional output CSV path for --export-grades.",
    )

    parser.add_argument(
        "--publish-grades",
        action="store_true",
        default=DEFAULT_PUBLISH_GRADES,
        help="Publish local grades and feedback comments to Canvas.",
    )

    parser.add_argument(
        "--no-dry-run-publish",
        dest="dry_run_publish",
        action="store_false",
        default=DEFAULT_DRY_RUN_PUBLISH,
        help="Actually publish grades to Canvas. Default is dry-run publish.",
    )

    parser.add_argument(
        "--max-post-updates",
        type=int,
        default=DEFAULT_MAX_POST_UPDATES,
        help="Maximum number of Canvas grade updates to publish in this run.",
    )

    parser.add_argument(
        "--publish-message",
        type=str,
        default=DEFAULT_PUBLISH_MESSAGE,
        help="Optional message added before the automatic feedback comment.",
    )

    parser.add_argument(
        "--force-publish",
        action="store_true",
        default=DEFAULT_FORCE_PUBLISH,
        help="Publish again even if the record says it was already published.",
    )
    return parser.parse_args()


def normalize_runtime_args(args: argparse.Namespace) -> argparse.Namespace:
    if args.max_students is not None and args.max_students <= 0:
        args.max_students = None

    if args.prepare_only and not args.prepare_assignment:
        raise ValueError("--prepare-only must be used with --prepare-assignment.")

    return args


# ---------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------


def main() -> None:
    load_dotenv()

    args = parse_args()
    args = normalize_runtime_args(args)

    total_steps = 3
    if args.prepare_assignment:
        total_steps += 1
    if args.prepare_assignment:
        total_steps += 1
    if args.grade:
        total_steps += 1
    if args.publish_grades:
        total_steps += 1
    

    print_header("Canvas Autograder Pipeline")

    canvas = get_canvas_client()

    current_step = 1

    print_step(current_step, total_steps, "Match course")
    course_match = resolve_course(
        canvas=canvas,
        course_id=args.course_id,
        course_keywords=args.course_keywords,
        interactive=not args.non_interactive,
        verbose=True,
    )
    current_step += 1

    print_step(current_step, total_steps, "Match assignment")
    assignment_match = resolve_assignment(
        course=course_match.raw,
        assignment_id=args.assignment_id,
        assignment_keywords=args.assignment_keywords,
        interactive=not args.non_interactive,
        verbose=True,
    )
    current_step += 1 

    if args.clear_assignment_cache:
        print_step(current_step, total_steps, "Clear assignment cache")

        cleared_path = clear_assignment_cache(
            base_dir=args.base_dir,
            course_id=course_match.id,
            assignment_id=assignment_match.id,
        )

        print()
        print("Clear summary:")
        print("-" * 60)
        print(f"  Cleared assignment cache: {cleared_path}")

        print()
        print("=" * 60)
        print("Done.")
        print("=" * 60)
        return

    if args.prepare_assignment:
        print_step(current_step, total_steps, "Prepare assignment materials")
        
        problem_pdf_path = resolve_problem_pdf_path(
            problem_pdf=args.problem_pdf,
            assignment_name=assignment_match.name,
        )
                
        prep_result = prepare_assignment_materials(
            course_id=course_match.id,
            assignment_id=assignment_match.id,
            base_dir=args.base_dir,
            problem_pdf_path=problem_pdf_path,
            model=args.prepare_model,
        )

        print()
        print("Preparation summary:")
        print("-" * 60)
        print(f"  Materials dir:       {prep_result['materials_dir']}")
        print(f"  Problem PDF:         {prep_result['problem_set_pdf']}")
        print(f"  Structure JSON:      {prep_result['assignment_structure']}")
        print(f"  Presence prompt:     {prep_result['presence_prompt']}")
        print(f"  Grading prompt:      {prep_result['grading_prompt']}")

        current_step += 1

        if args.prepare_only:
            print()
            print("=" * 60)
            print("Done.")
            print("=" * 60)
            return

    print_step(current_step, total_steps, "Download submissions")
    download_result = download_assignment_submissions(
        course_match=course_match,
        assignment_match=assignment_match,
        base_dir=args.base_dir,
        canvas_token=os.getenv("CANVAS_TOKEN"),
        force=args.force_download,
        max_students=args.max_students,
    )

    print_download_summary(download_result)
    current_step += 1

    if args.grade:
        print_step(current_step, total_steps, "Grade submissions")

        grade_result = grade_assignment_submissions(
            course_match=course_match,
            assignment_match=assignment_match,
            base_dir=args.base_dir,
            provider=args.provider,
            model=args.model,
            force_grade=args.force_grade,
            max_students=args.max_students,
            dry_run_grade=args.dry_run_grade,
        )

        print_grade_summary(grade_result)
    
    if args.export_grades:
        print_step(current_step, total_steps, "Export grades summary")

        export_result = export_grades_summary(
            base_dir=args.base_dir,
            course_id=course_match.id,
            assignment_id=assignment_match.id,
            output_csv=args.output_csv,
        )

        print_export_summary(export_result)
        current_step += 1
    
    if args.publish_grades:
        print_step(current_step, total_steps, "Publish grades to Canvas")

        publish_result = publish_assignment_grades(
            course_match=course_match,
            assignment_match=assignment_match,
            base_dir=args.base_dir,
            api_url=os.getenv("CANVAS_API_URL"),
            canvas_token=os.getenv("CANVAS_TOKEN"),
            dry_run_publish=args.dry_run_publish,
            max_post_updates=args.max_post_updates,
            publish_message=args.publish_message,
            force_publish=args.force_publish,
        )

        print_publish_summary(publish_result)
        current_step += 1

    print()
    print("=" * 60)
    print("Done.")
    print("=" * 60)


if __name__ == "__main__":
    main()