import hashlib
import hmac
import json

import pytest

from outcomeci_connectors.providers.github import PROVIDER

SECRET = " test-secret with whitespace "
DELIVERY = "72d3162e-cc78-11e3-81ab-4c9367dc0958"


def request(payload=None, event="issues", delivery=DELIVERY, body=None):
    if body is None:
        body = json.dumps(
            payload
            if payload is not None
            else {"action": "opened", "issue": {"number": 7, "title": "Unicode ✓"}}
        ).encode()
    return {
        "x-hub-signature-256": "sha256="
        + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest(),
        "x-github-event": event,
        "x-github-delivery": delivery,
    }, body


def receive(headers, body, **kwargs):
    return PROVIDER.receiver.receive(
        headers,
        body,
        secret=kwargs.get("secret", SECRET),
        events=kwargs.get("events", ("issues",)),
        now=0,
    )


def test_signed_event_preserves_payload_and_normalizes_delivery():
    headers, body = request(delivery=DELIVERY.upper())
    result = receive(headers, body)
    assert result.status == "trigger"
    assert result.event_id == DELIVERY
    assert result.trigger == {
        "event": "issues",
        "delivery_id": DELIVERY,
        "payload": json.loads(body),
    }
    assert receive(headers, body) == result


@pytest.mark.parametrize("signature", [None, "", "sha1=abc", "sha256=bad", "☃"])
def test_missing_or_invalid_signature_rejected(signature):
    headers, body = request()
    if signature is None:
        del headers["x-hub-signature-256"]
    else:
        headers["x-hub-signature-256"] = signature
    assert receive(headers, body).status == "reject"


def test_wrong_secret_and_changed_raw_bytes_rejected():
    headers, body = request()
    assert receive(headers, body, secret="wrong").status == "reject"
    assert receive(headers, body, secret="").status == "reject"
    assert receive(headers, body + b" ").status == "reject"
    assert receive(headers, body, secret=SECRET.strip()).status == "reject"


@pytest.mark.parametrize("body", [b"not json", b"[]", b"null", b'"text"', b"\xff"])
def test_signed_invalid_payload_rejected(body):
    assert receive(*request(body=body)).status == "reject"


@pytest.mark.parametrize("delivery", ["", "invalid", "x" * 200])
def test_invalid_delivery_rejected(delivery):
    assert receive(*request(delivery=delivery)).status == "reject"


def test_ping_is_verified_but_never_starts_a_run():
    headers, body = request({"zen": "Keep it logically awesome."}, event="ping")
    result = receive(headers, body)
    assert result.status == "respond"
    assert result.response == {"ok": True}
    assert receive(headers, body, secret="wrong").status == "reject"


def test_unselected_and_unknown_events_are_ignored_after_verification():
    assert receive(*request(event="push")).status == "ignore"
    assert receive(*request(event="unknown"), events=("unknown",)).status == "ignore"
    assert receive(*request(event="")).status == "reject"
    assert receive(*request(event="push"), secret="wrong").status == "reject"


@pytest.mark.parametrize("event", list(PROVIDER.receiver.events))
def test_all_advertised_events_can_trigger(event):
    assert receive(*request(event=event), events=(event,)).status == "trigger"


def test_github_official_signature_vector_passes_authentication():
    # https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries
    headers, _ = request()
    headers["x-hub-signature-256"] = (
        "sha256=757107ea0eb2509fc211221cce984b8a37570b6d7586c22c46f4379c8b043e17"
    )
    result = receive(headers, b"Hello, World!", secret="It's a Secret to Everybody")
    assert result.reason == "GitHub request body is not JSON"


def test_setup_contract_exposes_webhook_secret_without_changing_auth():
    contract = PROVIDER.contract()
    assert contract["setup"]["credentials"][0]["suggested_path"] == "github/webhook-secret"
    assert set(contract["receiver"]["events"]) == set(PROVIDER.receiver.events)
    assert [auth["kind"] for auth in contract["auth"]["accepts"]] == [
        "token",
        "app_installation",
        "oauth2",
    ]
