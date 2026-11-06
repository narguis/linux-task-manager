from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HistorySample:
    key: str
    name: str
    icon_name: str
    cpu_percent: float
    memory_bytes: int
    process_io: tuple[tuple[tuple[int, int], int], ...]


@dataclass(slots=True)
class HistoryRecord:
    key: str
    name: str
    icon_name: str
    cpu_seconds: float = 0.0
    weighted_cpu: float = 0.0
    observed_seconds: float = 0.0
    peak_memory: int = 0
    disk_bytes: int = 0
    last_seen: float = 0.0

    @property
    def average_cpu(self) -> float:
        return self.weighted_cpu / self.observed_seconds if self.observed_seconds else 0.0


class ActivityHistory:
    """Accumulates app/process-group usage while Task Manager is open."""

    def __init__(self) -> None:
        self._records: dict[str, HistoryRecord] = {}
        self._previous_io: dict[tuple[int, int], int] = {}
        self._last_timestamp: float | None = None

    def update(self, samples: list[HistorySample], timestamp: float) -> list[HistoryRecord]:
        elapsed = 0.0
        if self._last_timestamp is not None:
            elapsed = max(0.0, min(10.0, timestamp - self._last_timestamp))
        self._last_timestamp = timestamp
        current_identities: set[tuple[int, int]] = set()

        for sample in samples:
            record = self._records.get(sample.key)
            if record is None:
                record = HistoryRecord(sample.key, sample.name, sample.icon_name)
                self._records[sample.key] = record
            record.name = sample.name
            record.icon_name = sample.icon_name
            record.cpu_seconds += sample.cpu_percent / 100.0 * elapsed
            record.weighted_cpu += sample.cpu_percent * elapsed
            record.observed_seconds += elapsed
            record.peak_memory = max(record.peak_memory, sample.memory_bytes)
            record.last_seen = timestamp
            for identity, total_io in sample.process_io:
                current_identities.add(identity)
                previous = self._previous_io.get(identity)
                if previous is not None:
                    record.disk_bytes += max(0, total_io - previous)
                self._previous_io[identity] = total_io

        for identity in set(self._previous_io) - current_identities:
            del self._previous_io[identity]
        return self.records()

    def records(self) -> list[HistoryRecord]:
        return sorted(self._records.values(), key=lambda item: (item.name.casefold(), item.key))

    def clear(self) -> None:
        self._records.clear()
        self._previous_io.clear()
        self._last_timestamp = None
