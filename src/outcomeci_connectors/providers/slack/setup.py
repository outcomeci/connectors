"""Local, user-owned Slack app setup through the official Slack CLI."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path


class SlackError(RuntimeError):
    pass


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]

PROJECT_RELATIVE = Path(".outcomeci/integrations/slack")


def _manifest(name: str) -> dict[str, object]:
    return {
        "display_information": {
            "name": name,
            "description": "Bring human context into local OutcomeCI workflows.",
            "background_color": "#17131f",
        },
        "features": {
            "app_home": {
                "home_tab_enabled": False,
                "messages_tab_enabled": True,
                "messages_tab_read_only_enabled": False,
            },
            "bot_user": {"display_name": name, "always_online": False},
        },
        "oauth_config": {
            "scopes": {
                "bot": [
                    "channels:history",
                    "channels:read",
                    "chat:write",
                    "groups:history",
                    "groups:read",
                    "im:history",
                    "im:read",
                    "im:write",
                    "reactions:read",
                    "usergroups:read",
                    "users:read",
                    "users:read.email",
                ]
            }
        },
        "settings": {
            "org_deploy_enabled": False,
            "socket_mode_enabled": False,
            "token_rotation_enabled": False,
        },
    }


def _hooks() -> dict[str, object]:
    return {
        "hooks": {
            "get-manifest": "oci integration slack manifest --project .",
        },
        "config": {
            "sdk-managed-connection-enabled": True,
            "watch": {
                "manifest": {"paths": ["manifest.json"]},
            },
        },
    }


def scaffold(workspace: Path, name: str, *, force: bool = False) -> Path:
    project = workspace / PROJECT_RELATIVE
    project.mkdir(parents=True, exist_ok=True)
    slack_dir = project / ".slack"
    slack_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = project / "manifest.json"
    if force or not manifest_path.exists():
        manifest_path.write_text(json.dumps(_manifest(name), indent=2) + "\n", encoding="utf-8")
    managed_files = {
        slack_dir / "hooks.json": json.dumps(_hooks(), indent=2) + "\n",
        slack_dir / ".gitignore": "apps.dev.json\ncache/\noutcomeci-runtime.json\n",
    }
    for path, content in managed_files.items():
        path.write_text(content, encoding="utf-8")
    if force:
        for legacy in (
            project / "app.py",
            project / "pyproject.toml",
            project / "requirements.txt",
        ):
            if legacy.exists():
                legacy.unlink()
    config_path = slack_dir / "config.json"
    if not config_path.exists():
        config_path.write_text(
            json.dumps({"manifest": {"source": "local"}, "project_id": str(uuid.uuid4())}, indent=2)
            + "\n",
            encoding="utf-8",
        )
    return project


def _invoke(
    command: Sequence[str],
    *,
    cwd: Path,
    runner: CommandRunner,
    capture: bool = False,
) -> subprocess.CompletedProcess[str]:
    return runner(
        list(command),
        cwd=cwd,
        text=True,
        check=False,
        capture_output=capture,
    )


def _require_slack() -> str:
    executable = shutil.which("slack")
    if executable is None:
        raise SlackError(
            "Slack CLI is not installed; install it from "
            "https://docs.slack.dev/tools/slack-cli/guides/installing-the-slack-cli-for-mac-and-linux/"
        )
    return executable


def _authorized(slack: str, project: Path, runner: CommandRunner) -> bool:
    result = _invoke(
        [slack, "auth", "list", "--no-color"], cwd=project, runner=runner, capture=True
    )
    return result.returncode == 0 and bool(re.search(r"Team ID:\s*[A-Z0-9]+", result.stdout or ""))


def _expired(result: subprocess.CompletedProcess[str]) -> bool:
    output = f"{result.stdout or ''}\n{result.stderr or ''}".lower()
    return (
        "auth_token_error" in output
        or "token_expired" in output
        or "access token has expired" in output
    )


def _validate(
    slack: str,
    project: Path,
    runner: CommandRunner,
    *,
    app_id: str | None = None,
    team: str | None = None,
) -> subprocess.CompletedProcess[str]:
    command = [slack, "manifest", "validate", "--no-color"]
    if app_id:
        command.extend(["--app", app_id])
    elif team:
        command.extend(["--team", team])
    return _invoke(command, cwd=project, runner=runner, capture=True)


def setup(
    workspace: Path,
    *,
    name: str = "OutcomeCI",
    team: str | None = None,
    channel: str | None = None,
    force: bool = False,
    runner: CommandRunner = subprocess.run,
) -> dict[str, object]:
    """Generate the manifest, create/install the Slack app, and report where
    to sync its credential next. Requires an initialized oci workspace
    (an outcome.yml must already exist) even though this function neither
    reads nor writes it -- that's the signal you're in the right directory."""
    workspace = workspace.resolve()
    workflow = workspace / "outcome.yml"
    if not workflow.is_file():
        raise SlackError(f"{workflow} does not exist; run `oci init --backend filesystem` first")
    slack = _require_slack()
    project = scaffold(workspace, name, force=force)
    if channel:
        (project / "config.json").write_text(
            json.dumps({"default_target": channel.strip()}, indent=2) + "\n",
            encoding="utf-8",
        )

    if not _authorized(slack, project, runner):
        login = _invoke([slack, "login"], cwd=project, runner=runner)
        if login.returncode != 0:
            raise SlackError("Slack CLI login did not complete")
        if not _authorized(slack, project, runner):
            raise SlackError("Slack CLI has no authorized workspace after login")

    app_id = installed_app_id(project, team)
    validate = _validate(slack, project, runner, app_id=app_id, team=team)
    if _expired(validate):
        login = _invoke([slack, "login"], cwd=project, runner=runner)
        if login.returncode != 0:
            raise SlackError("Slack CLI login did not complete")
        validate = _validate(slack, project, runner, app_id=app_id, team=team)
    if validate.returncode != 0 or _expired(validate):
        detail = (validate.stderr or validate.stdout or "unknown Slack CLI error").strip()
        raise SlackError(f"Slack rejected the generated app manifest: {detail}")
    command = [slack, "app", "install"]
    if app_id:
        command.extend(["--app", app_id])
    else:
        command.extend(["--environment", "local"])
        if team:
            command.extend(["--team", team])
    install = _invoke(command, cwd=project, runner=runner)
    if install.returncode != 0:
        raise SlackError("Slack app installation did not complete")
    return {
        "configured": True,
        "project": str(project),
        "next": "oci integration slack sync-credentials --workspace "
        + str(workspace)
        + " --cloud <workspace-id>",
    }


def status(workspace: Path, *, runner: CommandRunner = subprocess.run) -> dict[str, object]:
    workspace = workspace.resolve()
    project = workspace / PROJECT_RELATIVE
    executable = shutil.which("slack")
    authorized = False
    if executable and project.is_dir() and _authorized(executable, project, runner):
        authorized = not _expired(
            _validate(executable, project, runner, app_id=installed_app_id(project))
        )
    return {
        "ready": bool(executable and project.is_dir() and authorized),
        "cli_installed": executable is not None,
        "authorized": authorized,
        "project_created": (project / ".slack/hooks.json").is_file(),
        "project": str(project),
    }


def installed_app_id(project: Path, team: str | None = None) -> str | None:
    """Return one unambiguous installed app, otherwise preserve Slack's selector."""
    path = project / ".slack" / "apps.dev.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    installations = [item for item in value.values() if isinstance(item, dict)]
    if team:
        installations = [
            item
            for item in installations
            if item.get("team_id") == team or item.get("team_domain") == team
        ]
    app_ids = {item.get("app_id") for item in installations if isinstance(item.get("app_id"), str)}
    return next(iter(app_ids)) if len(app_ids) == 1 else None


def manifest(project: Path) -> dict[str, object]:
    path = project.resolve() / "manifest.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SlackError(f"could not read Slack manifest {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SlackError("Slack manifest must be a JSON object")
    return value
