"""Signed Linear webhooks. The runtime owns Vault access and deduplication.

Linear signs the raw body: `Linear-Signature` is the hex HMAC-SHA256 of it
with the webhook's signing secret. The body carries `webhookTimestamp`, in
milliseconds, and a request more than a minute from now is refused, so a
captured one cannot be replayed later. Linear has no URL handshake.

The `Linear-Delivery` header is not signed, so the event id comes from the
signed body: the created issue or comment, or the issue and the `updatedAt` of
its state change. A redelivery of one change never starts two runs.
https://linear.app/developers/webhooks
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Collection, Mapping
from typing import Any

from ...provider import Receiver, Reception

MAX_AGE_SECONDS = 60

EVENTS = {
    "issue_created": "An issue was created.",
    "issue_state_changed": "An issue moved to another workflow state.",
    "comment_added": "A comment was added to an issue.",
}


def signature(secret: str, body: bytes) -> str:
    """The `Linear-Signature` Linear sends for `body`."""
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _kind(payload: Mapping[str, Any]) -> str | None:
    kind, action = payload.get("type"), payload.get("action")
    if kind == "Issue" and action == "create":
        return "issue_created"
    updated = payload.get("updatedFrom")
    if kind == "Issue" and action == "update" and isinstance(updated, dict):
        return "issue_state_changed" if "stateId" in updated else None
    if kind == "Comment" and action == "create":
        return "comment_added"
    return None


def receive(
    headers: Mapping[str, str],
    body: bytes,
    *,
    secret: str,
    events: Collection[str],
    now: float,
) -> Reception:
    sent = headers.get("linear-signature", "")
    expected = signature(secret, body)
    if not secret or not hmac.compare_digest(sent.encode("utf-8", "replace"), expected.encode()):
        return Reception("reject", "Linear signature does not match")
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return Reception("reject", "Linear request body is not JSON")
    if not isinstance(payload, dict):
        return Reception("reject", "Linear request body is not an object")
    timestamp = payload.get("webhookTimestamp")
    if type(timestamp) is not int:
        return Reception("reject", "missing or malformed Linear webhook timestamp")
    if abs(now - timestamp / 1000) > MAX_AGE_SECONDS:
        return Reception("reject", "Linear webhook timestamp is outside one minute")
    kind = _kind(payload)
    if kind is None or kind not in events:
        return Reception("ignore", "event the workflow does not listen for")
    data = payload.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("id"), str) or not data["id"]:
        return Reception("ignore", "event without an entity id")
    event_id = f"{kind}:{data['id']}"
    if kind == "issue_state_changed":
        updated_at = data.get("updatedAt")
        if not isinstance(updated_at, str) or not updated_at:
            return Reception("ignore", "state change without updatedAt")
        event_id += f":{updated_at}"
    return Reception(
        "trigger", kind, event_id=event_id, trigger={"event": kind, "payload": payload}
    )


RECEIVER = Receiver(
    receive=receive,
    events=EVENTS,
    description=(
        "Linear webhooks verified with HMAC-SHA256 and a one-minute timestamp: "
        "issues created, issue state changes and comments added."
    ),
)
