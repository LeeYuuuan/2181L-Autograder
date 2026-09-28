from workspace_temp import temporary_directory
import unittest
from pathlib import Path
from types import SimpleNamespace as Obj
from unittest.mock import Mock, patch

from src.completion_ops import full_credit, grade_completion, submission_status
from src.section_ops import select_section


def assignment(**kwargs):
    values = dict(id=9, name="Lab 1", grading_type="points", points_possible=10,
                  submission_types=["online_upload"], published=True)
    values.update(kwargs)
    return Obj(**values)


class CompletionTests(unittest.TestCase):
    def test_section_selection(self):
        sections = [Obj(id=10, name="001"), Obj(id=20, name="002")]
        course = Obj(get_sections=lambda: iter(sections))
        with patch("builtins.input", side_effect=["bad", "3", "2"]):
            self.assertEqual(select_section(course).id, 20)
        self.assertEqual(select_section(course, section_id=10, interactive=False).id, 10)
        with self.assertRaises(ValueError):
            select_section(course, section_id=99)
        with self.assertRaises(ValueError):
            select_section(course, interactive=False)
        self.assertIsNone(select_section(course, all_sections=True, interactive=False))

    def test_section_limits_reports_and_writes(self):
        subs = [Obj(user_id=i, workflow_state="submitted", edit=Mock(return_value=Obj())) for i in [1, 2]]
        enrollments = [Obj(user_id=uid, course_section_id=sid, type="StudentEnrollment", user={"name": str(uid)})
                       for uid, sid in [(1, 10), (1, 10), (2, 20), (3, 10)]]
        course = Obj(id=1, get_enrollments=lambda **kw: iter(enrollments))
        task = assignment(get_submissions=lambda **kw: iter(subs))
        with temporary_directory() as folder:
            report = grade_completion(course, task, folder, apply=True, section=Obj(id=10, name="001"))
        self.assertEqual([r["user_id"] for r in report["students"]], [1, 3])
        self.assertEqual(report["section_id"], 10)
        self.assertEqual(report["counts"], {"submitted": 1, "unknown": 1})
        subs[0].edit.assert_called_once()
        subs[1].edit.assert_not_called()

    def test_grading_types(self):
        for kind, expected in [("points", "10"), ("pass_fail", "complete"),
                               ("percent", "100%"), ("letter_grade", "100%"),
                               ("gpa_scale", "100%"), ("not_graded", None)]:
            with self.subTest(kind=kind):
                self.assertEqual(full_credit(assignment(grading_type=kind)), expected)
        with self.assertRaises(ValueError):
            full_credit(assignment(grading_type="new_type"))
        with self.assertRaises(ValueError):
            full_credit(assignment(points_possible=None))

    def test_submission_evidence(self):
        cases = [({}, "unknown"), ({"workflow_state": "unsubmitted"}, "missing"),
                 ({"workflow_state": "graded", "score": 0}, "missing"),
                 ({"workflow_state": "graded", "submitted_at": "date"}, "submitted"),
                 ({"workflow_state": "submitted"}, "submitted"),
                 ({"workflow_state": "pending_review"}, "submitted"),
                 ({"workflow_state": "unsubmitted", "submitted_at": "date"}, "unknown"),
                 ({"excused": True}, "excused"),
                 ({"assignment_visible": False}, "not_assigned")]
        for fields, expected in cases:
            with self.subTest(fields=fields):
                self.assertEqual(submission_status(assignment(), Obj(**fields)), expected)
        for kind in ["external_tool", "on_paper", "none"]:
            self.assertEqual(submission_status(assignment(submission_types=[kind]),
                                             Obj(workflow_state="graded")), "unknown")

    def run_workflow(self, apply=False, **overrides):
        subs = [Obj(user_id=1, workflow_state="submitted", edit=Mock(return_value=Obj())),
                Obj(user_id=2, workflow_state="unsubmitted", edit=Mock()),
                Obj(user_id=3, workflow_state="graded", score=10, submitted_at="date",
                    grade_matches_current_submission=True, edit=Mock())]
        course = Obj(id=1, get_enrollments=Mock(return_value=[
            Obj(user_id=i, type="StudentEnrollment", user={"name": f"Student {i}"})
            for i in [1, 1, 2, 3, 4]
        ]))
        task = assignment(get_submissions=Mock(return_value=subs), **overrides)
        with temporary_directory() as folder:
            report = grade_completion(course, task, folder, apply=apply)
            self.assertTrue((Path(folder) / "missing_students.csv").exists())
        return report, subs

    def test_preview_never_writes_and_counts_unique_students(self):
        report, subs = self.run_workflow()
        self.assertEqual(report["counts"], {"submitted": 2, "missing": 1, "unknown": 1})
        for sub in subs:
            sub.edit.assert_not_called()

    def test_apply_only_submitted_not_already_full(self):
        report, subs = self.run_workflow(apply=True)
        subs[0].edit.assert_called_once_with(submission={"posted_grade": "10"})
        subs[1].edit.assert_not_called()
        subs[2].edit.assert_not_called()
        self.assertEqual(report["actions"]["graded"], 1)

    def test_visibility_and_ungraded(self):
        report, subs = self.run_workflow(apply=True, assignment_visibility=[2])
        self.assertEqual(report["counts"], {"not_assigned": 3, "missing": 1})
        report, subs = self.run_workflow(apply=True, grading_type="not_graded")
        for sub in subs:
            sub.edit.assert_not_called()

    def test_api_failure_is_reported(self):
        sub = Obj(user_id=1, workflow_state="submitted", edit=Mock(side_effect=RuntimeError("private")))
        course = Obj(id=1, get_enrollments=lambda **kw: [Obj(user_id=1, type="StudentEnrollment", user={"name": "A"})])
        task = assignment(get_submissions=lambda **kw: [sub])
        with temporary_directory() as folder:
            report = grade_completion(course, task, folder, apply=True)
        self.assertEqual(report["actions"], {"error": 1})
        self.assertEqual(report["students"][0]["error"], "RuntimeError")


if __name__ == "__main__":
    unittest.main()
