from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ProcessInfo:
    pid: int
    ppid: int
    session_id: int
    start_ticks: int
    name: str
    username: str
    uid: int
    status: str
    cpu_percent: float
    memory_percent: float
    rss_bytes: int
    read_bytes: int
    write_bytes: int
    io_rate: float
    threads: int
    nice: int
    command: str
    executable: str
    cwd: str
    is_application: bool = False


@dataclass(frozen=True, slots=True)
class SystemSnapshot:
    timestamp: float
    cpu_percent: float
    per_cpu_percent: tuple[float, ...]
    memory_total: int
    memory_used: int
    memory_available: int
    memory_cached: int
    swap_total: int
    swap_used: int
    disk_total: int
    disk_used: int
    disk_read_rate: float
    disk_write_rate: float
    disk_busy_percent: float
    network_receive_rate: float
    network_send_rate: float
    load_average: tuple[float, float, float]
    uptime_seconds: float
    process_count: int
    thread_count: int
    cpu_count: int
    cpu_model: str
    temperature_c: float | None = None

    @property
    def memory_percent(self) -> float:
        if not self.memory_total:
            return 0.0
        return self.memory_used * 100.0 / self.memory_total

    @property
    def swap_percent(self) -> float:
        if not self.swap_total:
            return 0.0
        return self.swap_used * 100.0 / self.swap_total

    @property
    def disk_percent(self) -> float:
        if not self.disk_total:
            return 0.0
        return self.disk_used * 100.0 / self.disk_total


@dataclass(frozen=True, slots=True)
class StartupEntry:
    entry_id: str
    name: str
    command: str
    description: str
    enabled: bool
    source: str
    scope: str


@dataclass(frozen=True, slots=True)
class ServiceInfo:
    name: str
    description: str
    load_state: str
    active_state: str
    sub_state: str
    enabled_state: str


@dataclass(frozen=True, slots=True)
class UserInfo:
    username: str
    sessions: int
    process_count: int
    cpu_percent: float
    memory_bytes: int
    terminals: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class ActionResult:
    ok: bool
    message: str
    new_pid: int | None = None
