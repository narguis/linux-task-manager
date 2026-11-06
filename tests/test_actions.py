import os
import unittest

from linux_task_manager.actions import ProcessController
from linux_task_manager.models import ProcessInfo


def process_info(pid: int, start_ticks: int) -> ProcessInfo:
    return ProcessInfo(
        pid=pid,
        ppid=1,
        session_id=pid,
        start_ticks=start_ticks,
        name="test",
        username="test",
        uid=os.getuid(),
        status="Sleeping",
        cpu_percent=0,
        memory_percent=0,
        rss_bytes=0,
        read_bytes=0,
        write_bytes=0,
        io_rate=0,
        threads=1,
        nice=0,
        command="test",
        executable="",
        cwd="",
    )


class ProcessControllerTests(unittest.TestCase):
    def test_refuses_pid_one(self) -> None:
        result = ProcessController().terminate(process_info(1, 1))
        self.assertFalse(result.ok)
        self.assertIn("essential", result.message)

    def test_refuses_stale_identity(self) -> None:
        result = ProcessController().terminate(process_info(999_999_999, 1))
        self.assertFalse(result.ok)
        self.assertIn("exited", result.message)

if __name__ == "__main__":
    unittest.main()
