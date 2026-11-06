import unittest

from linux_task_manager.monitor import calculate_cpu_percent, parse_meminfo, parse_proc_stat_line


class MonitorParserTests(unittest.TestCase):
    def test_parses_process_names_with_spaces_and_parentheses(self) -> None:
        line = (
            "123 (Web Content (GPU)) R 10 20 30 0 0 0 1 2 3 4 "
            "100 50 0 0 20 5 8 0 9999 100000 42"
        )
        result = parse_proc_stat_line(line)
        self.assertEqual(result["pid"], 123)
        self.assertEqual(result["name"], "Web Content (GPU)")
        self.assertEqual(result["ppid"], 10)
        self.assertEqual(result["session_id"], 30)
        self.assertEqual(result["utime"], 100)
        self.assertEqual(result["stime"], 50)
        self.assertEqual(result["nice"], 5)
        self.assertEqual(result["threads"], 8)
        self.assertEqual(result["start_ticks"], 9999)
        self.assertEqual(result["rss_pages"], 42)

    def test_rejects_incomplete_process_stat(self) -> None:
        with self.assertRaises(ValueError):
            parse_proc_stat_line("1 (bad) S 0")

    def test_parses_memory_values_as_bytes(self) -> None:
        values = parse_meminfo("MemTotal: 1000 kB\nMemFree: 250 kB\nHugePages_Total: 2\n")
        self.assertEqual(values["MemTotal"], 1_024_000)
        self.assertEqual(values["MemFree"], 256_000)
        self.assertEqual(values["HugePages_Total"], 2)

    def test_calculates_cpu_delta(self) -> None:
        self.assertEqual(calculate_cpu_percent(None, (100, 50)), 0)
        self.assertAlmostEqual(calculate_cpu_percent((100, 40), (200, 70)), 70.0)
        self.assertEqual(calculate_cpu_percent((200, 80), (200, 80)), 0)


if __name__ == "__main__":
    unittest.main()
