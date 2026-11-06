from __future__ import annotations


def format_bytes(value: float | int, precision: int = 1) -> str:
    value = max(0.0, float(value))
    units = ("B", "KB", "MB", "GB", "TB", "PB")
    unit = units[0]
    for unit in units:
        if value < 1024.0 or unit == units[-1]:
            break
        value /= 1024.0
    decimals = 0 if unit == "B" else precision
    return f"{value:.{decimals}f} {unit}"


def format_rate(value: float | int) -> str:
    return f"{format_bytes(value)}/s"


def format_percent(value: float) -> str:
    if value < 0.05:
        return "0%"
    if value < 10:
        return f"{value:.1f}%"
    return f"{value:.0f}%"


def format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)
    if days:
        return f"{days}d {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def format_uptime(seconds: float) -> str:
    seconds = max(0, int(seconds))
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    clock = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{days}d {clock}" if days else clock


def ellipsize_middle(value: str, maximum: int = 100) -> str:
    if len(value) <= maximum:
        return value
    side = max(1, (maximum - 1) // 2)
    return f"{value[:side]}…{value[-side:]}"
