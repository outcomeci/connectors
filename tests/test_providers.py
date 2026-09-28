from __future__ import annotations

from importlib.metadata import entry_points

import pytest

from outcomeci_connectors.provider import (
    CONTRACT_VERSION,
    Grantable,
    Operation,
    Provider,
    Watcher,
)
from outcomeci_connectors.providers import github, slack


def test_built_in_providers_are_registered_as_entry_points():
    registered = {item.name: item.load() for item in entry_points(group="outcomeci.connectors")}
    assert registered["slack"] is slack.PROVIDER
    assert registered["github"] is github.PROVIDER


def test_slack_contract_carries_the_first_built_ins():
    contract = slack.PROVIDER.contract()
    assert contract["schema_version"] == CONTRACT_VERSION
    assert sorted(contract["operations"]) == ["post", "reactions", "thread"]
    post = contract["operations"]["post"]
    assert post["request"] == {
        "method": "POST",
        "path": "/api/chat.postMessage",
        "body": "{{ input }}",
    }
    assert post["grantable"] == {
        "channel": {"field": "channel"},
        "thread_ts": {"field": "thread_ts"},
    }
    assert post["response"]["expose"] == {
        "channel": "body.channel",
        "ts": "body.ts",
        "thread_ts": "body.message.thread_ts",
    }
    assert contract["watchers"]["reaction"]["operation"] == "reactions"
    assert contract["watchers"]["reply"]["operation"] == "thread"
    assert contract["watchers"]["reply"]["respond"] == "post"
    assert contract["watchers"]["reply"]["thread_field"] == "thread_ts"
    assert contract["watchers"]["reaction"]["respond"] == "post"


def test_github_read_and_write_are_request_operations_scoped_by_repo():
    operations = github.PROVIDER.contract()["operations"]
    assert operations["read"]["request"] == {"methods": ["GET"]}
    assert operations["write"]["request"] == {"methods": ["GET", "PATCH", "POST", "PUT"]}
    assert operations["write"]["grantable"]["repo"] == {
        "path_prefix": "/repos/{owner}/{name}",
        "value_fields": ["owner", "name"],
    }


def test_digest_changes_with_the_contract():
    assert slack.PROVIDER.digest() == slack.PROVIDER.digest()
    assert slack.PROVIDER.digest() != github.PROVIDER.digest()


def test_reaction_watcher_matches_the_emoji_only():
    output = {"reactions": [{"name": "eyes", "count": 2}, {"name": "+1", "count": 1}]}
    assert slack.reaction_matches(output, "+1")
    assert not slack.reaction_matches(output, "tada")
    assert not slack.reaction_matches({"reactions": None}, "+1")


def test_reply_watcher_skips_the_root_bots_and_already_read_replies():
    output = {
        "messages": [
            {"ts": "1.0", "text": "plan", "bot_id": "B1"},
            {"ts": "2.0", "text": "why?", "user": "U1"},
            {"ts": "3.0", "text": "answer", "bot_id": "B1"},
            {"ts": "4.0", "text": "", "user": "U1"},
            {"ts": "5.0", "text": "joined", "subtype": "channel_join"},
            {"ts": "6.0", "text": "go ahead", "user": "U1"},
        ]
    }
    assert [reply["text"] for reply in slack.human_replies(output)] == ["why?", "go ahead"]
    assert [reply["ts"] for reply in slack.human_replies(output, after="2.0")] == ["6.0"]


def test_operations_are_either_fixed_or_requests():
    with pytest.raises(ValueError):
        Operation(description="x", method="GET")
    with pytest.raises(ValueError):
        Operation(description="x", method="GET", path="/x", methods=("GET",))
    with pytest.raises(ValueError):
        Grantable()
    assert (
        Provider(name="p", base_url="https://p.test", operations={}).contract()["operations"] == {}
    )


def test_a_watcher_must_read_a_declared_operation():
    with pytest.raises(ValueError, match="unknown operation"):
        Provider(
            name="p",
            base_url="https://p.test",
            operations={},
            watchers={"reaction": Watcher(operation="reactions", match=lambda output: True)},
        )


def _denied(method: str, path: str) -> bool:
    import re

    for rule in github.PROVIDER.contract()["operations"]["write"]["deny"]:
        if (not rule["methods"] or method in rule["methods"]) and re.search(rule["path"], path):
            return True
    return False


@pytest.mark.parametrize(
    ("method", "path", "denied"),
    [
        ("POST", "/repos/o/r/git/refs", False),
        ("PUT", "/repos/o/r/contents/src/app.py", False),
        ("POST", "/repos/o/r/pulls", False),
        ("PATCH", "/repos/o/r/pulls/7", False),
        ("GET", "/repos/o/r", False),
        ("PATCH", "/repos/o/r", True),
        ("POST", "/repos/o/r/transfer", True),
        ("PUT", "/repos/o/r/collaborators/eve", True),
        ("POST", "/repos/o/r/hooks", True),
        ("PUT", "/repos/o/r/pulls/7/merge", True),
        ("POST", "/repos/o/r/merges", True),
        ("PATCH", "/repos/o/r/git/refs/heads/main", True),
        ("PUT", "/repos/o/r/branches/main/protection", True),
        ("PUT", "/repos/o/r/actions/secrets/TOKEN", True),
        ("POST", "/user/repos", True),
        ("POST", "/orgs/o/repos", True),
    ],
)
def test_github_write_denies_administration_and_merging(method, path, denied):
    assert _denied(method, path) is denied


def test_watchers_can_require_one_user():
    reactions = {"reactions": [{"name": "+1", "count": 1, "users": ["U2"]}]}
    assert slack.reaction_matches(reactions, "+1")
    assert slack.reaction_matches(reactions, "+1", by="U2")
    assert not slack.reaction_matches(reactions, "+1", by="U1")
    thread = {"messages": [{"ts": "1.0"}, {"ts": "2.0", "text": "go", "user": "U2"}]}
    assert slack.human_replies(thread, by="U1") == []
    assert slack.human_replies(thread, by="U2")[0]["text"] == "go"
