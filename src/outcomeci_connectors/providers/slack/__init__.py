"""The Slack Web API operations a workflow can be granted with `uses: slack`."""

from __future__ import annotations

from typing import Any

from ...provider import Download, Grantable, OAuth2, Operation, Provider, Token, Watcher
from .messages import HUMAN_SUBTYPES, files
from .receiver import RECEIVER

CHANNEL = Grantable(field="channel")
THREAD = Grantable(field="thread_ts")
# A file is readable when it is shared in the granted conversation.
SHARED_IN = Grantable(response_in=("body.file.channels", "body.file.groups", "body.file.ims"))


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
) -> list[dict[str, Any]]:
    """Human replies in a `thread` result, oldest first, skipping the root and bots.

    `after` is a message ts; only replies posted after it are returned, so a
    caller that remembers the last reply it read sees each reply once. `by`
    keeps only one user's replies. A reply is its text, its files, or both.
    """
    replies = []
    for item in (output.get("messages") or [])[1:]:
        if (
            not isinstance(item, dict)
            or item.get("bot_id")
            or item.get("subtype") not in HUMAN_SUBTYPES
        ):
            continue
        text, ts, attached = item.get("text"), item.get("ts"), files(item)
        text = text if isinstance(text, str) else ""
        if not isinstance(ts, str) or not (text.strip() or attached):
            continue
        if after is not None and float(ts) <= float(after):
            continue
        if by is not None and item.get("user") != by:
            continue
        replies.append(
            {"ts": ts, "text": text, "user": str(item.get("user") or ""), "files": attached}
        )
    return sorted(replies, key=lambda reply: float(reply["ts"]))


# A bot token (xoxb-) is sent as a bearer token. An app with token rotation
# turned on holds a refresh token instead: it expires its access tokens after
# 12 hours, and each refresh returns a new refresh token and revokes the one it
# used. Slack prefers the client id and secret over HTTP Basic.
AUTH = (
    Token(description="A Slack bot token (xoxb-), sent as a bearer token."),
    OAuth2(
        token_url="https://slack.com/api/oauth.v2.access",
        grant_types=("refresh_token",),
        client_auth="basic",
        rotates_refresh_token=True,
        description=(
            "A Slack app with token rotation: its client id and secret and a refresh "
            "token, exchanged for a 12-hour bot token."
        ),
    ),
)

PROVIDER = Provider(
    name="slack",
    base_url="https://slack.com",
    auth=AUTH,
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
        "file": Operation(
            description=(
                "Open one file shared in the granted conversation, such as a screenshot "
                "attached to a message: returns its name, type and size, and `file.path`, "
                "a local copy to open. Messages list their files by id."
            ),
            method="GET",
            path="/api/files.info",
            input={
                "type": "object",
                "required": ["file"],
                "properties": {"file": {"type": "string", "pattern": "^F[A-Z0-9]+$"}},
                "additionalProperties": False,
            },
            query={"file": "{{ input.file }}"},
            expose={
                "name": "body.file.name",
                "mimetype": "body.file.mimetype",
                "size": "body.file.size",
            },
            grantable={"channel": SHARED_IN},
            # Saved with the run's artifacts, which hold up to 2 MiB a file.
            download=Download(
                url="body.file.url_private_download",
                hosts=("files.slack.com",),
                name="body.file.name",
                content_type="body.file.mimetype",
                max_bytes=2 * 1024 * 1024,
            ),
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
            attachment="file",
        ),
    },
    receiver=RECEIVER,
)
