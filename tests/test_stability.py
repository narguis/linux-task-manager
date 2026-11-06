import unittest

from test_grouping import process
from linux_task_manager.stability import ProcessListStabilizer


class ProcessListStabilizerTests(unittest.TestCase):
    def test_requires_two_samples_for_new_processes(self) -> None:
        stabilizer = ProcessListStabilizer(appearances=2, disappearance_grace=2)
        baseline = process(10, "baseline")
        newcomer = process(20, "new")
        self.assertEqual(stabilizer.update([baseline]), [baseline])
        self.assertNotIn(newcomer, stabilizer.update([baseline, newcomer]))
        self.assertIn(newcomer, stabilizer.update([baseline, newcomer]))

    def test_bridges_brief_read_misses_then_removes_process(self) -> None:
        stabilizer = ProcessListStabilizer(appearances=2, disappearance_grace=2)
        item = process(10, "steady")
        stabilizer.update([item])
        self.assertIn(item, stabilizer.update([]))
        self.assertIn(item, stabilizer.update([]))
        self.assertNotIn(item, stabilizer.update([]))


if __name__ == "__main__":
    unittest.main()
