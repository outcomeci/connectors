"""The Slack Web API operations a workflow can be granted with `uses: slack`."""

from __future__ import annotations

from typing import Any

from ...provider import Grantable, Operation, Provider, Watcher
from .receiver import RECEIVER

CHANNEL = Grantable(field="channel")
THREAD = Grantable(field="thread_ts")


def reaction_matches(output: dict[str, Any], emoji: str, *, by: str | None = None) -> bool:
    """Whether a `reactions` result carries an `emoji` reaction, from `by` when given."""
    for item in output.get("reactions") or []:
        if not isinstance(item, dict) or item.get("name") != emoji or item.get("count", 0) < 1:
            continue
        if by is None or by in (item.get("users") or []):
            return True
    return False


def human_replies(
    output: dict[str, Any], *, after: str | None = None, by: str | None = None
) -> list[dict[str, str]]:
    """Human replies in a `thread` result, oldest first, skipping the root and bots.

    `after` is a message ts; only replies posted after it are returned, so a
    caller that remembers the last reply it read sees each reply once. `by`
    keeps only one user's replies.
    """
    replies = []
    for item in (output.get("messages") or [])[1:]:
        if not isinstance(item, dict) or item.get("bot_id") or item.get("subtype"):
            continue
        text, ts = item.get("text"), item.get("ts")
        if not isinstance(text, str) or not text.strip() or not isinstance(ts, str):
            continue
        if after is not None and float(ts) <= float(after):
            continue
        if by is not None and item.get("user") != by:
            continue
        replies.append({"ts": ts, "text": text, "user": str(item.get("user") or "")})
    return sorted(replies, key=lambda reply: float(reply["ts"]))


PROVIDER = Provider(
    name="slack",
    base_url="https://slack.com",
    operations={
        "post": Operation(
            description=(
                "Post one message to a Slack channel, or reply in a thread with thread_ts. "
                "Returns the posted message's channel and ts, and the thread's root "
                "thread_ts when it was posted in a thread."
            ),
            method="POST",
            path="/api/chat.postMessage",
            input={
                "type": "object",
                "required": ["channel", "text"],
                "properties": {
                    "channel": {"type": "string", "minLength": 1},
                    "text": {"type": "string", "minLength": 1, "maxLength": 4000},
                    "thread_ts": {"type": "string", "minLength": 1},
                },
                "additionalProperties": False,
            },
            body="{{ input }}",
            expose={
                "channel": "body.channel",
                "ts": "body.ts",
                "thread_ts": "body.message.thread_ts",
            },
            side_effect="create",
            grantable={"channel": CHANNEL, "thread_ts": THREAD},
        ),
        "thread": Operation(
            description="Read a message's thread: the root message and every reply.",
            method="GET",
            path="/api/conversations.replies",
            input={
                "type": "object",
                "required": ["channel", "ts"],
                "properties": {
                    "channel": {"type": "string", "minLength": 1},
                    "ts": {"type": "string", "minLength": 1},
                },
                "additionalProperties": False,
            },
            query={"channel": "{{ input.channel }}", "ts": "{{ input.ts }}", "limit": 200},
            expose={"messages": "body.messages"},
            grantable={"channel": CHANNEL},
        ),
        "reactions": Operation(
            description="Read the reactions on one message.",
            method="GET",
            path="/api/reactions.get",
            input={
                "type": "object",
                "required": ["channel", "ts"],
                "properties": {
                    "channel": {"type": "string", "minLength": 1},
                    "ts": {"type": "string", "minLength": 1},
                },
                "additionalProperties": False,
            },
            query={"channel": "{{ input.channel }}", "timestamp": "{{ input.ts }}"},
            expose={"reactions": "body.message.reactions"},
            grantable={"channel": CHANNEL},
        ),
    },
    watchers={
        "reaction": Watcher(
            operation="reactions",
            match=reaction_matches,
            description="Wait for an emoji reaction on one message.",
            respond="post",
            thread_field="thread_ts",
        ),
        "reply": Watcher(
            operation="thread",
            match=human_replies,
            description="Wait for human replies in one message's thread.",
            respond="post",
            thread_field="thread_ts",
        ),
    },
    receiver=RECEIVER,
)
