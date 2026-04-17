from __future__ import annotations


def format_bytes(value: int) -> str:
    size = float(value)
    units = ["B", "KB", "MB", "GB", "TB"]
    for unit in units:
        if size < 1024.0 or unit == units[-1]:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{value} B"


def format_dbfs(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.1f} dBFS"
