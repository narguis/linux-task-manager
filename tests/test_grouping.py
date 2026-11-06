import os
import unittest

from linux_task_manager.grouping import build_process_groups, filter_process_groups
from linux_task_manager.models import ProcessInfo


def process(
    pid: int,
    name: str,
    *,
    ppid: int = 1,
    uid: int = 1000,
    app: bool = False,
    cpu: float = 0,
    memory: int = 0,
) -> ProcessInfo:
    return ProcessInfo(
        pid=pid,
        ppid=ppid,
        session_id=pid,
        start_ticks=pid * 10,
        name=name,
        username="user" if uid else "root",
        uid=uid,
        status="Running",
        cpu_percent=cpu,
        memory_percent=0,
        rss_bytes=memory,
        read_bytes=0,
        write_bytes=0,
        io_rate=0,
        threads=1,
        nice=0,
        command=name,
        executable=f"/usr/bin/{name}",
        cwd="/tmp",
        is_application=app,
    )


class ProcessGroupingTests(unittest.TestCase):
    def test_groups_child_processes_and_aggregates_usage(self) -> None:
        items = [
            process(100, "browser", app=True, cpu=4, memory=100),
            process(101, "renderer", ppid=100, cpu=3, memory=50),
            process(102, "worker", ppid=101, cpu=2, memory=25),
            process(200, "daemon", uid=0),
        ]
        groups = build_process_groups(items)
        browser = next(group for group in groups if group.root.process.pid == 100)
        self.assertEqual(browser.section, "Apps")
        self.assertEqual(len(browser.root.members), 3)
        self.assertEqual(browser.root.cpu_percent, 9)
        self.assertEqual(browser.root.memory_bytes, 175)
        daemon = next(group for group in groups if group.root.process.pid == 200)
        self.assertEqual(daemon.section, "System processes")

    def test_search_keeps_the_whole_matching_group(self) -> None:
        groups = build_process_groups(
            [process(100, "browser", app=True), process(101, "renderer", ppid=100)]
        )
        filtered = filter_process_groups(groups, "All processes", "renderer", os.getuid())
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0].root.process.name, "browser")


if __name__ == "__main__":
    unittest.main()
