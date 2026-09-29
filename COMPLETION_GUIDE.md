# Lab / Prelab / Postlab Completion Grading

Use `completion.py` to award full credit based on submission status. No LLM, OpenAI API key, PDF processing, or student-file downloads are required.

## Setup

Requires Python 3.11 or later. TOML parsing uses the Python standard library.

```powershell
python -m pip install -r requirements.txt
```

Set the Canvas URL and, optionally, the token in a local `.env` file. Do not commit this file:

```dotenv
CANVAS_API_URL=https://uncc.instructure.com
CANVAS_TOKEN=your_canvas_token
```

Alternatively, omit the token from `.env` and store it through keyring:

```powershell
python -m keyring set canvas-autograder CANVAS_TOKEN
```

Enter the token at the prompt. An environment token, including one loaded from `.env`, takes precedence over keyring. Existing process environment variables take precedence over `.env`. Keyring is accessed only if no nonblank token is available. The Canvas URL must still be configured. Explicit token arguments passed by Python callers take precedence over both sources.

## Batch Grading with a Configuration File

First, find the Canvas IDs:

```powershell
python completion.py --list-courses
python completion.py --course-id 123 --list-assignments
python completion.py --course-id 123 --list-sections
```

For initial setup, copy `grading.example.toml` to `grading.toml`. Do not overwrite an existing local configuration. Fill in **Canvas IDs, not interactive list positions**:

```toml
course_id = 123
assignment_ids = [456, 457, 458]
section_ids = [789, 790]
mode = "preview"
output_dir = "data/completion"
```

The local configuration is ignored by Git; commit only the example template. Replace the template's zero and empty lists before running.

```powershell
python completion.py --config grading.toml
```

`preview` generates reports without modifying Canvas. After reviewing the results, change `mode` to `"apply"` and run the same command to write grades. Do not combine `--config` with command-line course, assignment, section, output directory, list, or `--apply` options.

The selected sections form a union of students, deduplicated by Canvas user ID. Each assignment has separate counts and a separate missing-submission list. Counts across assignments are not a count of unique students.

Batch reports are stored under:

```text
data/completion/course_<ID>/sections_<ID>_<ID>/assignment_<ID>/
```

A `batch_summary.json` file summarizes the assignments. Relative output paths are resolved against the configuration file's directory.

## Single-Assignment Commands

Replace the example IDs with actual Canvas IDs.

```powershell
# List courses.
python completion.py --list-courses

# List assignments, grading types, and maximum points.
python completion.py --course-id 123 --list-assignments

# List section names and IDs.
python completion.py --course-id 123 --list-sections

# Preview counts and reports; select a section interactively.
python completion.py --course-id 123 --assignment-id 456

# Award full credit to submitted work in one section.
python completion.py --course-id 123 --assignment-id 456 --section-id 789 --apply

# Match by keywords; select from multiple matches when prompted.
python completion.py --course-keywords "ECGR 2181" --assignment-keywords "Prelab 1"
```

Without `--section-id`, the program lists sections and asks for a numbered selection before grading or previewing. Enter `q` to cancel. Selection is required even when only one section is available. With `--section-id`, the specified section is used directly.

Counts, missing-submission lists, and grade updates include only active students in the selected section. Multiple enrollments for one student count once.

Whole-course operations require explicit `--all-sections`. In single-assignment mode, `--non-interactive` requires either `--section-id` or `--all-sections`. Ambiguous keyword matches cause an error instead of an automatic selection:

```powershell
python completion.py --course-id 123 --assignment-id 456 --section-id 789 --non-interactive
```

## Grading Rules

| Canvas grading type | Value submitted |
|---|---|
| Complete / Incomplete (`pass_fail`) | `complete` |
| Points | The assignment's `points_possible` |
| Percent | `100%` |
| Letter grade / GPA scale | `100%`, converted by Canvas using the assignment's grading scheme |
| Not graded | Report only; no grade update |

- Submission status comes from Canvas; content quality is not evaluated. Records marked `submitted`, `pending_review`, or `graded` with a submission timestamp count as submitted.
- Existing lower grades for submitted work are changed to full credit. Full-credit grades matching the current submission are skipped. Existing grades for unsubmitted work are preserved; no zero or Incomplete is written.
- Only active `StudentEnrollment` records visible to the current account are included. Test Student and inactive enrollments are excluded. Section-restricted permissions may limit coverage.
- Excused students (`excused`) and students not assigned the work (`not_assigned`) are reported separately and skipped.
- External-tool work, paper submissions, or missing API records without clear submission evidence are classified as `unknown`. Review these in Canvas; they are not counted as missing submissions.
- Group assignments use individual submission records. Automatic grading supports groups configured for individual grades. Shared group grades support preview only, avoiding grade propagation to other members.
- Late submissions receive full credit. When applicable, the submission's late-policy status is set to `none`, removing its automatic deduction and manual late/missing status without changing the course policy. If Canvas still returns a deduction, the action is recorded as `graded_with_late_penalty` for review.
- Unpublished assignments and moderated grading do not support automatic grade writes. Existing Canvas grade posting and visibility policies still apply.
- No comments or feedback are posted. Existing comments are not modified.

## Reports

For single-assignment mode, the default directory is:

```text
data/completion/course_<ID>/assignment_<ID>/section_<ID>/
```

Whole-course reports use `all_sections/` instead of `section_<ID>/`. Reports for different section scopes are stored separately. Use `--output-dir` to choose a directory in single-assignment mode; use `output_dir` in the TOML file for batch mode. JSON reports include section names and IDs.

- `completion_report.json`: counts, grading actions, and individual results.
- `completion_report.csv`: student names, Canvas IDs, submission states, and grading results.
- `missing_students.csv`: names and Canvas IDs of students classified as missing a submission.

The terminal also prints submission counts and missing students. Each run replaces reports at the same output location; choose a different output directory to preserve history. Individual grade-write failures are recorded as `error`; other students continue to be processed, and the command returns a nonzero exit code. Each new run reads Canvas again.

## Tests

```powershell
python -m unittest discover -s tests -v
```

Tests use mock data and credentials, without contacting Canvas or accessing the real credential store.

API references: [Canvas Submissions](https://developerdocs.instructure.com/services/canvas/resources/submissions) and [Canvas Assignments](https://developerdocs.instructure.com/services/canvas/resources/assignments).
