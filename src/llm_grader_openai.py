"""
OpenAI grader implementation.

This file handles:
1. File upload.
2. Presence detection call.
3. Grading call.
4. JSON parsing through structured output.
5. Local canonicalization after model output.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from openai import OpenAI
from pydantic import BaseModel

from src.llm_grader_base import BaseLLMGrader


class PresenceItem(BaseModel):
    subpart_id: str
    answered: bool
    confidence_0_1: float
    evidence: list[str]


class PresenceOutput(BaseModel):
    submission_filename: str
    parse_ok: bool
    parse_issues: list[str]
    presence: list[PresenceItem]


class GradeSubpartItem(BaseModel):
    subpart_id: str
    score_0_1: float
    confidence_0_1: float
    evidence: list[str]
    feedback: str


class GradeQuestionItem(BaseModel):
    question_id: str
    question_score_0_1: float
    subparts: list[GradeSubpartItem]


class GradeOutput(BaseModel):
    student_name: str
    student_id: str
    submission_filename: str
    parse_ok: bool
    parse_issues: list[str]
    questions: list[GradeQuestionItem]
    unweighted_total_0_1: float
    unweighted_total_sum: float


def canonicalize_presence(
    raw_presence: dict[str, Any],
    presence_template: dict[str, Any],
    submission_filename: str,
) -> dict[str, Any]:
    """Force presence output to match template subpart IDs."""

    raw_items = {
        item.get("subpart_id"): item
        for item in raw_presence.get("presence", [])
    }

    result = {
        "submission_filename": raw_presence.get("submission_filename") or submission_filename,
        "parse_ok": raw_presence.get("parse_ok", True),
        "parse_issues": raw_presence.get("parse_issues", []),
        "presence": [],
    }

    for template_item in presence_template["presence"]:
        subpart_id = template_item["subpart_id"]
        raw_item = raw_items.get(subpart_id)

        if raw_item is None:
            result["presence"].append(
                {
                    "subpart_id": subpart_id,
                    "answered": False,
                    "confidence_0_1": 0.2,
                    "evidence": ["not found"],
                }
            )
            continue

        answered = bool(raw_item.get("answered", False))

        result["presence"].append(
            {
                "subpart_id": subpart_id,
                "answered": answered,
                "confidence_0_1": float(raw_item.get("confidence_0_1", 1.0 if answered else 0.2)),
                "evidence": raw_item.get("evidence") or (["not found"] if not answered else ["evidence found"]),
            }
        )

    return result


def presence_map(presence_result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Convert presence list to dictionary."""

    return {
        item["subpart_id"]: item
        for item in presence_result.get("presence", [])
    }


def canonicalize_grade(
    raw_grade: dict[str, Any],
    grading_template: dict[str, Any],
    presence_result: dict[str, Any],
    submission_filename: str,
) -> dict[str, Any]:
    """Force grading output to match template and recompute totals."""

    pmap = presence_map(presence_result)

    raw_questions = {
        q.get("question_id"): q
        for q in raw_grade.get("questions", [])
    }

    result = {
        "student_name": raw_grade.get("student_name", ""),
        "student_id": raw_grade.get("student_id", ""),
        "submission_filename": raw_grade.get("submission_filename") or submission_filename,
        "parse_ok": raw_grade.get("parse_ok", True),
        "parse_issues": raw_grade.get("parse_issues", []),
        "questions": [],
        "unweighted_total_0_1": 0,
        "unweighted_total_sum": 0,
    }

    for template_question in grading_template["questions"]:
        question_id = template_question["question_id"]
        raw_question = raw_questions.get(question_id, {})
        raw_subparts = {
            sp.get("subpart_id"): sp
            for sp in raw_question.get("subparts", [])
        }

        subparts = []
        subpart_scores = []

        for template_sp in template_question["subparts"]:
            subpart_id = template_sp["subpart_id"]
            pitem = pmap.get(subpart_id, {})
            answered = bool(pitem.get("answered", False))

            if not answered:
                sp = {
                    "subpart_id": subpart_id,
                    "score_0_1": 0.0,
                    "confidence_0_1": 0.2,
                    "evidence": ["not found"],
                    "feedback": "No work found for this subpart.",
                }
            else:
                raw_sp = raw_subparts.get(subpart_id, {})
                score = float(raw_sp.get("score_0_1", 0.0))
                score = max(0.0, min(1.0, score))

                sp = {
                    "subpart_id": subpart_id,
                    "score_0_1": score,
                    "confidence_0_1": float(raw_sp.get("confidence_0_1", pitem.get("confidence_0_1", 0.8))),
                    "evidence": raw_sp.get("evidence") or pitem.get("evidence") or ["evidence found"],
                    "feedback": raw_sp.get("feedback") or "Relevant work found and graded.",
                }

            subparts.append(sp)
            subpart_scores.append(sp["score_0_1"])

        question_score = sum(subpart_scores) / len(subpart_scores) if subpart_scores else 0.0

        result["questions"].append(
            {
                "question_id": question_id,
                "question_score_0_1": question_score,
                "subparts": subparts,
            }
        )

    total_sum = sum(q["question_score_0_1"] for q in result["questions"])
    result["unweighted_total_sum"] = total_sum
    result["unweighted_total_0_1"] = total_sum / len(result["questions"]) if result["questions"] else 0.0

    return result


class OpenAIGrader(BaseLLMGrader):
    """OpenAI-based grader."""

    provider = "openai"

    def __init__(self, model: str = "gpt-4.1"):
        self.model = model
        self.client = OpenAI()
        self._file_cache: dict[str, str] = {}

    def upload_file_once(self, path: Path) -> str:
        """Upload a file once and cache the file ID."""

        key = str(path.resolve())

        if key in self._file_cache:
            return self._file_cache[key]

        uploaded = self.client.files.create(
            file=open(path, "rb"),
            purpose="user_data",
        )

        self._file_cache[key] = uploaded.id
        return uploaded.id

    def check_presence(
        self,
        assignment_pdf: Path,
        submission_pdf: Path,
        presence_prompt: str,
        presence_template: dict[str, Any],
    ) -> dict[str, Any]:
        """Run presence detection."""

        assignment_file_id = self.upload_file_once(assignment_pdf)
        submission_file_id = self.upload_file_once(submission_pdf)

        response = self.client.responses.parse(
            model=self.model,
            input=[
                {
                    "role": "system",
                    "content": presence_prompt,
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "File A is the official assignment PDF. "
                                "File B is the student submission PDF. "
                                "Perform presence detection only."
                            ),
                        },
                        {
                            "type": "input_file",
                            "file_id": assignment_file_id,
                        },
                        {
                            "type": "input_file",
                            "file_id": submission_file_id,
                        },
                    ],
                },
            ],
            text_format=PresenceOutput,
        )

        raw_presence = response.output_parsed.model_dump()

        return canonicalize_presence(
            raw_presence=raw_presence,
            presence_template=presence_template,
            submission_filename=submission_pdf.name,
        )

    def grade_submission(
        self,
        assignment_pdf: Path,
        submission_pdf: Path,
        grading_prompt: str,
        grading_template: dict[str, Any],
        presence_result: dict[str, Any],
    ) -> dict[str, Any]:
        """Run grading."""

        assignment_file_id = self.upload_file_once(assignment_pdf)
        submission_file_id = self.upload_file_once(submission_pdf)

        response = self.client.responses.parse(
            model=self.model,
            input=[
                {
                    "role": "system",
                    "content": grading_prompt,
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "File A is the official assignment PDF. "
                                "File B is the student submission PDF. "
                                "Use the following PRESENCE_JSON as the only source of truth for answered vs not answered:\n\n"
                                + json.dumps(presence_result, indent=2, ensure_ascii=False)
                            ),
                        },
                        {
                            "type": "input_file",
                            "file_id": assignment_file_id,
                        },
                        {
                            "type": "input_file",
                            "file_id": submission_file_id,
                        },
                    ],
                },
            ],
            text_format=GradeOutput,
        )

        raw_grade = response.output_parsed.model_dump()

        return canonicalize_grade(
            raw_grade=raw_grade,
            grading_template=grading_template,
            presence_result=presence_result,
            submission_filename=submission_pdf.name,
        )