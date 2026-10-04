"""Signed GitHub webhooks. The runtime owns Vault access and deduplication.

GitHub signs raw body bytes, not delivery/event headers or a timestamp.
Delivery IDs deduplicate normal redeliveries, not captured requests with changed
headers. A secret must be configured on the GitHub App or repository webhook.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Collection, Mapping

from ..provider import Receiver, Reception

EVENTS = {
    "push": "Commits pushed to a repository.",
    "pull_request": "Pull request activity, including opened, synchronized and closed.",
    "pull_request_review": "Pull request review activity.",
    "pull_request_review_comment": "Comments on a pull request diff.",
    "issues": "Issue activity, including opened, edited and closed.",
    "issue_comment": "Comments on an issue or pull request.",
    "check_run": "Check run activity.",
    "check_suite": "Check suite activity.",
    "workflow_run": "GitHub Actions workflow run activity.",
    "release": "Release activity.",
}


def receive(
    headers: Mapping[str, str],
    body: bytes,
    *,
    secret: str,
    events: Collection[str],
    now: float,
) -> Reception:
    sent = headers.get("x-hub-signature-256", "")
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not secret or not hmac.compare_digest(sent.encode("utf-8", "replace"), expected.encode()):
        return Reception("reject", "GitHub signature does not match")
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return Reception("reject", "GitHub request body is not JSON")
    if not isinstance(payload, dict):
        return Reception("reject", "GitHub request body is not an object")
    event = headers.get("x-github-event", "")
    delivery = headers.get("x-github-delivery", "")
    if not re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", delivery):
        return Reception("reject", "missing or malformed GitHub delivery ID")
    if not event:
        return Reception("reject", "missing GitHub event")
    if event == "ping":
        return Reception("respond", "GitHub webhook ping", response={"ok": True})
    if event not in EVENTS or event not in events:
        return Reception("ignore", "event the workflow does not listen for")
    return Reception(
        "trigger",
        event,
        event_id=delivery.lower(),
        trigger={"event": event, "delivery_id": delivery.lower(), "payload": payload},
    )


RECEIVER = Receiver(
    receive=receive,
    events=EVENTS,
    description="GitHub webhooks verified with HMAC-SHA256; all actions of selected events.",
)
