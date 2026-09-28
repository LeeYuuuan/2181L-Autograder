"""
Canvas operation utilities.

Current scope:
1. Connect to Canvas.
2. Match courses by ID or keywords.
3. Match assignments by ID or keywords.

Course keyword matching:
- First search course.name.
- If course.name has matches, return those matches.
- Otherwise search course.course_code.
- In each field, all keyword tokens must appear in that field.

Assignment keyword matching:
- Search assignment.name.
- All keyword tokens must appear in assignment.name.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Optional

from canvasapi import Canvas


@dataclass
class MatchResult:
    """A lightweight wrapper for a matched Canvas object."""

    id: int
    name: str
    raw: Any
    extra: dict[str, Any] = field(default_factory=dict)


def get_canvas_client(
    api_url: Optional[str] = None,
    api_token: Optional[str] = None,
) -> Canvas:
    """Create a Canvas client."""

    api_url = api_url or os.getenv("CANVAS_API_URL")
    api_token = (api_token or "").strip() or (os.getenv("CANVAS_TOKEN") or "").strip()

    if not api_url:
        raise ValueError("Missing Canvas API URL. Set CANVAS_API_URL or pass api_url.")

    if not api_token:
        try:
            import keyring
            api_token = (keyring.get_password("canvas-autograder", "CANVAS_TOKEN") or "").strip()
        except Exception:
            raise ValueError(
                "Cannot access credential storage. Set CANVAS_TOKEN in the environment/.env, "
                "or install/configure keyring."
            ) from None
    if not api_token:
        raise ValueError(
            "Missing Canvas token. Set CANVAS_TOKEN in the environment/.env or run: "
            "python -m keyring set canvas-autograder CANVAS_TOKEN"
        )

    api_url = str(api_url).rstrip("/")

    return Canvas(api_url, api_token)


def normalize_text(text: str) -> str:
    """Normalize text for token-based matching."""

    text = str(text).lower()

    for ch in ["_", "-", ":", "/", "\\", ".", ",", "(", ")", "[", "]"]:
        text = text.replace(ch, " ")

    return " ".join(text.split())


def all_keywords_match(search_text: str, keywords: str) -> bool:
    """Return True only if all keyword tokens appear in one normalized search text."""

    normalized_search_text = normalize_text(search_text)
    normalized_keywords = normalize_text(keywords)

    tokens = normalized_keywords.split()

    if not tokens:
        return False

    return all(token in normalized_search_text for token in tokens)


def deduplicate_matches(matches: list[MatchResult]) -> list[MatchResult]:
    """Remove duplicated matches by Canvas object ID."""

    seen_ids: set[int] = set()
    unique_matches: list[MatchResult] = []

    for item in matches:
        if item.id in seen_ids:
            continue

        seen_ids.add(item.id)
        unique_matches.append(item)

    return unique_matches


def course_to_match_result(course: Any) -> MatchResult:
    """Convert a Canvas course object to MatchResult."""

    course_id = int(getattr(course, "id"))
    name = str(getattr(course, "name", "") or "")
    course_code = str(getattr(course, "course_code", "") or "")

    return MatchResult(
        id=course_id,
        name=name,
        raw=course,
        extra={
            "course_code": course_code,
            "workflow_state": getattr(course, "workflow_state", ""),
        },
    )


def print_course_match(course_match: MatchResult) -> None:
    """Print one matched course."""

    print()
    print("Matched course:")
    print(f"  Canvas ID:    {course_match.id}")
    print(f"  Name:         {course_match.name}")
    print(f"  Course Code:  {course_match.extra.get('course_code', '')}")
    print(f"  State:        {course_match.extra.get('workflow_state', '')}")
    print()


def print_course_candidates(candidates: list[MatchResult]) -> None:
    """Print multiple course candidates."""

    print()
    print("Multiple courses matched:")
    print("-" * 30)

    for idx, item in enumerate(candidates, start=1):
        print(f"[{idx}] Canvas ID:   {item.id}")
        print(f"    Name:        {item.name}")
        print(f"    Course Code: {item.extra.get('course_code', '')}")
        print(f"    State:       {item.extra.get('workflow_state', '')}")
        print()


def get_course_by_id(canvas: Canvas, course_id: int) -> MatchResult:
    """Get one Canvas course by exact Canvas course ID."""

    try:
        course = canvas.get_course(course_id)
    except Exception as e:
        raise ValueError(
            f"Failed to get course by ID={course_id}. "
            "Please check whether the course ID is correct and accessible."
        ) from e

    return course_to_match_result(course)


def find_courses_by_keywords(canvas: Canvas, course_keywords: str) -> list[MatchResult]:
    """
    Find courses by keywords.

    Matching order:
    1. Try course.name first.
    2. If course.name has matches, return name matches.
    3. Otherwise, try course.course_code.
    """

    courses = list(canvas.get_courses())

    name_results: list[MatchResult] = []

    for course in courses:
        name = getattr(course, "name", "") or ""

        if all_keywords_match(name, course_keywords):
            name_results.append(course_to_match_result(course))

    name_results = deduplicate_matches(name_results)

    if name_results:
        return name_results

    code_results: list[MatchResult] = []

    for course in courses:
        course_code = getattr(course, "course_code", "") or ""

        if all_keywords_match(course_code, course_keywords):
            code_results.append(course_to_match_result(course))

    return deduplicate_matches(code_results)


def choose_course_interactively(candidates: list[MatchResult]) -> MatchResult:
    """Ask user to choose one course from multiple course matches."""

    if not candidates:
        raise ValueError("No course candidates available.")

    if len(candidates) == 1:
        return candidates[0]

    print_course_candidates(candidates)

    while True:
        choice = input(f"Select one course [1-{len(candidates)}]: ").strip()

        if not choice.isdigit():
            print("Please enter a number.")
            continue

        index = int(choice)

        if 1 <= index <= len(candidates):
            return candidates[index - 1]

        print(f"Invalid choice. Please enter a number from 1 to {len(candidates)}.")


def resolve_course(
    canvas: Canvas,
    course_id: Optional[int] = None,
    course_keywords: Optional[str] = None,
    interactive: bool = True,
    verbose: bool = True,
) -> MatchResult:
    """Resolve a Canvas course."""

    if course_id is not None:
        matched_course = get_course_by_id(canvas, course_id)

        if verbose:
            print_course_match(matched_course)

        return matched_course

    if not course_keywords:
        raise ValueError("Please provide either course_id or course_keywords.")

    candidates = find_courses_by_keywords(canvas, course_keywords)

    if not candidates:
        raise ValueError(f"No course matched keywords: {course_keywords}")

    if len(candidates) == 1:
        matched_course = candidates[0]
    else:
        if not interactive:
            raise ValueError(
                f"Multiple courses matched keywords '{course_keywords}'. "
                "Please use course_id or enable interactive selection."
            )

        matched_course = choose_course_interactively(candidates)

    if verbose:
        print_course_match(matched_course)

    return matched_course


def assignment_to_match_result(assignment: Any) -> MatchResult:
    """Convert a Canvas assignment object to MatchResult."""

    assignment_id = int(getattr(assignment, "id"))
    name = str(getattr(assignment, "name", "") or "")

    return MatchResult(
        id=assignment_id,
        name=name,
        raw=assignment,
        extra={
            "due_at": getattr(assignment, "due_at", None),
            "unlock_at": getattr(assignment, "unlock_at", None),
            "lock_at": getattr(assignment, "lock_at", None),
            "points_possible": getattr(assignment, "points_possible", None),
            "workflow_state": getattr(assignment, "workflow_state", ""),
        },
    )


def print_assignment_match(assignment_match: MatchResult) -> None:
    """Print one matched assignment."""

    print()
    print("Matched assignment:")
    print(f"  Canvas ID:        {assignment_match.id}")
    print(f"  Name:             {assignment_match.name}")
    print(f"  Points Possible:  {assignment_match.extra.get('points_possible', '')}")
    print(f"  Due At:           {assignment_match.extra.get('due_at', '')}")
    print(f"  State:            {assignment_match.extra.get('workflow_state', '')}")
    print()


def print_assignment_candidates(candidates: list[MatchResult]) -> None:
    """Print multiple assignment candidates."""

    print()
    print("Multiple assignments matched:")
    print("-" * 34)

    for idx, item in enumerate(candidates, start=1):
        print(f"[{idx}] Canvas ID:        {item.id}")
        print(f"    Name:             {item.name}")
        print(f"    Points Possible:  {item.extra.get('points_possible', '')}")
        print(f"    Due At:           {item.extra.get('due_at', '')}")
        print(f"    State:            {item.extra.get('workflow_state', '')}")
        print()


def get_assignment_by_id(course: Any, assignment_id: int) -> MatchResult:
    """Get one Canvas assignment by exact Canvas assignment ID."""

    try:
        assignment = course.get_assignment(assignment_id)
    except Exception as e:
        raise ValueError(
            f"Failed to get assignment by ID={assignment_id}. "
            "Please check whether the assignment ID is correct and accessible."
        ) from e

    return assignment_to_match_result(assignment)


def find_assignments_by_keywords(
    course: Any,
    assignment_keywords: str,
) -> list[MatchResult]:
    """Find assignments by matching all keyword tokens against assignment.name."""

    results: list[MatchResult] = []

    for assignment in course.get_assignments():
        name = getattr(assignment, "name", "") or ""

        if all_keywords_match(name, assignment_keywords):
            results.append(assignment_to_match_result(assignment))

    return deduplicate_matches(results)


def choose_assignment_interactively(candidates: list[MatchResult]) -> MatchResult:
    """Ask user to choose one assignment from multiple assignment matches."""

    if not candidates:
        raise ValueError("No assignment candidates available.")

    if len(candidates) == 1:
        return candidates[0]

    print_assignment_candidates(candidates)

    while True:
        choice = input(f"Select one assignment [1-{len(candidates)}]: ").strip()

        if not choice.isdigit():
            print("Please enter a number.")
            continue

        index = int(choice)

        if 1 <= index <= len(candidates):
            return candidates[index - 1]

        print(f"Invalid choice. Please enter a number from 1 to {len(candidates)}.")


def resolve_assignment(
    course: Any,
    assignment_id: Optional[int] = None,
    assignment_keywords: Optional[str] = None,
    interactive: bool = True,
    verbose: bool = True,
) -> MatchResult:
    """Resolve a Canvas assignment."""

    if assignment_id is not None:
        matched_assignment = get_assignment_by_id(course, assignment_id)

        if verbose:
            print_assignment_match(matched_assignment)

        return matched_assignment

    if not assignment_keywords:
        raise ValueError("Please provide either assignment_id or assignment_keywords.")

    candidates = find_assignments_by_keywords(course, assignment_keywords)

    if not candidates:
        raise ValueError(f"No assignment matched keywords: {assignment_keywords}")

    if len(candidates) == 1:
        matched_assignment = candidates[0]
    else:
        if not interactive:
            raise ValueError(
                f"Multiple assignments matched keywords '{assignment_keywords}'. "
                "Please use assignment_id or enable interactive selection."
            )

        matched_assignment = choose_assignment_interactively(candidates)

    if verbose:
        print_assignment_match(matched_assignment)

    return matched_assignment
