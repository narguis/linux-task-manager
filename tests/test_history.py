import unittest

from linux_task_manager.history import ActivityHistory, HistorySample


class ActivityHistoryTests(unittest.TestCase):
    def test_accumulates_cpu_memory_and_io_deltas(self) -> None:
        history = ActivityHistory()
        first = HistorySample("app", "App", "app", 50, 100, (((1, 10), 1000),))
        second = HistorySample("app", "App", "app", 50, 250, (((1, 10), 1600),))
        history.update([first], 100.0)
        record = history.update([second], 102.0)[0]
        self.assertAlmostEqual(record.cpu_seconds, 1.0)
        self.assertAlmostEqual(record.average_cpu, 50.0)
        self.assertEqual(record.peak_memory, 250)
        self.assertEqual(record.disk_bytes, 600)

    def test_clear_removes_records(self) -> None:
        history = ActivityHistory()
        history.update([HistorySample("a", "A", "a", 0, 0, ())], 1)
        history.clear()
        self.assertEqual(history.records(), [])


if __name__ == "__main__":
    unittest.main()
