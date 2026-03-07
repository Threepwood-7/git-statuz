from __future__ import annotations

from pathlib import Path
from typing import cast

SETTINGS_RECENT_PATHS_KEY = "prefs/recent_paths"
MAX_RECENT_PATHS = 10


def update_recent_paths(
    paths: list[str], new_path: str, limit: int = MAX_RECENT_PATHS
) -> list[str]:
    normalized_new = str(Path(new_path).resolve())
    deduped = [normalized_new]
    for existing in paths:
        normalized_existing = str(Path(existing).resolve())
        if normalized_existing not in deduped:
            deduped.append(normalized_existing)
    return deduped[:limit]


def load_recent_paths(raw_value: object, limit: int = MAX_RECENT_PATHS) -> list[str]:
    if isinstance(raw_value, str):
        raw_paths = [raw_value] if raw_value else []
    elif isinstance(raw_value, list):
        raw_paths: list[str] = []
        for item in cast("list[object]", raw_value):
            as_text = str(item)
            if as_text:
                raw_paths.append(as_text)
    else:
        raw_paths = []

    unique_paths: list[str] = []
    for item in raw_paths:
        normalized = str(Path(item).resolve())
        if normalized not in unique_paths:
            unique_paths.append(normalized)
    return unique_paths[:limit]


def drop_recent_path(paths: list[str], path: str) -> list[str]:
    normalized = str(Path(path).resolve())
    return [entry for entry in paths if entry != normalized]
