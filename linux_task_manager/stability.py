from __future__ import annotations

from dataclasses import dataclass

from .models import ProcessInfo


@dataclass(slots=True)
class _TrackedProcess:
    process: ProcessInfo
    consecutive_samples: int = 1
    missed_samples: int = 0
    visible: bool = False


class ProcessListStabilizer:
    """Hides one-shot process churn and bridges occasional procfs read misses."""

    def __init__(self, appearances: int = 2, disappearance_grace: int = 2) -> None:
        self.appearances = max(1, appearances)
        self.disappearance_grace = max(0, disappearance_grace)
        self._tracked: dict[tuple[int, int], _TrackedProcess] = {}
        self._initialized = False

    def update(self, processes: list[ProcessInfo]) -> list[ProcessInfo]:
        current = {(item.pid, item.start_ticks): item for item in processes}
        if not self._initialized:
            self._tracked = {
                key: _TrackedProcess(item, visible=True) for key, item in current.items()
            }
            self._initialized = True
            return list(processes)

        for key, item in current.items():
            tracked = self._tracked.get(key)
            if tracked is None:
                tracked = _TrackedProcess(item)
                self._tracked[key] = tracked
            else:
                tracked.process = item
                tracked.consecutive_samples += 1
                tracked.missed_samples = 0
            if tracked.consecutive_samples >= self.appearances:
                tracked.visible = True

        for key in list(self._tracked):
            if key in current:
                continue
            tracked = self._tracked[key]
            if not tracked.visible:
                del self._tracked[key]
                continue
            tracked.missed_samples += 1
            if tracked.missed_samples > self.disappearance_grace:
                del self._tracked[key]

        return [
            tracked.process
            for tracked in self._tracked.values()
            if tracked.visible
        ]
