import unittest

from linux_task_manager.formatting import (
    format_bytes,
    format_duration,
    format_percent,
    format_rate,
    format_uptime,
)


class FormattingTests(unittest.TestCase):
    def test_formats_binary_byte_units(self) -> None:
        self.assertEqual(format_bytes(0), "0 B")
        self.assertEqual(format_bytes(1024), "1.0 KB")
        self.assertEqual(format_bytes(5 * 1024**3), "5.0 GB")
        self.assertEqual(format_rate(2048), "2.0 KB/s")

    def test_formats_percentages(self) -> None:
        self.assertEqual(format_percent(0.01), "0%")
        self.assertEqual(format_percent(2.34), "2.3%")
        self.assertEqual(format_percent(52.8), "53%")

    def test_formats_duration(self) -> None:
        self.assertEqual(format_duration(59), "0m")
        self.assertEqual(format_duration(3660), "1h 1m")
        self.assertEqual(format_duration(90060), "1d 1h 1m")

    def test_formats_uptime_to_seconds(self) -> None:
        self.assertEqual(format_uptime(3661), "01:01:01")
        self.assertEqual(format_uptime(90061), "1d 01:01:01")


if __name__ == "__main__":
    unittest.main()
