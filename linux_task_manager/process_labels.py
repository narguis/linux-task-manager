from __future__ import annotations

import re

from .models import ProcessInfo


_TYPE_PATTERN = re.compile(r"(?:^|\s)--type=([^\s]+)")
_UTILITY_PATTERN = re.compile(r"(?:^|\s)--utility-sub-type=([^\s]+)")
_RENDERER_ID_PATTERN = re.compile(r"(?:^|\s)--renderer-client-id=([^\s]+)")


def process_display_name(
    process: ProcessInfo,
    root: ProcessInfo,
    application_name: str | None,
) -> str:
    """Return a useful role label instead of repeating a browser executable name."""
    if process.pid == root.pid:
        return f"{application_name} · Main process" if application_name else process.name

    role = _command_role(process.command)
    base = application_name or root.name
    if role:
        return f"{base} · {role}"

    process_name = process.name.strip("()")
    if process_name.casefold() != root.name.casefold():
        return f"{base} · {process_name}"
    return f"{base} · Subprocess"


def _command_role(command: str) -> str | None:
    lowered = command.casefold()
    match = _TYPE_PATTERN.search(command)
    if not match:
        if "crashpad_handler" in lowered or "ptype=crashpad-handler" in lowered:
            return "Crash handler"
        if command.strip() == "cat":
            return "Crash report pipe"
        return None
    process_type = match.group(1).casefold()
    if process_type == "renderer":
        if "--extension-process" in lowered:
            return "Extension renderer"
        renderer_id = _RENDERER_ID_PATTERN.search(command)
        return f"Renderer #{renderer_id.group(1)}" if renderer_id else "Renderer"
    if process_type == "gpu-process":
        return "GPU process"
    if process_type == "zygote":
        return "Zygote"
    if process_type == "broker":
        return "Broker"
    if process_type == "utility":
        utility = _UTILITY_PATTERN.search(command)
        subtype = utility.group(1).casefold() if utility else ""
        utility_names = (
            ("network", "Network service"),
            ("audio", "Audio service"),
            ("storage", "Storage service"),
            ("data_decoder", "Data decoder"),
            ("video", "Video service"),
            ("media", "Media service"),
        )
        return next((label for marker, label in utility_names if marker in subtype), "Utility process")
    return process_type.replace("-", " ").title()
