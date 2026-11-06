from __future__ import annotations

import os
import pwd
import shutil
import subprocess
import threading
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable

from .models import ProcessInfo, SystemSnapshot, UserInfo


_STATUS_NAMES = {
    "R": "Running",
    "S": "Sleeping",
    "D": "Disk sleep",
    "Z": "Zombie",
    "T": "Stopped",
    "t": "Tracing",
    "X": "Dead",
    "I": "Idle",
    "P": "Parked",
}


def parse_proc_stat_line(line: str) -> dict[str, int | str]:
    """Parse one /proc/<pid>/stat line, including names containing spaces."""
    left = line.find("(")
    right = line.rfind(")")
    if left < 1 or right <= left:
        raise ValueError("invalid process stat line")
    pid = int(line[:left].strip())
    name = line[left + 1 : right]
    fields = line[right + 2 :].split()
    if len(fields) < 22:
        raise ValueError("incomplete process stat line")
    return {
        "pid": pid,
        "name": name,
        "state": fields[0],
        "ppid": int(fields[1]),
        "session_id": int(fields[3]),
        "utime": int(fields[11]),
        "stime": int(fields[12]),
        "nice": int(fields[16]),
        "threads": int(fields[17]),
        "start_ticks": int(fields[19]),
        "rss_pages": int(fields[21]),
    }


def parse_meminfo(text: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, raw_value = line.split(":", 1)
        parts = raw_value.strip().split()
        if not parts:
            continue
        try:
            value = int(parts[0])
        except ValueError:
            continue
        if len(parts) > 1 and parts[1].lower() == "kb":
            value *= 1024
        result[key] = value
    return result


def calculate_cpu_percent(
    previous: tuple[int, int] | None, current: tuple[int, int]
) -> float:
    if previous is None:
        return 0.0
    previous_total, previous_idle = previous
    total_delta = current[0] - previous_total
    idle_delta = current[1] - previous_idle
    if total_delta <= 0:
        return 0.0
    return max(0.0, min(100.0, (total_delta - idle_delta) * 100.0 / total_delta))


def _read_text(path: str | Path, default: str = "") -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except (OSError, PermissionError):
        return default


def _read_bytes(path: str | Path) -> bytes:
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except (OSError, PermissionError):
        return b""


@dataclass(frozen=True, slots=True)
class _StaticProcessInfo:
    name: str
    uid: int
    username: str
    command: str
    executable: str
    cwd: str


class SystemMonitor:
    """Collects system and process data behind a small, thread-safe interface."""

    def __init__(self, proc_root: str | Path = "/proc") -> None:
        self.proc_root = Path(proc_root)
        self.clock_ticks = int(os.sysconf("SC_CLK_TCK"))
        self.page_size = int(os.sysconf("SC_PAGE_SIZE"))
        self.cpu_count = os.cpu_count() or 1
        self._lock = threading.Lock()
        self._previous_cpu: list[tuple[int, int]] = []
        self._previous_disk: tuple[float, int, int, int] | None = None
        self._previous_network: tuple[float, int, int] | None = None
        self._previous_processes: dict[int, tuple[int, int, int, int]] = {}
        self._previous_process_time: float | None = None
        self._static_processes: dict[tuple[int, int], _StaticProcessInfo] = {}
        self._usernames: dict[int, str] = {}
        self._cpu_model = self._read_cpu_model()

    def collect(self) -> tuple[SystemSnapshot, list[ProcessInfo]]:
        with self._lock:
            snapshot = self._collect_snapshot()
            processes = self._collect_processes(snapshot.memory_total)
            snapshot = replace(
                snapshot,
                process_count=len(processes),
                thread_count=sum(item.threads for item in processes),
            )
            return snapshot, processes

    def process_identity(self, pid: int) -> int | None:
        try:
            parsed = parse_proc_stat_line(_read_text(self.proc_root / str(pid) / "stat"))
            return int(parsed["start_ticks"])
        except (ValueError, TypeError):
            return None

    def _collect_snapshot(self) -> SystemSnapshot:
        now = time.monotonic()
        cpu_values = self._read_cpu_times()
        percentages = [
            calculate_cpu_percent(
                self._previous_cpu[index] if index < len(self._previous_cpu) else None,
                value,
            )
            for index, value in enumerate(cpu_values)
        ]
        self._previous_cpu = cpu_values

        meminfo = parse_meminfo(_read_text(self.proc_root / "meminfo"))
        memory_total = meminfo.get("MemTotal", 0)
        memory_available = meminfo.get("MemAvailable", meminfo.get("MemFree", 0))
        memory_used = max(0, memory_total - memory_available)
        memory_cached = meminfo.get("Cached", 0) + meminfo.get("SReclaimable", 0)
        swap_total = meminfo.get("SwapTotal", 0)
        swap_used = max(0, swap_total - meminfo.get("SwapFree", 0))

        try:
            disk_usage = shutil.disk_usage("/")
            disk_total, disk_used = disk_usage.total, disk_usage.used
        except OSError:
            disk_total = disk_used = 0
        disk_read_rate, disk_write_rate, disk_busy = self._read_disk_rates(now)
        network_receive_rate, network_send_rate = self._read_network_rates(now)

        try:
            uptime = float(_read_text(self.proc_root / "uptime").split()[0])
        except (ValueError, IndexError):
            uptime = 0.0
        try:
            load_average = tuple(os.getloadavg())
        except OSError:
            load_average = (0.0, 0.0, 0.0)

        return SystemSnapshot(
            timestamp=time.time(),
            cpu_percent=percentages[0] if percentages else 0.0,
            per_cpu_percent=tuple(percentages[1:]),
            memory_total=memory_total,
            memory_used=memory_used,
            memory_available=memory_available,
            memory_cached=memory_cached,
            swap_total=swap_total,
            swap_used=swap_used,
            disk_total=disk_total,
            disk_used=disk_used,
            disk_read_rate=disk_read_rate,
            disk_write_rate=disk_write_rate,
            disk_busy_percent=disk_busy,
            network_receive_rate=network_receive_rate,
            network_send_rate=network_send_rate,
            load_average=(float(load_average[0]), float(load_average[1]), float(load_average[2])),
            uptime_seconds=uptime,
            process_count=0,
            thread_count=0,
            cpu_count=self.cpu_count,
            cpu_model=self._cpu_model,
            temperature_c=self._read_temperature(),
        )

    def _read_cpu_times(self) -> list[tuple[int, int]]:
        result: list[tuple[int, int]] = []
        for line in _read_text(self.proc_root / "stat").splitlines():
            if not line.startswith("cpu"):
                break
            name, *raw_values = line.split()
            if name != "cpu" and not name[3:].isdigit():
                continue
            values = [int(value) for value in raw_values]
            total = sum(values)
            idle = (values[3] if len(values) > 3 else 0) + (
                values[4] if len(values) > 4 else 0
            )
            result.append((total, idle))
        return result

    def _read_cpu_model(self) -> str:
        for line in _read_text(self.proc_root / "cpuinfo").splitlines():
            if line.lower().startswith(("model name", "hardware", "processor")) and ":" in line:
                value = line.split(":", 1)[1].strip()
                if value:
                    return value
        return "Unknown processor"

    def _read_disk_rates(self, now: float) -> tuple[float, float, float]:
        allowed = set()
        sys_block = Path("/sys/block")
        if sys_block.exists():
            allowed = {
                path.name
                for path in sys_block.iterdir()
                if not path.name.startswith(("loop", "ram", "fd", "sr", "zram", "dm-", "md"))
            }
        read_bytes = write_bytes = busy_ms = 0
        for line in _read_text(self.proc_root / "diskstats").splitlines():
            fields = line.split()
            if len(fields) < 13:
                continue
            name = fields[2]
            if allowed and name not in allowed:
                continue
            if not allowed and (name[-1:].isdigit() or name.startswith(("loop", "ram"))):
                continue
            try:
                read_bytes += int(fields[5]) * 512
                write_bytes += int(fields[9]) * 512
                busy_ms += int(fields[12])
            except ValueError:
                continue
        rates = (0.0, 0.0, 0.0)
        if self._previous_disk:
            old_time, old_read, old_write, old_busy = self._previous_disk
            elapsed = now - old_time
            if elapsed > 0:
                rates = (
                    max(0, read_bytes - old_read) / elapsed,
                    max(0, write_bytes - old_write) / elapsed,
                    min(100.0, max(0, busy_ms - old_busy) / (elapsed * 10.0)),
                )
        self._previous_disk = (now, read_bytes, write_bytes, busy_ms)
        return rates

    def _read_network_rates(self, now: float) -> tuple[float, float]:
        received = sent = 0
        for line in _read_text(self.proc_root / "net/dev").splitlines()[2:]:
            if ":" not in line:
                continue
            interface, values = line.split(":", 1)
            if interface.strip() == "lo":
                continue
            fields = values.split()
            if len(fields) < 9:
                continue
            try:
                received += int(fields[0])
                sent += int(fields[8])
            except ValueError:
                continue
        rates = (0.0, 0.0)
        if self._previous_network:
            old_time, old_received, old_sent = self._previous_network
            elapsed = now - old_time
            if elapsed > 0:
                rates = (
                    max(0, received - old_received) / elapsed,
                    max(0, sent - old_sent) / elapsed,
                )
        self._previous_network = (now, received, sent)
        return rates

    def _collect_processes(self, memory_total: int) -> list[ProcessInfo]:
        now = time.monotonic()
        elapsed = now - self._previous_process_time if self._previous_process_time else 0.0
        current_cache: dict[int, tuple[int, int, int, int]] = {}
        current_static: dict[tuple[int, int], _StaticProcessInfo] = {}
        processes: list[ProcessInfo] = []

        try:
            directories: Iterable[os.DirEntry[str]] = os.scandir(self.proc_root)
        except OSError:
            directories = ()
        for process_dir in directories:
            if not process_dir.name.isdigit():
                continue
            try:
                process_path = process_dir.path
                stat = parse_proc_stat_line(
                    _read_text(os.path.join(process_path, "stat"))
                )
                pid = int(stat["pid"])
                start_ticks = int(stat["start_ticks"])
                cpu_ticks = int(stat["utime"]) + int(stat["stime"])
                name = str(stat["name"])
                uid = process_dir.stat(follow_symlinks=False).st_uid
                static_key = (pid, start_ticks)
                static = self._static_processes.get(static_key)
                if static is None or static.name != name or static.uid != uid:
                    cmdline_parts = [
                        part.decode("utf-8", errors="replace")
                        for part in _read_bytes(
                            os.path.join(process_path, "cmdline")
                        ).split(b"\0")
                        if part
                    ]
                    command = " ".join(cmdline_parts) or f"[{name}]"
                    static = _StaticProcessInfo(
                        name=name,
                        uid=uid,
                        username=self._username_for_uid(uid),
                        command=command,
                        executable=self._read_link(
                            os.path.join(process_path, "exe")
                        ),
                        cwd=self._read_link(os.path.join(process_path, "cwd")),
                    )
                current_static[static_key] = static
                if static.command.startswith("["):
                    read_bytes = write_bytes = 0
                else:
                    read_bytes, write_bytes = self._read_process_io(process_path)
                current_cache[pid] = (start_ticks, cpu_ticks, read_bytes, write_bytes)
                previous = self._previous_processes.get(pid)
                cpu_percent = io_rate = 0.0
                if previous and previous[0] == start_ticks and elapsed > 0:
                    cpu_percent = max(
                        0.0,
                        (cpu_ticks - previous[1])
                        / self.clock_ticks
                        / elapsed
                        / self.cpu_count
                        * 100.0,
                    )
                    io_rate = (
                        max(0, read_bytes - previous[2]) + max(0, write_bytes - previous[3])
                    ) / elapsed

                rss_bytes = int(stat["rss_pages"]) * self.page_size
                threads = int(stat["threads"])
                processes.append(
                    ProcessInfo(
                        pid=pid,
                        ppid=int(stat["ppid"]),
                        session_id=int(stat["session_id"]),
                        start_ticks=start_ticks,
                        name=name,
                        username=static.username,
                        uid=uid,
                        status=_STATUS_NAMES.get(str(stat["state"]), str(stat["state"])),
                        cpu_percent=min(100.0, cpu_percent),
                        memory_percent=(rss_bytes * 100.0 / memory_total) if memory_total else 0.0,
                        rss_bytes=rss_bytes,
                        read_bytes=read_bytes,
                        write_bytes=write_bytes,
                        io_rate=io_rate,
                        threads=threads,
                        nice=int(stat["nice"]),
                        command=static.command,
                        executable=static.executable,
                        cwd=static.cwd,
                        is_application=False,
                    )
                )
            except (OSError, PermissionError, ValueError, ProcessLookupError):
                continue
        self._previous_processes = current_cache
        self._static_processes = current_static
        self._previous_process_time = now
        return processes

    def _username_for_uid(self, uid: int) -> str:
        username = self._usernames.get(uid)
        if username is not None:
            return username
        try:
            username = pwd.getpwuid(uid).pw_name
        except KeyError:
            username = str(uid)
        self._usernames[uid] = username
        return username

    @staticmethod
    def _read_process_io(process_dir: str | Path) -> tuple[int, int]:
        values: dict[str, int] = {}
        for line in _read_text(os.path.join(os.fspath(process_dir), "io")).splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            try:
                values[key] = int(value.strip())
            except ValueError:
                continue
        return values.get("read_bytes", 0), values.get("write_bytes", 0)

    @staticmethod
    def _read_link(path: str | Path) -> str:
        try:
            return os.readlink(path)
        except (OSError, PermissionError):
            return ""

    @staticmethod
    def _read_temperature() -> float | None:
        values: list[float] = []
        for path in Path("/sys/class/thermal").glob("thermal_zone*/temp"):
            try:
                value = float(path.read_text().strip())
                if value > 1000:
                    value /= 1000.0
                if 0 < value < 150:
                    values.append(value)
            except (OSError, ValueError):
                continue
        return max(values) if values else None


def build_user_summary(processes: list[ProcessInfo]) -> list[UserInfo]:
    sessions: Counter[str] = Counter()
    terminals: dict[str, list[str]] = defaultdict(list)
    try:
        output = subprocess.run(
            ["who"], capture_output=True, text=True, check=False, timeout=3
        ).stdout
        for line in output.splitlines():
            fields = line.split()
            if not fields:
                continue
            sessions[fields[0]] += 1
            if len(fields) > 1:
                terminals[fields[0]].append(fields[1])
    except (OSError, subprocess.TimeoutExpired):
        pass

    grouped: dict[str, list[ProcessInfo]] = defaultdict(list)
    for process in processes:
        grouped[process.username].append(process)
    users = set(grouped) | set(sessions)
    result = []
    for username in users:
        owned = grouped.get(username, [])
        result.append(
            UserInfo(
                username=username,
                sessions=sessions[username],
                process_count=len(owned),
                cpu_percent=sum(item.cpu_percent for item in owned),
                memory_bytes=sum(item.rss_bytes for item in owned),
                terminals=tuple(terminals[username]),
            )
        )
    return sorted(result, key=lambda item: (-item.sessions, item.username.lower()))
