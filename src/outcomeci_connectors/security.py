"""Small filesystem-safety helpers shared by connectors."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def atomic_write_text(path: Path, text: str, *, mode: int | None = None) -> None:
    """Write text to `path` so readers only ever see a complete write.

    Writes to a sibling temp file, optionally chmods it (before the rename,
    so the final file never has a window at the default permissions), then
    renames it into place -- a rename is atomic within the same filesystem,
    unlike an in-place write.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    if mode is not None:
        temporary.chmod(mode)
    temporary.replace(path)


def atomic_write_json(
    path: Path, value: Any, *, sort_keys: bool = True, mode: int | None = None
) -> None:
    atomic_write_text(path, json.dumps(value, indent=2, sort_keys=sort_keys) + "\n", mode=mode)
