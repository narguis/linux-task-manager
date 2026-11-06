from __future__ import annotations

from dataclasses import dataclass, field

from .models import ProcessInfo


SECTION_ORDER = ("Apps", "Background processes", "System processes")
_ROOT_PARENTS = {"systemd", "init", "kthreadd", "gnome-shell", "plasmashell"}


@dataclass(frozen=True, slots=True)
class ProcessNode:
    process: ProcessInfo
    children: tuple["ProcessNode", ...] = ()
    _members: tuple[ProcessInfo, ...] = field(init=False, repr=False)
    _cpu_percent: float = field(init=False, repr=False)
    _memory_bytes: int = field(init=False, repr=False)
    _io_rate: float = field(init=False, repr=False)

    def __post_init__(self) -> None:
        members = (self.process, *(
            member for child in self.children for member in child.members
        ))
        object.__setattr__(self, "_members", members)
        object.__setattr__(
            self, "_cpu_percent", sum(item.cpu_percent for item in members)
        )
        object.__setattr__(
            self, "_memory_bytes", sum(item.rss_bytes for item in members)
        )
        object.__setattr__(self, "_io_rate", sum(item.io_rate for item in members))

    @property
    def members(self) -> tuple[ProcessInfo, ...]:
        return self._members

    @property
    def cpu_percent(self) -> float:
        return self._cpu_percent

    @property
    def memory_bytes(self) -> int:
        return self._memory_bytes

    @property
    def io_rate(self) -> float:
        return self._io_rate


@dataclass(frozen=True, slots=True)
class ProcessGroup:
    section: str
    root: ProcessNode


def build_process_groups(processes: list[ProcessInfo]) -> list[ProcessGroup]:
    """Build useful app/process trees without grouping everything under systemd."""
    by_pid = {item.pid: item for item in processes}
    parent_by_pid: dict[int, int] = {}
    children_by_pid: dict[int, list[int]] = {}

    for process in processes:
        parent = by_pid.get(process.ppid)
        if (
            parent is None
            or parent.pid == process.pid
            or parent.name.casefold() in _ROOT_PARENTS
            or parent.uid != process.uid
            or process.is_application
        ):
            continue
        parent_by_pid[process.pid] = parent.pid
        children_by_pid.setdefault(parent.pid, []).append(process.pid)

    def make_node(pid: int, ancestors: frozenset[int] = frozenset()) -> ProcessNode:
        process = by_pid[pid]
        if pid in ancestors:
            return ProcessNode(process)
        children = tuple(
            make_node(child_pid, ancestors | {pid})
            for child_pid in sorted(
                children_by_pid.get(pid, []),
                key=lambda child: (by_pid[child].name.casefold(), child),
            )
        )
        return ProcessNode(process, children)

    roots = [item for item in processes if item.pid not in parent_by_pid]
    groups: list[ProcessGroup] = []
    for process in roots:
        if process.is_application:
            section = "Apps"
        elif process.uid < 1000 or process.uid == 65534:
            section = "System processes"
        else:
            section = "Background processes"
        groups.append(ProcessGroup(section, make_node(process.pid)))
    return sorted(
        groups,
        key=lambda group: (
            SECTION_ORDER.index(group.section),
            group.root.process.name.casefold(),
            group.root.process.pid,
        ),
    )


def filter_process_groups(
    groups: list[ProcessGroup],
    view: str,
    query: str,
    current_uid: int,
) -> list[ProcessGroup]:
    query = query.strip().casefold()
    result: list[ProcessGroup] = []
    for group in groups:
        root = group.root.process
        if view == "My processes" and root.uid != current_uid:
            continue
        if view == "Apps" and group.section != "Apps":
            continue
        if view == "System processes" and group.section != "System processes":
            continue
        if query:
            matches = any(
                query
                in f"{item.name} {item.pid} {item.username} {item.command}".casefold()
                for item in group.root.members
            )
            if not matches:
                continue
        result.append(group)
    return result
