"""
Assignment preparation utilities.

This module prepares assignment-specific grading materials:
1. Copy official homework PDF into materials/problem_set.pdf.
2. Ask an LLM to extract assignment_structure.json.
3. Generate presence_schema.json and grading_schema.json.
4. Generate prompt_presence.txt and prompt_grading.txt deterministically.

Important design choice:
- LLM extracts assignment structure.
- Code generates prompts from the structure.
- This avoids unstable LLM-written prompts narrowing anchors incorrectly.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from openai import OpenAI
from pydantic import BaseModel, Field

from src.storage_ops import ProjectStore, save_json, utc_now_iso


# ---------------------------------------------------------------------
# Pydantic schemas for assignment structure extraction
# ---------------------------------------------------------------------


class SubpartSpec(BaseModel):
    subpart_id: str = Field(description='Canonical subpart ID, e.g., "Q1(a)".')
    subpart_label: str = Field(description='Subpart label, e.g., "a", "b", or "a" for single-part questions.')
    subpart_text: str = Field(description="Official text of this subpart.")
    task_type: str = Field(description="Task type, e.g., open_ended, drawing, base_conversion, truth_table.")
    anchor_hints: list[str] = Field(description="Specific anchors for matching student work to this exact subpart.")
    max_score_0_1: float = Field(description="Normalized maximum score for this subpart, usually 1.0.")


class QuestionSpec(BaseModel):
    question_id: str = Field(description='Canonical question ID, e.g., "Q1".')
    question_text: str = Field(description="Main question text.")
    task_type: str = Field(description="General category of this question.")
    subparts: list[SubpartSpec]


class AssignmentStructure(BaseModel):
    assignment_key: str = Field(description='Short key, e.g., "HW01".')
    title: str
    course: str | None = None
    term: str | None = None
    questions: list[QuestionSpec]


# ---------------------------------------------------------------------
# Template builders
# ---------------------------------------------------------------------


def build_presence_template(structure: dict[str, Any]) -> dict[str, Any]:
    """Build the expected presence JSON template."""

    presence = []

    for question in structure["questions"]:
        for subpart in question["subparts"]:
            presence.append(
                {
                    "subpart_id": subpart["subpart_id"],
                    "answered": False,
                    "confidence_0_1": 0.2,
                    "evidence": ["not found"],
                }
            )

    return {
        "submission_filename": "",
        "parse_ok": True,
        "parse_issues": [],
        "presence": presence,
    }


def build_grading_template(structure: dict[str, Any]) -> dict[str, Any]:
    """Build the expected grading JSON template."""

    questions = []

    for question in structure["questions"]:
        subparts = []

        for subpart in question["subparts"]:
            subparts.append(
                {
                    "subpart_id": subpart["subpart_id"],
                    "score_0_1": 0,
                    "confidence_0_1": 0,
                    "evidence": [""],
                    "feedback": "",
                }
            )

        questions.append(
            {
                "question_id": question["question_id"],
                "question_score_0_1": 0,
                "subparts": subparts,
            }
        )

    return {
        "student_name": "",
        "student_id": "",
        "submission_filename": "",
        "parse_ok": True,
        "parse_issues": [],
        "questions": questions,
        "unweighted_total_0_1": 0,
        "unweighted_total_sum": 0,
    }


def build_anchor_block(structure: dict[str, Any]) -> str:
    """Build assignment-specific anchor hints for presence detection."""

    lines = []

    for question in structure["questions"]:
        for subpart in question["subparts"]:
            subpart_id = subpart["subpart_id"]
            subpart_text = subpart.get("subpart_text", "")
            anchor_hints = subpart.get("anchor_hints", [])
            task_type = subpart.get("task_type", "other")

            lines.append(f"- {subpart_id}:")
            lines.append(f"  Official task: {subpart_text}")
            lines.append(f"  Task type: {task_type}")
            lines.append(f"  Anchor hints: {', '.join(anchor_hints)}")

    return "\n".join(lines)


def build_presence_prompt(
    structure: dict[str, Any],
    presence_template: dict[str, Any],
) -> str:
    """Build final assignment-specific presence prompt."""

    anchor_block = build_anchor_block(structure)
    template_json = json.dumps(presence_template, indent=2, ensure_ascii=False)

    return f"""
You are an automated autograder assistant.

You will receive TWO PDF files in the same request:
- File A: ASSIGNMENT PDF (official questions).
- File B: STUDENT SUBMISSION PDF (student answers).

TASK (Presence Detection ONLY):
Determine which homework subparts have DISTINCT, DIRECT evidence in the student submission.
Do NOT grade. Do NOT assign scores. Only mark answered=true/false with evidence.

ABSOLUTE OUTPUT RULES:
1) Output MUST be a single valid JSON object and NOTHING else.
2) Do NOT output markdown, code fences, explanations, headings, or any extra text.
3) Use double quotes for all JSON strings.
4) Every number must be a plain JSON number.

FORMAT GATE:
If File B is not a PDF, output exactly:
{{"error":"NOT_PDF","message":"Submission is not PDF format."}}
and stop.

ROBUST MATCHING:
- The student may NOT write question numbers or labels. Do NOT require labels.
- Question labels can help, but they are not required.
- Handwriting, OCR, and notation may be imperfect.
- If the student writes work near a question/subpart label and the work contains distinctive values or concepts from that subpart, treat it as strong evidence.
- If the assignment contains unusual base notation, subscripts, or OCR-sensitive expressions, preserve the meaning flexibly.
  Example: "(47)_127", "(47)127", "(47)_27", and "47 with base/subscript" may all be relevant variants if the official subpart involves such notation.
- Do NOT over-normalize an unusual expression into a different problem. Match the student's visible work to the most likely official subpart.

CRITICAL PRESENCE RULES:
A) DISTINCT ANCHORS REQUIRED:
   A subpart is answered=true ONLY if you can point to specific content that uniquely matches that subpart:
   numbers, bitstrings, keywords, required structure, calculations, diagrams, drawings, tables, or explanations.

B) NO DOUBLE-COUNTING:
   The same piece of work MUST NOT be used to mark multiple different subparts as answered=true.
   If one piece of work could match multiple subparts, assign it to ONLY ONE best-matching subpart unless there is additional distinct evidence.

C) CONSERVATIVE BUT NOT BLIND:
   Be conservative when there is no evidence.
   But if there is clear student work for a subpart, do not mark it false only because the label is missing, OCR is imperfect, or the notation is slightly different.

D) TARGET OBJECT MATCH REQUIRED:
    A subpart is answered=true only if the student's work targets the same function, expression, table, circuit, or object requested by that subpart.
    Do not mark a subpart answered=true merely because the student wrote work of the same general type.
    For example, if a question asks for VHDL for functions from Problem 2, but the student writes VHDL for functions from Problem 5, mark it answered=false or at most flag it as mismatched evidence.

EVIDENCE STRINGS:
- Provide 1–3 short evidence strings per subpart.
- Include a page hint like "submission p1" whenever possible.
- If answered=false, set evidence=["not found"] and confidence_0_1=0.2.

ASSIGNMENT STRUCTURE AND ANCHOR HINTS:
{anchor_block}

OUTPUT JSON SHAPE:
Your output MUST match exactly the following structure, using the exact subpart_ids, keys, and nesting.
Do not add, remove, or rename keys.

{template_json}

Return the JSON object only.
""".strip()


def build_grading_prompt(
    structure: dict[str, Any],
    grading_template: dict[str, Any],
) -> str:
    """Build final assignment-specific grading prompt."""

    anchor_block = build_anchor_block(structure)
    template_json = json.dumps(grading_template, indent=2, ensure_ascii=False)
    num_questions = len(structure["questions"])

    return f"""
You are an automated, VERY GENEROUS autograder.

You will receive:
- File A: ASSIGNMENT PDF (official questions).
- File B: STUDENT SUBMISSION PDF (student work).
- PRESENCE_JSON: the presence-detection output from a previous call.

ABSOLUTE OUTPUT RULES:
1) Output MUST be a single valid JSON object and NOTHING else.
2) Do NOT output markdown, code fences, explanations, headings, or any extra text.
3) Use double quotes for all JSON strings.
4) Every number must be a plain JSON number.
5) You MUST follow the JSON TEMPLATE EXACTLY. Do not add keys. Do not remove keys.

FORMAT GATE:
If File B is not a PDF, output exactly:
{{"error":"NOT_PDF","message":"Submission is not PDF format."}}
and stop.


PRESENCE_JSON CONTROLS ANSWERED VS NOT ANSWERED:
For each subpart:
- If PRESENCE_JSON says answered=false:
  score_0_1 = 0.0
  confidence_0_1 = 0.2
  evidence = ["not found"]
  feedback = "No work found for this subpart."
  Do not grade it. Do not infer. Do not guess.

- If PRESENCE_JSON says answered=true:
  Grade it using the rubric below.
  Evidence MUST include the page hint from PRESENCE_JSON if available.
  Evidence must be 1–3 short strings.
  Feedback must be 1–3 short sentences.

NO DOUBLE-COUNTING:
Do NOT reuse the same piece of work to award points to multiple different subparts.
If overlap exists, keep credit only for the best-matching subpart unless there is distinct evidence.

GRADING PHILOSOPHY:
Be generous. Give credit whenever possible.
Do NOT penalize messy handwriting, informal formatting, missing labels, nonstandard notation, OCR noise, or minor notation issues if the intent is clear.
Do NOT distort student work or invent missing reasoning.

GENERAL SCORING:
- Correct or clearly satisfying answer -> 1.0.
- Correct idea with small omission or tiny slip -> 0.9.
- Real but minor mistake or incomplete work -> 0.8 or 0.7.
- Weak but relevant attempt -> 0.6 or 0.3.
- No work -> 0.0.

OBJECTIVE / CALCULATION QUESTIONS:
- Correct final answer -> 1.0.
- Wrong final answer with clearly relevant reasoning/process -> substantial partial credit.
- Wrong final answer with weak or mostly irrelevant process -> small partial credit.
- Wrong final answer with no process -> 0.0 or very low score.

OPEN-ENDED / SUBJECTIVE QUESTIONS:
- If present and basically reasonable -> 1.0.
- If present but weak or mostly unreasonable -> partial credit.
- If absent -> 0.0.
- Do not nitpick subjective answers. If reasonable, give full credit.

PREFERRED SCORES:
Use these scores when possible:
1.0, 0.9, 0.8, 0.7, 0.6, 0.3, 0.0.

ASSIGNMENT STRUCTURE:
{anchor_block}

SCORING CONSISTENCY:
- Each question_score_0_1 MUST equal the mean of its subpart scores.
- unweighted_total_sum MUST equal the sum of the {num_questions} question_score_0_1 values.
- unweighted_total_0_1 MUST equal unweighted_total_sum / {num_questions}.

IMPORTANT: PRESENCE_JSON only says that some work was found. It does NOT guarantee correctness.
Even when answered=true, you must check whether the work answers the exact requested object.
If the student answers a different function, different expression, different table, or different problem, assign low or zero credit depending on relevance.
Do not give full credit for correct-looking work that belongs to the wrong question.

OUTPUT JSON TEMPLATE:
{template_json}

Return the JSON object only.
""".strip()


# ---------------------------------------------------------------------
# LLM extraction
# ---------------------------------------------------------------------


STRUCTURE_EXTRACTION_PROMPT = """
You are preparing an automated grading configuration for a homework assignment.

You will receive the official assignment PDF as a file input.

Your task:
Extract the complete assignment structure into the required structured output format.

Requirements:
1. Identify every numbered question.
2. Identify every explicit subpart such as (a), (b), (c), etc.
3. If a question has no explicit subparts, create exactly one subpart with label "a" and subpart_id like "Q2(a)".
4. Preserve the official meaning of every question and subpart.
5. Do not solve the homework.
6. Do not generate grading feedback.
7. Do not omit any subpart.
8. Use canonical IDs:
   - Q1, Q2, Q3, ...
   - Q1(a), Q1(b), Q1(c), ...
9. For each subpart, generate useful anchor_hints for later presence detection.
   Anchor hints should include distinctive numbers, bitstrings, keywords, tables, drawings, diagrams, base notation, or required concepts.
10. For each subpart, assign a task_type such as:
   - open_ended
   - drawing
   - hierarchy
   - base_conversion
   - decimal_binary_conversion
   - binary_decimal_conversion
   - twos_complement
   - bit_extension
   - truth_table
   - logic_gate
   - range_or_representability
   - other

Important:
- Preserve unusual notation carefully.
- If the PDF contains odd-looking base/subscript notation, keep it in the subpart_text and add tolerant anchor variants.
- Subpart IDs must be stable and complete.
"""


def prepare_assignment_materials(
    course_id: int,
    assignment_id: int,
    base_dir: str | Path | None,
    problem_pdf_path: str | Path,
    model: str = "gpt-4.1",
) -> dict[str, Any]:
    """
    Prepare assignment-specific materials.

    Saves:
    - materials/problem_set.pdf
    - materials/assignment_structure.json
    - materials/presence_schema.json
    - materials/grading_schema.json
    - materials/prompt_presence.txt
    - materials/prompt_grading.txt
    """

    problem_pdf_path = Path(problem_pdf_path)

    if not problem_pdf_path.exists():
        raise FileNotFoundError(f"Problem PDF not found: {problem_pdf_path}")

    project_store = ProjectStore(base_dir)
    assignment_store = project_store.course(course_id).assignment(assignment_id)

    target_problem_pdf = assignment_store.materials_dir / "problem_set.pdf"
    shutil.copy2(problem_pdf_path, target_problem_pdf)

    client = OpenAI()

    uploaded_file = client.files.create(
        file=open(target_problem_pdf, "rb"),
        purpose="user_data",
    )

    response = client.responses.parse(
        model=model,
        input=[
            {
                "role": "system",
                "content": STRUCTURE_EXTRACTION_PROMPT,
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": "Extract the complete assignment structure from this official assignment PDF.",
                    },
                    {
                        "type": "input_file",
                        "file_id": uploaded_file.id,
                    },
                ],
            },
        ],
        text_format=AssignmentStructure,
    )

    structure = response.output_parsed.model_dump()
    presence_template = build_presence_template(structure)
    grading_template = build_grading_template(structure)

    presence_prompt = build_presence_prompt(structure, presence_template)
    grading_prompt = build_grading_prompt(structure, grading_template)

    save_json(assignment_store.materials_dir / "assignment_structure.json", structure)
    save_json(assignment_store.materials_dir / "presence_schema.json", presence_template)
    save_json(assignment_store.materials_dir / "grading_schema.json", grading_template)

    (assignment_store.materials_dir / "prompt_presence.txt").write_text(
        presence_prompt,
        encoding="utf-8",
    )

    (assignment_store.materials_dir / "prompt_grading.txt").write_text(
        grading_prompt,
        encoding="utf-8",
    )

    config = assignment_store.ensure_assignment_config()
    config["materials"] = {
        "problem_set_pdf": "materials/problem_set.pdf",
        "assignment_structure": "materials/assignment_structure.json",
        "presence_schema": "materials/presence_schema.json",
        "grading_schema": "materials/grading_schema.json",
        "presence_prompt": "materials/prompt_presence.txt",
        "grading_prompt": "materials/prompt_grading.txt",
    }
    config["updated_at"] = utc_now_iso()
    save_json(assignment_store.assignment_config_path, config)

    return {
        "course_id": course_id,
        "assignment_id": assignment_id,
        "assignment_dir": str(assignment_store.assignment_dir),
        "materials_dir": str(assignment_store.materials_dir),
        "problem_set_pdf": str(target_problem_pdf),
        "assignment_structure": str(assignment_store.materials_dir / "assignment_structure.json"),
        "presence_prompt": str(assignment_store.materials_dir / "prompt_presence.txt"),
        "grading_prompt": str(assignment_store.materials_dir / "prompt_grading.txt"),
    }