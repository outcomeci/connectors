from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from outcomeci_connectors.providers.slack.setup import (
    SlackError,
    manifest,
    scaffold,
    setup,
    status,
)

URL = "https://example.com/v1/webhooks/route/token"


class FakeSlack:
    def __init__(self, *, initially_authorized: bool = True, expired: bool = False) -> None:
        self.authorized = initially_authorized
        self.expired = expired
        self.commands: list[tuple[list[str], Path]] = []

    def __call__(self, command, *, cwd, text, check, capture_output=False):
        self.commands.append((list(command), Path(cwd)))
        if command[1:3] == ["auth", "list"]:
            stdout = "local (Team ID: T0123456)\n" if self.authorized else ""
            return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")
        if command[1:] == ["login"]:
            self.authorized = True
            self.expired = False
        if command[1:3] == ["manifest", "validate"] and self.expired:
            return subprocess.CompletedProcess(
                command, 0, stdout="auth_token_error: token_expired", stderr=""
            )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")


def test_scaffold_writes_a_manifest_for_the_webhook_trigger(tmp_path: Path) -> None:
    project = scaffold(tmp_path, "Acme Outcomes", request_url=URL)
    value = manifest(project)
    assert value["display_information"]["name"] == "Acme Outcomes"
    assert value["settings"]["socket_mode_enabled"] is False
    assert value["settings"]["event_subscriptions"] == {
        "request_url": URL,
        "bot_events": ["app_mention", "message.im"],
    }
    assert value["oauth_config"]["scopes"]["bot"] == [
        "app_mentions:read",
        "channels:history",
        "chat:write",
        "files:read",
        "groups:history",
        "im:history",
        "mpim:history",
        "reactions:read",
    ]
    assert value["features"]["app_home"]["messages_tab_enabled"] is True
    assert "slash_commands" not in value["features"]
    hooks = json.loads((project / ".slack/hooks.json").read_text())
    assert hooks == {"hooks": {"get-manifest": "oci integration slack manifest --project ."}}


def test_a_mention_only_trigger_subscribes_to_mentions_only(tmp_path: Path) -> None:
    value = manifest(scaffold(tmp_path, "Acme", request_url=URL, events=["mention"]))

    assert value["settings"]["event_subscriptions"]["bot_events"] == ["app_mention"]
    assert value["features"]["app_home"]["messages_tab_enabled"] is False


@pytest.mark.parametrize(
    ("request_url", "events", "message"),
    [
        ("http://example.com/hook", ["dm"], "https webhook URL"),
        (URL, ["reaction"], "unknown: reaction"),
        (URL, [], "must be some of"),
    ],
)
def test_scaffold_refuses_an_unusable_trigger(tmp_path: Path, request_url, events, message):
    with pytest.raises(SlackError, match=message):
        scaffold(tmp_path, "Acme", request_url=request_url, events=events)


def test_setup_first_creates_the_app_then_subscribes_it(tmp_path: Path) -> None:
    project = scaffold(tmp_path, "First")
    assert "event_subscriptions" not in manifest(project)["settings"]

    scaffold(tmp_path, "Second", request_url=URL)

    value = manifest(project)
    assert value["display_information"]["name"] == "Second"
    assert value["settings"]["event_subscriptions"]["request_url"] == URL


def test_setup_logs_in_when_needed_and_installs_app(tmp_path: Path, monkeypatch) -> None:
    fake = FakeSlack(initially_authorized=False)
    monkeypatch.setattr(
        "outcomeci_connectors.providers.slack.setup.shutil.which", lambda _: "/usr/local/bin/slack"
    )
    result = setup(tmp_path, request_url=URL, name="Acme Outcomes", team="T0123456", runner=fake)
    commands = [command for command, _ in fake.commands]
    assert ["/usr/local/bin/slack", "login"] in commands
    assert [
        "/usr/local/bin/slack",
        "manifest",
        "validate",
        "--no-color",
        "--team",
        "T0123456",
    ] in commands
    assert [
        "/usr/local/bin/slack",
        "app",
        "install",
        "--environment",
        "local",
        "--team",
        "T0123456",
    ] in commands
    assert result["configured"] is True
    assert result["subscribed"] == URL
    assert result["next"] == []


def test_setup_without_a_request_url_says_what_comes_next(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "outcomeci_connectors.providers.slack.setup.shutil.which", lambda _: "/usr/bin/slack"
    )

    result = setup(tmp_path, runner=FakeSlack())

    assert result["subscribed"] is None
    assert "Signing Secret" in result["next"][1]
    assert "--request-url" in result["next"][2]


def test_setup_skips_login_for_authorized_workspace(tmp_path: Path, monkeypatch) -> None:
    fake = FakeSlack()
    monkeypatch.setattr(
        "outcomeci_connectors.providers.slack.setup.shutil.which", lambda _: "/usr/bin/slack"
    )
    setup(tmp_path, request_url=URL, runner=fake)
    assert ["/usr/bin/slack", "login"] not in [command for command, _ in fake.commands]


def test_setup_targets_unambiguous_existing_app(tmp_path: Path, monkeypatch) -> None:
    project = scaffold(tmp_path, "Acme", request_url=URL)
    apps = project / ".slack/apps.dev.json"
    apps.parent.mkdir(parents=True, exist_ok=True)
    apps.write_text('{"T1":{"app_id":"A1","team_id":"T1"}}')
    fake = FakeSlack()
    monkeypatch.setattr(
        "outcomeci_connectors.providers.slack.setup.shutil.which", lambda _: "/usr/bin/slack"
    )
    setup(tmp_path, request_url=URL, name="Acme", runner=fake)
    commands = [command for command, _ in fake.commands]
    assert ["/usr/bin/slack", "manifest", "validate", "--no-color", "--app", "A1"] in commands
    assert ["/usr/bin/slack", "app", "install", "--app", "A1"] in commands


def test_setup_reauthenticates_an_expired_slack_session(tmp_path: Path, monkeypatch) -> None:
    fake = FakeSlack(expired=True)
    monkeypatch.setattr(
        "outcomeci_connectors.providers.slack.setup.shutil.which", lambda _: "/usr/bin/slack"
    )
    setup(tmp_path, request_url=URL, runner=fake)
    assert ["/usr/bin/slack", "login"] in [command for command, _ in fake.commands]


def test_status_reports_ready_configuration(tmp_path: Path, monkeypatch) -> None:
    scaffold(tmp_path, "OutcomeCI", request_url=URL)
    monkeypatch.setattr(
        "outcomeci_connectors.providers.slack.setup.shutil.which", lambda _: "/usr/bin/slack"
    )
    assert status(tmp_path, runner=FakeSlack())["ready"] is True


def test_setup_requires_slack_cli(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("outcomeci_connectors.providers.slack.setup.shutil.which", lambda _: None)
    with pytest.raises(SlackError, match="Slack CLI is not installed"):
        setup(tmp_path, request_url=URL)
