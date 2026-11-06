from __future__ import annotations

import configparser
import os
import shlex
from functools import lru_cache
from pathlib import Path

from .models import ProcessInfo


_HELPER_MARKERS = ("--type=", "-contentproc", "utility-sub-type", "webextensions")


class ProcessIconResolver:
    """Matches Linux processes to installed desktop entries and their icons."""

    def __init__(self) -> None:
        self._icons: dict[str, str] = {}
        self._names: dict[str, str] = {}
        self._load_desktop_entries()

    def resolve(self, process: ProcessInfo) -> tuple[str, bool]:
        return self._resolve_values(
            process.name, process.executable, process.command, process.uid
        )

    @lru_cache(maxsize=4096)
    def _resolve_values(
        self, name: str, executable: str, command: str, uid: int
    ) -> tuple[str, bool]:
        command_lower = command.casefold()
        helper = any(marker in command_lower for marker in _HELPER_MARKERS)
        for key in self._process_keys(name, executable, command):
            icon = self._icons.get(key)
            if icon:
                return icon, not helper
        if name in {"python", "python3"} and (
            "linux_task_manager" in command_lower or "linux-task-manager" in command_lower
        ):
            return "io.github.systemtaskmanager.TaskManager", not helper
        if command.startswith("["):
            return "computer-symbolic", False
        if uid < 1000 or uid == 65534:
            return "system-run-symbolic", False
        return "application-x-executable-symbolic", False

    def display_name(self, process: ProcessInfo) -> str | None:
        return self._display_name_values(
            process.name, process.executable, process.command
        )

    @lru_cache(maxsize=4096)
    def _display_name_values(
        self, name: str, executable: str, command: str
    ) -> str | None:
        for key in self._process_keys(name, executable, command):
            display_name = self._names.get(key)
            if display_name:
                return display_name
        command_lower = command.casefold()
        if name in {"python", "python3"} and (
            "linux_task_manager" in command_lower or "linux-task-manager" in command_lower
        ):
            return "Linux Task Manager"
        return None

    def _load_desktop_entries(self) -> None:
        data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
        directories = [data_home / "applications"]
        directories.extend(
            Path(item) / "applications"
            for item in os.environ.get(
                "XDG_DATA_DIRS", "/usr/local/share:/usr/share"
            ).split(":")
            if item
        )
        directories.extend(
            (
                Path.home() / ".local/share/flatpak/exports/share/applications",
                Path("/var/lib/flatpak/exports/share/applications"),
                Path("/var/lib/snapd/desktop/applications"),
            )
        )
        # User entries should win, so only fill a key once.
        for directory in directories:
            if not directory.exists():
                continue
            for path in directory.glob("*.desktop"):
                self._read_desktop_entry(path)

    def _read_desktop_entry(self, path: Path) -> None:
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        parser.optionxform = str
        try:
            parser.read(path, encoding="utf-8")
            entry = parser["Desktop Entry"]
        except (OSError, UnicodeError, KeyError, configparser.Error):
            return
        if entry.get("Type", "Application") != "Application":
            return
        if entry.get("Hidden", "false").casefold() == "true" or entry.get(
            "NoDisplay", "false"
        ).casefold() == "true":
            return
        command = entry.get("Exec", "")
        executable = self._desktop_executable(command)
        icon = entry.get("Icon", "").strip()
        if icon.startswith("/"):
            icon = Path(executable).name if executable else path.stem.rsplit("_", 1)[-1]
        if not icon:
            return
        name = entry.get("Name", "").strip()
        keys = {
            path.stem.casefold(),
            entry.get("StartupWMClass", "").casefold(),
            entry.get("TryExec", "").casefold(),
        }
        if executable:
            keys.add(executable.casefold())
            keys.add(Path(executable).name.casefold())
        aliases = set()
        for key in keys:
            normalized = Path(key).name.casefold()
            normalized = normalized.removeprefix("google-").removesuffix("-stable")
            if normalized and normalized != key:
                aliases.add(normalized)
        keys.update(aliases)
        for key in keys:
            if key:
                self._icons.setdefault(key, icon)
                if name:
                    self._names.setdefault(key, name)

    @staticmethod
    def _desktop_executable(command: str) -> str:
        try:
            arguments = shlex.split(command)
        except ValueError:
            return ""
        while arguments and (arguments[0] == "env" or "=" in arguments[0]):
            arguments.pop(0)
        if not arguments:
            return ""
        if arguments[0] == "flatpak" and "run" in arguments:
            index = arguments.index("run") + 1
            while index < len(arguments) and arguments[index].startswith("-"):
                index += 1
            return arguments[index] if index < len(arguments) else ""
        return arguments[0]

    @staticmethod
    def _process_keys(name: str, executable: str, command: str) -> tuple[str, ...]:
        keys = [name.casefold()]
        if executable:
            keys.extend((executable.casefold(), Path(executable).name.casefold()))
        try:
            arguments = shlex.split(command)
        except ValueError:
            arguments = []
        if arguments:
            keys.extend((arguments[0].casefold(), Path(arguments[0]).name.casefold()))
            if "flatpak" in arguments[0] and "run" in arguments:
                index = arguments.index("run") + 1
                if index < len(arguments):
                    keys.append(arguments[index].casefold())
        return tuple(dict.fromkeys(keys))
