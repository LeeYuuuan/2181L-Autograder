"""
Base LLM grader interface and dummy grader.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.storage_ops import utc_now_iso


class BaseLLMGrader:
    """Base interface for all graders."""

    provider: str = "base"
    model: str = "base"

    def check_presence(
        self,
        assignment_pdf: Path,
        submission_pdf: Path,
        presence_prompt: str,
        presence_template: dict[str, Any],
    ) -> dict[str, Any]:
        raise NotImplementedError

    def grade_submission(
        self,
        assignment_pdf: Path,
        submission_pdf: Path,
        grading_prompt: str,
        grading_template: dict[str, Any],
        presence_result: dict[str, Any],
    ) -> dict[str, Any]:
        raise NotImplementedError


class DummyGrader(BaseLLMGrader):
    """Dummy grader for testing pipeline only."""

    provider = "dummy"
    model = "dummy-v0"

    def check_presence(
        self,
        assignment_pdf: Path,
        submission_pdf: Path,
        presence_prompt: str,
        presence_template: dict[str, Any],
    ) -> dict[str, Any]:
        result = dict(presence_template)
        result["submission_filename"] = submission_pdf.name

        for item in result["presence"]:
            item["answered"] = True
            item["confidence_0_1"] = 1.0
            item["evidence"] = [f"Dummy presence for {item['subpart_id']}."]

        return result

    def grade_submission(
        self,
        assignment_pdf: Path,
        submission_pdf: Path,
        grading_prompt: str,
        grading_template: dict[str, Any],
        presence_result: dict[str, Any],
    ) -> dict[str, Any]:
        result = dict(grading_template)
        result["submission_filename"] = submission_pdf.name

        for question in result["questions"]:
            scores = []

            for subpart in question["subparts"]:
                subpart["score_0_1"] = 1.0
                subpart["confidence_0_1"] = 1.0
                subpart["evidence"] = [f"Dummy grading for {subpart['subpart_id']}."]
                subpart["feedback"] = "Dummy full credit."
                scores.append(1.0)

            question["question_score_0_1"] = sum(scores) / len(scores)

        total_sum = sum(q["question_score_0_1"] for q in result["questions"])
        result["unweighted_total_sum"] = total_sum
        result["unweighted_total_0_1"] = total_sum / len(result["questions"])
        result["graded_at"] = utc_now_iso()

        return result


def build_grader(provider: str, model: str | None = None) -> BaseLLMGrader:
    """Build a grader."""

    provider = provider.lower().strip()

    if provider == "dummy":
        grader = DummyGrader()
        if model:
            grader.model = model
        return grader

    if provider == "openai":
        from src.llm_grader_openai import OpenAIGrader

        return OpenAIGrader(model=model or "gpt-4.1")

    raise ValueError(f"Unsupported grader provider: {provider}")