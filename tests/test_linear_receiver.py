import hashlib
import hmac
import json

import pytest

from outcomeci_connectors.providers.linear import PROVIDER

SECRET = "lin_wh_test-secret"
NOW = 1_760_000_000.0
ISSUE = "2174add1-f7c8-44e3-bbf3-2d60b5ea8bc9"
ALL = ("issue_created", "issue_state_changed", "comment_added")


def payload(kind="Issue", action="create", **extra):
    value = {
        "action": action,
        "type": kind,
        "data": {
            "id": ISSUE,
            "identifier": "ENG-7",
            "title": "Unicode ✓",
            "updatedAt": "2026-10-06T14:00:00.000Z",
        },
        "url": "https://linear.app/acme/issue/ENG-7",
        "webhookTimestamp": int(NOW * 1000),
        "webhookId": "000042e3-d123-4980-b49f-8e140eef9329",
    }
    value.update(extra)
    return value


def request(value=None, body=None):
    if body is None:
        body = json.dumps(value if value is not None else payload()).encode()
    return {
        "linear-signature": hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest(),
        "linear-event": "Issue",
        "linear-delivery": "234d1a4e-b617-4388-90fe-adc3633d6b72",
    }, body


def receive(headers, body, **kwargs):
    return PROVIDER.receiver.receive(
        headers,
        body,
        secret=kwargs.get("secret", SECRET),
        events=kwargs.get("events", ALL),
        now=kwargs.get("now", NOW),
    )


def test_signed_issue_created_preserves_payload():
    headers, body = request()
    result = receive(headers, body)
    assert result.status == "trigger"
    assert result.event_id == f"issue_created:{ISSUE}"
    assert result.trigger == {"event": "issue_created", "payload": json.loads(body)}


def test_state_change_is_keyed_by_issue_and_update_time():
    value = payload(action="update", updatedFrom={"stateId": "old", "updatedAt": "earlier"})
    result = receive(*request(value))
    assert result.status == "trigger"
    assert result.trigger["event"] == "issue_state_changed"
    assert result.event_id == f"issue_state_changed:{ISSUE}:2026-10-06T14:00:00.000Z"
    later = payload(action="update", updatedFrom={"stateId": "next"})
    later["data"]["updatedAt"] = "2026-10-06T15:00:00.000Z"
    assert receive(*request(later)).event_id != result.event_id


def test_comment_added_triggers():
    result = receive(*request(payload(kind="Comment")))
    assert result.status == "trigger"
    assert result.event_id == f"comment_added:{ISSUE}"


def test_redelivery_with_a_new_timestamp_and_delivery_keeps_the_event_id():
    first = receive(*request())
    headers, body = request(payload(webhookTimestamp=int(NOW * 1000) + 30_000))
    headers["linear-delivery"] = "ffffffff-b617-4388-90fe-adc3633d6b72"
    assert receive(headers, body).event_id == first.event_id


@pytest.mark.parametrize("signature", [None, "", "sha256=abc", "0" * 64, "☃"])
def test_missing_or_forged_signature_rejected(signature):
    headers, body = request()
    if signature is None:
        del headers["linear-signature"]
    else:
        headers["linear-signature"] = signature
    assert receive(headers, body).status == "reject"


def test_wrong_secret_and_tampered_body_rejected():
    headers, body = request()
    assert receive(headers, body, secret="wrong").status == "reject"
    assert receive(headers, body, secret="").status == "reject"
    assert receive(headers, body + b" ").status == "reject"
    assert receive(headers, body.replace(b"ENG-7", b"ENG-8")).status == "reject"


@pytest.mark.parametrize("body", [b"not json", b"[]", b"null", b'"text"', b"\xff"])
def test_signed_invalid_payload_rejected(body):
    assert receive(*request(body=body)).status == "reject"


@pytest.mark.parametrize("timestamp", [None, "1760000000000", 1.5, True])
def test_missing_or_malformed_timestamp_rejected(timestamp):
    value = payload(webhookTimestamp=timestamp)
    assert receive(*request(value)).status == "reject"


@pytest.mark.parametrize("offset", [-61, 61, -3600])
def test_stale_or_future_request_rejected(offset):
    assert receive(*request(), now=NOW + offset).status == "reject"


@pytest.mark.parametrize("offset", [-60, 0, 60])
def test_request_within_a_minute_accepted(offset):
    assert receive(*request(), now=NOW + offset).status == "trigger"


@pytest.mark.parametrize(
    "value",
    [
        payload(action="update", updatedFrom={"title": "Old title"}),
        payload(action="update"),
        payload(action="remove"),
        payload(kind="Comment", action="update"),
        payload(kind="Project"),
        payload(kind="IssueLabel"),
    ],
)
def test_unsupported_events_are_ignored(value):
    assert receive(*request(value)).status == "ignore"


def test_unselected_events_are_ignored_after_verification():
    headers, body = request()
    assert receive(headers, body, events=("comment_added",)).status == "ignore"
    assert receive(headers, body, events=("comment_added",), secret="wrong").status == "reject"


def test_event_without_ids_is_ignored():
    assert receive(*request(payload(data={"title": "no id"}))).status == "ignore"
    value = payload(action="update", updatedFrom={"stateId": "old"})
    del value["data"]["updatedAt"]
    assert receive(*request(value)).status == "ignore"


@pytest.mark.parametrize("event", list(PROVIDER.receiver.events))
def test_all_advertised_events_can_trigger(event):
    value = {
        "issue_created": payload(),
        "issue_state_changed": payload(action="update", updatedFrom={"stateId": "s"}),
        "comment_added": payload(kind="Comment"),
    }[event]
    assert receive(*request(value), events=(event,)).status == "trigger"
