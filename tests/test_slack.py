from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from outcomeci_connectors.slack import (
    SlackError,
    manifest,
    scaffold,
    setup,
    status,
)

MINIMAL_WORKFLOW = """apiVersion: outcomeci.com/v1alpha1
kind: OutcomeWorkflow
metadata:
  name: default
spec: {}
"""


def _init_workflow(root: Path) -> None:
    (root / "outcome.yml").write_text(MINIMAL_WORKFLOW, encoding="utf-8")


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


def test_scaffold_writes_on_demand_slack_project(tmp_path: Path) -> None:
    project = scaffold(tmp_path, "Acme Outcomes")
    value = manifest(project)
    assert value["display_information"]["name"] == "Acme Outcomes"
    assert value["settings"]["socket_mode_enabled"] is False
    assert value["features"]["app_home"]["messages_tab_enabled"] is True
    assert "slash_commands" not in value["features"]
    assert "commands" not in value["oauth_config"]["scopes"]["bot"]
    assert "event_subscriptions" not in value["settings"]
    assert not (project / "app.py").exists()
    hooks = json.loads((project / ".slack/hooks.json").read_text())
    assert hooks["hooks"]["get-manifest"] == "oci integration slack manifest --project ."
    assert "start" not in hooks["hooks"]


def test_scaffold_preserves_existing_manifest_without_force(tmp_path: Path) -> None:
    project = scaffold(tmp_path, "First")
    scaffold(tmp_path, "Second")
    assert manifest(project)["display_information"]["name"] == "First"
    scaffold(tmp_path, "Second", force=True)
    assert manifest(project)["display_information"]["name"] == "Second"


def test_setup_logs_in_when_needed_and_installs_app(tmp_path: Path, monkeypatch) -> None:
    _init_workflow(tmp_path)
    fake = FakeSlack(initially_authorized=False)
    monkeypatch.setattr("outcomeci_connectors.slack.shutil.which", lambda _: "/usr/local/bin/slack")
    result = setup(tmp_path, name="Acme Outcomes", team="T0123456", channel="C0123456", runner=fake)
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
    assert (
        json.loads((tmp_path / ".outcomeci/integrations/slack/config.json").read_text())[
            "default_target"
        ]
        == "C0123456"
    )


def test_setup_skips_login_for_authorized_workspace(tmp_path: Path, monkeypatch) -> None:
    _init_workflow(tmp_path)
    fake = FakeSlack()
    monkeypatch.setattr("outcomeci_connectors.slack.shutil.which", lambda _: "/usr/bin/slack")
    setup(tmp_path, runner=fake)
    assert ["/usr/bin/slack", "login"] not in [command for command, _ in fake.commands]


def test_setup_targets_unambiguous_existing_app(tmp_path: Path, monkeypatch) -> None:
    _init_workflow(tmp_path)
    project = scaffold(tmp_path, "Acme")
    apps = project / ".slack/apps.dev.json"
    apps.parent.mkdir(parents=True, exist_ok=True)
    apps.write_text('{"T1":{"app_id":"A1","team_id":"T1"}}')
    fake = FakeSlack()
    monkeypatch.setattr("outcomeci_connectors.slack.shutil.which", lambda _: "/usr/bin/slack")
    setup(tmp_path, name="Acme", force=True, runner=fake)
    commands = [command for command, _ in fake.commands]
    assert ["/usr/bin/slack", "manifest", "validate", "--no-color", "--app", "A1"] in commands
    assert ["/usr/bin/slack", "app", "install", "--app", "A1"] in commands


def test_setup_reauthenticates_an_expired_slack_session(tmp_path: Path, monkeypatch) -> None:
    _init_workflow(tmp_path)
    fake = FakeSlack(expired=True)
    monkeypatch.setattr("outcomeci_connectors.slack.shutil.which", lambda _: "/usr/bin/slack")
    setup(tmp_path, runner=fake)
    assert ["/usr/bin/slack", "login"] in [command for command, _ in fake.commands]


def test_status_reports_ready_configuration(tmp_path: Path, monkeypatch) -> None:
    _init_workflow(tmp_path)
    scaffold(tmp_path, "OutcomeCI")
    monkeypatch.setattr("outcomeci_connectors.slack.shutil.which", lambda _: "/usr/bin/slack")
    assert status(tmp_path, runner=FakeSlack())["ready"] is True


def test_setup_requires_slack_cli(tmp_path: Path, monkeypatch) -> None:
    _init_workflow(tmp_path)
    monkeypatch.setattr("outcomeci_connectors.slack.shutil.which", lambda _: None)
    with pytest.raises(SlackError, match="Slack CLI is not installed"):
        setup(tmp_path)
