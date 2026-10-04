import dataclasses
import json

import pytest

from outcomeci_connectors.providers.github import PROVIDER as GITHUB
from outcomeci_connectors.providers.slack import PROVIDER as SLACK
from outcomeci_connectors.setup import SetupCredential


def test_slack_setup_is_discoverable_without_api_or_ui():
    contract = json.loads(json.dumps(SLACK.contract()))
    (secret,) = contract["setup"]["credentials"]
    assert secret["id"] == "signing_secret"
    assert secret["suggested_path"] == "slack/signing-secret"
    assert secret["used_by"] == "receiver"
    assert secret["required"] is True
    assert secret["secret"] is True
    assert [method["kind"] for method in contract["auth"]["accepts"]] == ["token", "oauth2"]
    assert "value" not in secret
    assert SLACK.digest() != dataclasses.replace(SLACK, setup_credentials=()).digest()
    assert "setup" not in GITHUB.contract()


@pytest.mark.parametrize("path", ["/absolute", "../escape", "slack//secret"])
def test_setup_paths_are_relative(path):
    with pytest.raises(ValueError):
        SetupCredential("secret", "Secret", "Verify events", path)


def test_setup_requires_a_receiver_and_unique_ids():
    secret = SLACK.setup_credentials[0]
    with pytest.raises(ValueError, match="receiver"):
        dataclasses.replace(GITHUB, setup_credentials=(secret,))
    with pytest.raises(ValueError, match="unique"):
        dataclasses.replace(SLACK, setup_credentials=(secret, secret))
