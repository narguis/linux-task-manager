from __future__ import annotations

import os
import platform
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .formatting import format_bytes
from .monitor import parse_meminfo


@dataclass(frozen=True, slots=True)
class SystemInfo:
    hostname: str
    manufacturer: str
    model: str
    firmware: str
    os_name: str
    kernel: str
    architecture: str
    desktop: str
    session_type: str
    virtualization: str
    cpu_model: str
    physical_cores: int
    logical_cores: int
    max_frequency: str
    graphics: tuple[str, ...]
    memory: str
    swap: str
    storage: tuple[str, ...]


def collect_system_info() -> SystemInfo:
    cpu_model, physical_cores, max_frequency = _cpu_details()
    meminfo = parse_meminfo(_read(Path("/proc/meminfo")))
    manufacturer = _read(Path("/sys/devices/virtual/dmi/id/sys_vendor")).strip()
    product = _read(Path("/sys/devices/virtual/dmi/id/product_name")).strip()
    product_version = _read(Path("/sys/devices/virtual/dmi/id/product_version")).strip()
    model = " ".join(
        item for item in (product, product_version) if item and item.casefold() != "none"
    )
    bios_vendor = _read(Path("/sys/devices/virtual/dmi/id/bios_vendor")).strip()
    bios_version = _read(Path("/sys/devices/virtual/dmi/id/bios_version")).strip()
    bios_date = _read(Path("/sys/devices/virtual/dmi/id/bios_date")).strip()
    firmware = " · ".join(item for item in (bios_vendor, bios_version, bios_date) if item)

    return SystemInfo(
        hostname=platform.node() or "Unknown computer",
        manufacturer=manufacturer or "Unknown",
        model=model or "Unknown",
        firmware=firmware or "Unknown",
        os_name=_os_name(),
        kernel=f"Linux {platform.release()}",
        architecture=platform.machine() or "Unknown",
        desktop=os.environ.get("XDG_CURRENT_DESKTOP", "Unknown").replace(":", " / "),
        session_type=os.environ.get("XDG_SESSION_TYPE", "Unknown").title(),
        virtualization=_virtualization(),
        cpu_model=cpu_model,
        physical_cores=physical_cores,
        logical_cores=os.cpu_count() or 1,
        max_frequency=max_frequency,
        graphics=tuple(_graphics_devices()) or ("Not detected",),
        memory=format_bytes(meminfo.get("MemTotal", 0)),
        swap=format_bytes(meminfo.get("SwapTotal", 0)),
        storage=tuple(_storage_devices()) or ("Not detected",),
    )


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except (OSError, PermissionError):
        return ""


def _os_name() -> str:
    values: dict[str, str] = {}
    for line in _read(Path("/etc/os-release")).splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value.strip().strip('"')
    return values.get("PRETTY_NAME") or values.get("NAME") or platform.system()


def _cpu_details() -> tuple[str, int, str]:
    model = "Unknown processor"
    physical_pairs: set[tuple[str, str]] = set()
    current: dict[str, str] = {}
    frequencies: list[float] = []
    for line in _read(Path("/proc/cpuinfo")).splitlines() + [""]:
        if not line:
            if current:
                if current.get("physical id") is not None and current.get("core id") is not None:
                    physical_pairs.add((current["physical id"], current["core id"]))
                try:
                    frequencies.append(float(current.get("cpu MHz", "0")))
                except ValueError:
                    pass
                model = current.get("model name", model)
                current = {}
            continue
        if ":" in line:
            key, value = line.split(":", 1)
            current[key.strip()] = value.strip()
    physical = len(physical_pairs) or os.cpu_count() or 1
    frequency_path = Path("/sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq")
    try:
        ghz = float(_read(frequency_path).strip()) / 1_000_000
    except ValueError:
        ghz = max(frequencies, default=0.0) / 1000
    frequency = f"{ghz:.2f} GHz" if ghz else "Not reported"
    return model, physical, frequency


def _graphics_devices() -> list[str]:
    try:
        completed = subprocess.run(
            ["lspci", "-mm"], capture_output=True, text=True, check=False, timeout=4
        )
        devices = []
        for line in completed.stdout.splitlines():
            if not any(kind in line for kind in ("VGA compatible controller", "3D controller", "Display controller")):
                continue
            fields = shlex.split(line)
            if len(fields) >= 4:
                devices.append(f"{fields[2]} {fields[3]}")
        if devices:
            return list(dict.fromkeys(devices))
    except (OSError, subprocess.TimeoutExpired, ValueError):
        pass

    vendor_names = {"0x10de": "NVIDIA", "0x1002": "AMD", "0x8086": "Intel"}
    devices = []
    for card in Path("/sys/class/drm").glob("card[0-9]"):
        device = card / "device"
        vendor = vendor_names.get(_read(device / "vendor").strip(), "Graphics")
        uevent = _read(device / "uevent")
        driver = next(
            (line.split("=", 1)[1] for line in uevent.splitlines() if line.startswith("DRIVER=")),
            "",
        )
        devices.append(f"{vendor} {driver}".strip())
    return list(dict.fromkeys(devices))


def _storage_devices() -> list[str]:
    devices = []
    for block in Path("/sys/block").glob("*"):
        if block.name.startswith(("loop", "ram", "zram", "fd", "sr", "dm-")):
            continue
        model = _read(block / "device/model").strip() or block.name
        try:
            size = int(_read(block / "size").strip()) * 512
        except ValueError:
            size = 0
        devices.append(f"{model} · {format_bytes(size)}")
    return devices


def _virtualization() -> str:
    try:
        completed = subprocess.run(
            ["systemd-detect-virt"], capture_output=True, text=True, check=False, timeout=3
        )
        value = completed.stdout.strip()
        return value if completed.returncode == 0 and value else "None detected"
    except (OSError, subprocess.TimeoutExpired):
        return "Unknown"
