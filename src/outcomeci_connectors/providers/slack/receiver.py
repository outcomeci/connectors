"""Slack Events API requests, turned into workflow triggers.

Slack signs every request with the app's signing secret: `X-Slack-Signature`
is `v0=` plus the HMAC-SHA256 of `v0:<X-Slack-Request-Timestamp>:<body>`.
A request older than five minutes is refused, so a captured one cannot be
replayed later.

Only top-level human messages start a run, a message with files included. A
reply in a thread, including one that mentions the bot, belongs to the
conversation that thread already carries (a workflow's `converse` step reads
it), so it is ignored here, as are bot messages, edits and deletions. A run is
keyed by its message (team, channel and ts), so one message never starts two
runs, even when Slack delivers it both as a mention and as a direct message.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Collection, Mapping
from typing import Any

from ...provider import Receiver, Reception

MAX_AGE_SECONDS = 300
# Subtypes a person's own top-level message can carry.
HUMAN_SUBTYPES = {None, "file_share"}

EVENTS = {
    "mention": "A top-level message that @mentions the app, in a channel it is in.",
    "dm": "A top-level direct message to the app.",
}

# The Slack bot event each trigger event subscribes to, and the scope it needs.
SUBSCRIPTIONS = {
    "mention": ("app_mention", "app_mentions:read"),
    "dm": ("message.im", "im:history"),
}


def signature(secret: str, timestamp: str, body: bytes) -> str:
    """The `X-Slack-Signature` Slack sends for `body` at `timestamp`."""
    base = b"v0:" + timestamp.encode() + b":" + body
    return "v0=" + hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()


def _kind(event: Mapping[str, Any]) -> str | None:
    if event.get("type") == "app_mention":
        return "mention"
    if event.get("type") == "message" and event.get("channel_type") == "im":
        return "dm"
    return None


def receive(
    headers: Mapping[str, str],
    body: bytes,
    *,
    secret: str,
    events: Collection[str],
    now: float,
) -> Reception:
    timestamp = headers.get("x-slack-request-timestamp", "")
    sent = headers.get("x-slack-signature", "")
    if not re.fullmatch(r"[0-9]{1,12}", timestamp):
        return Reception("reject", "missing or malformed Slack request timestamp")
    if abs(now - int(timestamp)) > MAX_AGE_SECONDS:
        return Reception("reject", "Slack request timestamp is outside five minutes")
    secret = secret.strip()
    expected = signature(secret, timestamp, body).encode()
    if not secret or not hmac.compare_digest(sent.encode("utf-8", "replace"), expected):
        return Reception("reject", "Slack signature does not match")
    try:
        payload = json.loads(body)
    except ValueError:
        return Reception("reject", "Slack request body is not JSON")
    if not isinstance(payload, dict):
        return Reception("reject", "Slack request body is not an object")
    if payload.get("type") == "url_verification":
        return Reception(
            "respond", "URL verification", response={"challenge": payload.get("challenge", "")}
        )
    event = payload.get("event")
    event_id = payload.get("event_id")
    if payload.get("type") != "event_callback" or not isinstance(event, dict):
        return Reception("ignore", "not an event callback")
    if not isinstance(event_id, str) or not event_id:
        return Reception("ignore", "event callback without an event_id")
    if event.get("bot_id") or event.get("subtype") not in HUMAN_SUBTYPES:
        return Reception("ignore", "bot message, edit or deletion")
    kind = _kind(event)
    if kind is None or kind not in events:
        return Reception("ignore", "event the workflow does not listen for")
    ts, thread_ts = event.get("ts"), event.get("thread_ts")
    if thread_ts and thread_ts != ts:
        return Reception("ignore", "reply in a thread")
    channel, user, text = event.get("channel"), event.get("user"), event.get("text")
    if not all(isinstance(value, str) and value for value in (channel, user, ts)):
        return Reception("ignore", "event without a channel, user or ts")
    return Reception(
        "trigger",
        kind,
        event_id=f"{payload.get('team_id') or ''}:{channel}:{ts}",
        trigger={
            "event": kind,
            "team": str(payload.get("team_id") or ""),
            "channel": channel,
            "user": user,
            "text": text if isinstance(text, str) else "",
            "ts": ts,
            "thread_ts": ts,
        },
    )


RECEIVER = Receiver(
    receive=receive,
    events=EVENTS,
    description="Slack Events API: signed @mentions and direct messages.",
)
