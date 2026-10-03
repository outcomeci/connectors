"""The Slack app behind a workflow's Slack trigger, set up through the Slack CLI.

The generated manifest asks for exactly what the provider uses: the scopes of
the `post`, `thread` and `reactions` operations, and an event subscription to
the workflow's webhook URL for each event its trigger listens for.

Setup takes two passes, because Slack verifies the request URL when the
manifest is applied and the webhook can only answer once the app's signing
secret is in the Vault: first without a request URL, to create the app, then
with it, once the signing secret is deposited.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import uuid
from collections.abc import Callable, Collection, Sequence
from pathlib import Path

from .receiver import EVENTS, SUBSCRIPTIONS
from .scopes import OPERATION_SCOPES


class SlackError(RuntimeError):
    pass


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]

PROJECT_RELATIVE = Path(".outcomeci/integrations/slack")


def _events(events: Collection[str]) -> list[str]:
    chosen = sorted(set(events))
    unknown = [event for event in chosen if event not in EVENTS]
    if not chosen or unknown:
        raise SlackError(
            f"Slack trigger events must be some of {', '.join(sorted(EVENTS))}"
            + (f"; unknown: {', '.join(unknown)}" if unknown else "")
        )
    return chosen


def _manifest(name: str, *, request_url: str | None, events: Collection[str]) -> dict[str, object]:
    if request_url is not None and not request_url.startswith("https://"):
        raise SlackError("The Slack request URL must be the workflow's https webhook URL")
    chosen = _events(events)
    settings: dict[str, object] = {
        "org_deploy_enabled": False,
        "socket_mode_enabled": False,
        "token_rotation_enabled": False,
    }
    if request_url is not None:
        settings["event_subscriptions"] = {
            "request_url": request_url,
            "bot_events": sorted(SUBSCRIPTIONS[event][0] for event in chosen),
        }
    return {
        "display_information": {
            "name": name,
            "description": "Starts OutcomeCI workflows and talks with them in threads.",
            "background_color": "#17131f",
        },
        "features": {
            "app_home": {
                "home_tab_enabled": False,
                "messages_tab_enabled": "dm" in chosen,
                "messages_tab_read_only_enabled": False,
            },
            "bot_user": {"display_name": name, "always_online": False},
        },
        "oauth_config": {
            "scopes": {
                "bot": sorted({*OPERATION_SCOPES, *(SUBSCRIPTIONS[event][1] for event in chosen)})
            }
        },
        "settings": settings,
    }


def _hooks() -> dict[str, object]:
    return {"hooks": {"get-manifest": "oci integration slack manifest --project ."}}


def scaffold(
    workspace: Path,
    name: str,
    *,
    request_url: str | None = None,
    events: Collection[str] = tuple(EVENTS),
) -> Path:
    """Write the Slack CLI project. The manifest is regenerated every time, so
    it always matches the trigger it was set up for."""
    project = workspace / PROJECT_RELATIVE
    project.mkdir(parents=True, exist_ok=True)
    slack_dir = project / ".slack"
    slack_dir.mkdir(parents=True, exist_ok=True)
    value = _manifest(name, request_url=request_url, events=events)
    managed_files = {
        project / "manifest.json": json.dumps(value, indent=2) + "\n",
        slack_dir / "hooks.json": json.dumps(_hooks(), indent=2) + "\n",
        slack_dir / ".gitignore": "apps.dev.json\ncache/\n",
    }
    for path, content in managed_files.items():
        path.write_text(content, encoding="utf-8")
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
    request_url: str | None = None,
    events: Collection[str] = tuple(EVENTS),
    name: str = "OutcomeCI",
    team: str | None = None,
    runner: CommandRunner = subprocess.run,
) -> dict[str, object]:
    """Generate the manifest, create or update and install the Slack app, and
    report what comes next.

    `request_url` is the workflow's webhook URL. Slack verifies it when the
    manifest is applied, so pass it only once the workflow declares its Slack
    trigger and its signing secret is in the Vault, granted to the workflow.
    """
    workspace = workspace.resolve()
    slack = _require_slack()
    project = scaffold(workspace, name, request_url=request_url, events=events)

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
    if request_url is not None:
        return {
            "configured": True,
            "project": str(project),
            "subscribed": request_url,
            "next": [],
        }
    return {
        "configured": True,
        "project": str(project),
        "subscribed": None,
        "next": [
            "oci integration slack sync-credentials --workspace "
            + str(workspace)
            + " --cloud <workspace-id> --workflow <workflow-id>",
            "Deposit the app's Signing Secret (Slack app settings, Basic Information) "
            "in the Vault at the path the trigger's auth names, granted to the workflow.",
            "Rerun this setup with --request-url <the workflow's webhook URL> to "
            "subscribe the app to its events.",
        ],
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
