from workspace_temp import temporary_directory
import unittest
from pathlib import Path
from types import SimpleNamespace as Obj
from unittest.mock import Mock

from src.batch_completion import load_config, run_batch


class BatchTests(unittest.TestCase):
    def test_config_validation(self):
        with temporary_directory() as folder:
            path = Path(folder) / "config.toml"
            path.write_text('course_id=1\nassignment_ids=[2,2]\nsection_ids=[3]\n', encoding="utf-8")
            config = load_config(path)
            self.assertEqual(config["assignment_ids"], [2])
            self.assertEqual(config["mode"], "preview")
            self.assertEqual(config["output_dir"], path.resolve().parent / "data/completion")
            for text in ['course_id=0', 'course_id=1\nassignment_ids=[2]\nsection_ids=[]',
                         'course_id=1\nassignment_ids=[2]\nsection_ids=[3]\nmode="wrong"']:
                path.write_text(text, encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_config(path)

    def test_batch_union_excludes_other_sections_and_deduplicates(self):
        sections = [Obj(id=i, name=str(i)) for i in [10, 20, 30]]
        enrollments = [Obj(user_id=uid, course_section_id=sid, type="StudentEnrollment", user={"name": str(uid)})
                       for uid, sid in [(1, 10), (1, 20), (2, 20), (3, 30)]]
        tasks = {}
        for aid in [100, 200]:
            subs = [Obj(user_id=i, workflow_state="submitted", edit=Mock(return_value=Obj())) for i in [1, 2, 3]]
            tasks[aid] = Obj(id=aid, name=str(aid), grading_type="pass_fail", points_possible=1,
                             get_submissions=Mock(return_value=subs))
        course = Obj(id=1, get_sections=lambda: iter(sections), get_assignment=lambda i, **kw: tasks[i],
                     get_enrollments=lambda **kw: iter(enrollments))
        canvas = Obj(get_course=lambda i: course)
        with temporary_directory() as folder:
            config = dict(course_id=1, section_ids=[10, 20], assignment_ids=[100, 200], mode="apply", output_dir=Path(folder))
            self.assertEqual(run_batch(canvas, config), 0)
            for task in tasks.values():
                subs = task.get_submissions.return_value
                subs[0].edit.assert_called_once_with(submission={"posted_grade": "complete"})
                subs[1].edit.assert_called_once()
                subs[2].edit.assert_not_called()
            config["section_ids"] = [999]
            with self.assertRaises(ValueError):
                run_batch(canvas, config)
