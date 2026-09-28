import json

import pytest

from outcomeci_connectors.providers.slack import PROVIDER
from outcomeci_connectors.providers.slack.receiver import signature

SECRET = "signing-secret"
NOW = 1_790_000_000


def request(payload, *, secret=SECRET, sent_at=NOW):
    body = json.dumps(payload).encode()
    headers = {
        "x-slack-request-timestamp": str(sent_at),
        "x-slack-signature": signature(secret, str(sent_at), body),
    }
    return headers, body


def receive(payload, *, events=("mention", "dm"), **signing):
    headers, body = request(payload, **signing)
    return PROVIDER.receiver.receive(headers, body, secret=SECRET, events=events, now=NOW)


def callback(**event):
    return {
        "type": "event_callback",
        "team_id": "T1",
        "event_id": "Ev1",
        "event": {"channel": "C1", "user": "U1", "text": "hi", "ts": "1.1", **event},
    }


def test_the_contract_names_the_events_a_trigger_can_listen_for():
    assert set(PROVIDER.contract()["receiver"]["events"]) == {"mention", "dm"}


def test_url_verification_echoes_the_challenge():
    reception = receive({"type": "url_verification", "challenge": "abc"})

    assert reception.status == "respond"
    assert reception.response == {"challenge": "abc"}


@pytest.mark.parametrize(
    "signing",
    [{"secret": "someone-else"}, {"sent_at": NOW - 301}],
    ids=["wrong secret", "replayed"],
)
def test_unsigned_or_stale_requests_are_rejected(signing):
    assert receive({"type": "url_verification"}, **signing).status == "reject"


def test_a_tampered_body_is_rejected():
    headers, _ = request(callback(type="app_mention"))
    tampered = json.dumps(callback(type="app_mention", text="rm -rf")).encode()

    reception = PROVIDER.receiver.receive(
        headers, tampered, secret=SECRET, events=("mention",), now=NOW
    )

    assert reception.status == "reject"


def test_a_mention_becomes_the_trigger_keyed_by_event_id():
    reception = receive(callback(type="app_mention"))

    assert reception.status == "trigger"
    assert reception.event_id == "Ev1"
    assert reception.trigger == {
        "event": "mention",
        "team": "T1",
        "channel": "C1",
        "user": "U1",
        "text": "hi",
        "ts": "1.1",
        "thread_ts": "1.1",
    }


def test_a_direct_message_is_a_dm():
    reception = receive(callback(type="message", channel_type="im"))

    assert reception.status == "trigger"
    assert reception.trigger["event"] == "dm"


@pytest.mark.parametrize(
    ("event", "events"),
    [
        ({"type": "app_mention", "bot_id": "B1"}, ("mention",)),
        ({"type": "message", "channel_type": "im", "subtype": "message_changed"}, ("dm",)),
        ({"type": "message", "channel_type": "channel"}, ("mention", "dm")),
        ({"type": "message", "channel_type": "im"}, ("mention",)),
        ({"type": "app_mention", "thread_ts": "0.9"}, ("mention",)),
        ({"type": "message", "channel_type": "im", "thread_ts": "0.9"}, ("dm",)),
    ],
    ids=[
        "bot message",
        "edit",
        "channel message",
        "event not listened for",
        "mention in a thread",
        "dm thread reply",
    ],
)
def test_only_top_level_human_messages_start_a_run(event, events):
    assert receive(callback(**event), events=events).status == "ignore"
