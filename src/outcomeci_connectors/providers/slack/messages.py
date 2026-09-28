"""What a Slack message carries that both a trigger and a reply read."""

from __future__ import annotations

from typing import Any

# A person's own message may carry files; these subtypes are still theirs.
HUMAN_SUBTYPES = {None, "file_share"}


def files(message: dict[str, Any]) -> list[dict[str, Any]]:
    """The files a message carries: id, name, type and size, never a URL."""
    found = []
    for item in message.get("files") or []:
        if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"]:
            found.append(
                {
                    "id": item["id"],
                    "name": str(item.get("name") or item["id"]),
                    "mimetype": str(item.get("mimetype") or ""),
                    "size": item.get("size") if isinstance(item.get("size"), int) else None,
                }
            )
    return found
