"""Agent discovery and secret validation do not grant HTTP or process authority."""

import json
from importlib.metadata import entry_points

import pytest
from jsonschema import validate

from outcomeci_connectors.agents import agent_provider, agent_providers


@pytest.mark.parametrize("name", ["codex", "claude", "opencode"])
def test_agents_are_discoverable_without_http_operations(name):
    registered = {entry.name: entry.load() for entry in entry_points(group="outcomeci.connectors")}
    provider = agent_provider(name)
    assert registered[name] == provider
    contract = provider.contract()
    assert contract["capability"] == "agent"
    assert "base_url" not in contract and "operations" not in contract
    assert contract["auth"]["configuration"] == {"provider": name}
    assert len(provider.digest()) == 64


@pytest.mark.parametrize(
    ("name", "secrets", "expected"),
    [
        (
            "codex",
            {"auth_json": '{"auth_mode":"chatgpt","tokens":{"access_token":"secret"}}'},
            {"auth_json": {"auth_mode": "chatgpt", "tokens": {"access_token": "secret"}}},
        ),
        ("claude", {"oauth_token": "secret"}, {"oauth_token": "secret"}),
        ("opencode", {"api_key": "secret"}, {"api_key": "secret"}),
    ],
)
def test_vault_strings_validate_and_decode_into_hydration(name, secrets, expected):
    provider = agent_provider(name)
    validate(secrets, provider.contract()["auth"]["secrets_schema"])
    assert provider.validate_credentials(secrets) == expected


@pytest.mark.parametrize("name", ["codex", "claude", "opencode"])
@pytest.mark.parametrize("invalid", [None, "", "   ", [], 42, True])
def test_invalid_credentials_are_rejected_without_values(name, invalid):
    provider = agent_provider(name)
    with pytest.raises(ValueError):
        provider.validate_credentials({provider.credential_secret: invalid})
    with pytest.raises(ValueError):
        provider.validate_credentials({"wrong": "sensitive-value"})


@pytest.mark.parametrize("value", ["null", "[]", "{}", "not-json", '{"bad":NaN}'])
def test_codex_requires_a_nonempty_json_object(value):
    with pytest.raises(ValueError):
        agent_provider("codex").validate_credentials({"auth_json": value})


def test_codex_isolated_file_auth_and_rotated_object_are_independent():
    provider = agent_provider("codex")
    assert provider.credential_file == "auth.json"
    assert provider.environment_variable == "CODEX_HOME"
    assert provider.config_files == {"config.toml": 'cli_auth_credentials_store = "file"\n'}
    original = {"auth_json": {"auth_mode": "chatgpt", "tokens": {"access_token": "first"}}}
    canonical = provider.validate_credentials(original)
    canonical["auth_json"]["tokens"]["access_token"] = "rotated"
    assert original["auth_json"]["tokens"]["access_token"] == "first"
    assert "rotated" not in json.dumps(provider.contract())


def test_unknown_provider_is_rejected_and_registry_is_not_mutable():
    agent_providers().clear()
    assert set(agent_providers()) == {"codex", "claude", "opencode"}
    with pytest.raises(ValueError, match="unknown agent provider"):
        agent_provider("unknown")


@pytest.mark.parametrize(
    "value",
    [{"tokens": {}}, {"auth_mode": "apikey", "tokens": {}}, {"auth_mode": "chatgpt", "tokens": []}],
)
def test_codex_rejects_incomplete_or_non_subscription_caches(value):
    with pytest.raises(ValueError, match="complete ChatGPT"):
        agent_provider("codex").validate_credentials({"auth_json": value})
