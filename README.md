# 2181L Lab AutoGrader

Batch grade Canvas Lab, Prelab, and Postlab assignments: award full credit for submissions, skip students who have not submitted, and post no comments. No LLM is required.

Select multiple assignments and course sections. Each assignment produces its own submission counts and list of students who have not submitted.

## Installation

Requires Python 3.11 or later.

```powershell
python -m pip install -r requirements.txt
```

## Authentication

Set the Canvas URL in a local `.env` file:

```dotenv
CANVAS_API_URL=https://uncc.instructure.com
```

Provide your Canvas token using either method:

- Set `CANVAS_TOKEN` in your environment or local `.env` file.
- Store it using Windows Credential Manager through keyring:

```powershell
python -m keyring set canvas-autograder CANVAS_TOKEN
```

Enter the token at the prompt.

Token precedence is: an explicit Python function argument, then the environment (including values loaded from `.env`), then keyring. Existing process environment variables take precedence over `.env`. Empty or whitespace-only tokens are treated as unset. Keyring is accessed only when no higher-priority token is available.

## Find Courses, Assignments, and Sections

```powershell
python completion.py --list-courses
python completion.py --course-id 123 --list-assignments
python completion.py --course-id 123 --list-sections
```

Replace `123` with your Canvas course ID. The assignment list includes each assignment's grading type and maximum points.

## Configure and Run Batch Grading

For initial setup, copy `grading.example.toml` to `grading.toml`. Keep any existing local configuration.

Fill in the Canvas IDs returned by the list commands, not the numbered positions in an interactive selection list:

```toml
course_id = 123
assignment_ids = [456, 457]
section_ids = [789, 790]
mode = "preview"
output_dir = "data/completion"
```

Run:

```powershell
python completion.py --config grading.toml
```

`preview` generates local reports without changing Canvas. After reviewing the results, change `mode` to `"apply"` and run the same command to write grades.

Students in the selected sections are combined and deduplicated. Students outside those sections are not graded. Each assignment is handled according to its own grading type:

- Complete/Incomplete: award Complete.
- Points: award the assignment's maximum points.
- Percent, letter grade, or GPA scale: submit 100%; Canvas applies the assignment's grading scheme.
- Not graded: report submission status without writing grades.

Students who have not submitted are skipped, including any existing grades. Excused students are skipped. Late submissions also receive full credit; the program clears the submission's automatic late penalty without changing the course-wide policy. No comments or feedback are posted.

Reports are saved under `data/completion/` by default. See the [detailed usage guide](COMPLETION_GUIDE.md) for handling of external tools, unknown submission states, excused work, and group assignments.

## Git and Tests

Commit `grading.example.toml`. The local `grading.toml`, `.env`, and `data/` directory are ignored by Git. Do not force-add credentials or student reports.

```powershell
python -m unittest discover -s tests -v
```

Tests use mock data and credentials. They do not access Canvas or the real credential store.

## Project Structure

- `completion.py`: command-line entry point.
- `src/canvas_ops.py`: Canvas connection, token lookup, and course and assignment selection.
- `src/section_ops.py`: section listing and selection.
- `src/completion_ops.py`: submission classification, grading, and reports.
- `src/batch_completion.py`: TOML configuration and batch grading.
- `grading.example.toml`: configuration template suitable for version control.
- `tests/`: mock-based tests.
