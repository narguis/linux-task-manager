from __future__ import annotations

import os
import signal
import subprocess
from pathlib import Path

from .models import ActionResult, ProcessInfo
from .monitor import parse_proc_stat_line


class ProcessController:
    """Performs identity-checked process actions to avoid PID reuse mistakes."""

    def __init__(self, proc_root: str | Path = "/proc") -> None:
        self.proc_root = Path(proc_root)

    def terminate(self, process: ProcessInfo) -> ActionResult:
        return self._signal(process, signal.SIGTERM, "Close signal sent")

    def kill(self, process: ProcessInfo) -> ActionResult:
        return self._signal(process, signal.SIGKILL, "Process forcefully ended")

    def suspend(self, process: ProcessInfo) -> ActionResult:
        return self._signal(process, signal.SIGSTOP, "Process suspended")

    def resume(self, process: ProcessInfo) -> ActionResult:
        return self._signal(process, signal.SIGCONT, "Process resumed")

    def set_priority(self, process: ProcessInfo, nice: int) -> ActionResult:
        invalid = self._validate(process)
        if invalid:
            return invalid
        try:
            os.setpriority(os.PRIO_PROCESS, process.pid, max(-20, min(19, nice)))
            return ActionResult(True, f"Priority changed to {nice}")
        except PermissionError:
            return ActionResult(False, "Permission denied. Raising priority may require administrator access.")
        except (OSError, ProcessLookupError) as error:
            return ActionResult(False, f"Could not change priority: {error}")

    def open_location(self, process: ProcessInfo) -> ActionResult:
        executable = process.executable
        if not executable:
            return ActionResult(False, "The executable location is not available.")
        directory = os.path.dirname(executable)
        try:
            subprocess.Popen(
                ["xdg-open", directory],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return ActionResult(True, f"Opened {directory}")
        except OSError as error:
            return ActionResult(False, f"Could not open the location: {error}")

    def _signal(self, process: ProcessInfo, selected_signal: signal.Signals, success: str) -> ActionResult:
        invalid = self._validate(process)
        if invalid:
            return invalid
        try:
            os.kill(process.pid, selected_signal)
            return ActionResult(True, success)
        except PermissionError:
            return ActionResult(False, "Permission denied. You can only control your own processes without administrator access.")
        except ProcessLookupError:
            return ActionResult(False, "The process has already exited.")
        except OSError as error:
            return ActionResult(False, f"Process action failed: {error}")

    def _validate(self, process: ProcessInfo) -> ActionResult | None:
        if process.pid in {0, 1}:
            return ActionResult(False, "This essential system process cannot be controlled here.")
        if process.pid == os.getpid():
            return ActionResult(False, "Use the window close button to exit Task Manager.")
        if not self._same_process(process):
            return ActionResult(False, "The selected process has already exited or its PID was reused.")
        return None

    def _same_process(self, process: ProcessInfo) -> bool:
        try:
            line = (self.proc_root / str(process.pid) / "stat").read_text(
                encoding="utf-8", errors="replace"
            )
            return int(parse_proc_stat_line(line)["start_ticks"]) == process.start_ticks
        except (OSError, PermissionError, ValueError, TypeError):
            return False
