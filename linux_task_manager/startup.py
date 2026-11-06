from __future__ import annotations

import configparser
import os
from pathlib import Path

from .models import ActionResult, StartupEntry


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class StartupManager:
    def __init__(self, config_home: str | Path | None = None) -> None:
        self.config_home = Path(
            config_home or os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")
        )
        self.user_dir = self.config_home / "autostart"
        self.system_dirs = [
            Path(item) / "autostart"
            for item in os.environ.get("XDG_CONFIG_DIRS", "/etc/xdg").split(":")
            if item
        ]

    def list_entries(self) -> list[StartupEntry]:
        candidates: dict[str, tuple[Path, str]] = {}
        for directory in self.system_dirs:
            if directory.exists():
                for path in directory.glob("*.desktop"):
                    candidates.setdefault(path.name, (path, "System"))
        if self.user_dir.exists():
            for path in self.user_dir.glob("*.desktop"):
                candidates[path.name] = (path, "User")

        entries: list[StartupEntry] = []
        for entry_id, (path, scope) in candidates.items():
            entry = self._parse_entry(entry_id, path, scope)
            if entry:
                entries.append(entry)
        return sorted(entries, key=lambda item: item.name.casefold())

    def set_enabled(self, entry: StartupEntry, enabled: bool) -> ActionResult:
        source = Path(entry.source)
        target = source
        if entry.scope == "System":
            target = self.user_dir / entry.entry_id
        try:
            text = source.read_text(encoding="utf-8", errors="replace")
            text = self._set_desktop_key(text, "Hidden", "false" if enabled else "true")
            text = self._set_desktop_key(
                text, "X-GNOME-Autostart-enabled", "true" if enabled else "false"
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
            state = "enabled" if enabled else "disabled"
            return ActionResult(True, f"{entry.name} is now {state}")
        except (OSError, PermissionError) as error:
            return ActionResult(False, f"Could not update the startup entry: {error}")

    @staticmethod
    def _parse_entry(entry_id: str, path: Path, scope: str) -> StartupEntry | None:
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        parser.optionxform = str
        try:
            parser.read(path, encoding="utf-8")
            section = parser["Desktop Entry"]
        except (OSError, UnicodeError, KeyError, configparser.Error):
            return None
        if section.get("Type", "Application") != "Application":
            return None
        name = section.get("Name", path.stem)
        command = section.get("Exec", "")
        hidden = _bool(section.get("Hidden"), False)
        gnome_enabled = _bool(section.get("X-GNOME-Autostart-enabled"), True)
        return StartupEntry(
            entry_id=entry_id,
            name=name,
            command=command,
            description=section.get("Comment", ""),
            enabled=not hidden and gnome_enabled,
            source=str(path),
            scope=scope,
        )

    @staticmethod
    def _set_desktop_key(text: str, key: str, value: str) -> str:
        lines = text.splitlines()
        in_desktop = False
        inserted = False
        output: list[str] = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                if in_desktop and not inserted:
                    output.append(f"{key}={value}")
                    inserted = True
                in_desktop = stripped == "[Desktop Entry]"
            if in_desktop and stripped.startswith(f"{key}="):
                if not inserted:
                    output.append(f"{key}={value}")
                    inserted = True
                continue
            output.append(line)
        if in_desktop and not inserted:
            output.append(f"{key}={value}")
        if not any(line.strip() == "[Desktop Entry]" for line in lines):
            output = ["[Desktop Entry]", f"{key}={value}", *lines]
        return "\n".join(output) + "\n"
