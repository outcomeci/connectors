from __future__ import annotations

import dataclasses

import pytest

from outcomeci_connectors.provider import (
    CONTRACT_VERSION,
    OIDC,
    ApiKey,
    AppInstallation,
    Basic,
    JwtBearer,
    NoAuth,
    OAuth2,
    Provider,
    Token,
)
from outcomeci_connectors.providers import github, slack


def _provider(*auth) -> Provider:
    return Provider(name="p", base_url="https://p.test", operations={}, auth=auth)


def test_the_contract_lists_accepted_kinds_in_order_under_a_kept_version():
    contract = _provider(Token(), Basic()).contract()
    assert contract["schema_version"] == CONTRACT_VERSION
    assert [item["kind"] for item in contract["auth"]["accepts"]] == ["token", "basic"]


def test_a_provider_accepts_a_bearer_token_by_default():
    accepts = Provider(name="p", base_url="https://p.test", operations={}).contract()["auth"]
    assert accepts == {
        "accepts": [
            {
                "kind": "token",
                "description": "",
                "credential": ["value"],
                "header": "Authorization",
                "scheme": "Bearer",
            }
        ]
    }


def test_slack_accepts_a_bot_token_and_a_rotating_refresh_token():
    token, rotation = slack.PROVIDER.contract()["auth"]["accepts"]
    assert token["kind"] == "token"
    assert (token["header"], token["scheme"]) == ("Authorization", "Bearer")
    assert rotation == {
        "kind": "oauth2",
        "description": rotation["description"],
        "credential": ["client_id", "client_secret", "refresh_token"],
        "token_url": "https://slack.com/api/oauth.v2.access",
        "grant_types": ["refresh_token"],
        "scopes": [],
        "audience": None,
        "client_auth": "basic",
        "rotates_refresh_token": True,
    }


def test_github_accepts_a_token_and_an_app_installation():
    token, app = github.PROVIDER.contract()["auth"]["accepts"]
    assert token["kind"] == "token"
    assert app["kind"] == "app_installation"
    assert app["token_url"] == (
        "https://api.github.com/app/installations/{installation_id}/access_tokens"
    )
    assert app["credential"] == ["app_id", "installation_id", "private_key"]
    assert (app["method"], app["algorithm"], app["jwt_lifetime_seconds"]) == ("POST", "RS256", 600)
    assert (app["token_field"], app["expires_field"]) == ("token", "expires_at")
    assert app["headers"]["Accept"] == "application/vnd.github+json"


def test_each_kind_names_what_the_credential_supplies():
    kinds = {
        item["kind"]: item["credential"]
        for item in _provider(
            Token(),
            ApiKey(header="X-API-Key"),
            Basic(),
            OAuth2(token_url="https://p.test/token"),
            OIDC(issuer="https://login.p.test"),
            JwtBearer(token_url="https://p.test/token"),
        ).contract()["auth"]["accepts"]
    }
    assert kinds == {
        "token": ["value"],
        "api_key": ["api_key"],
        "basic": ["username", "password"],
        "oauth2": ["client_id", "client_secret"],
        "oidc": ["client_id", "client_secret"],
        "jwt_bearer": ["issuer", "subject", "private_key"],
    }


def test_an_unauthenticated_provider_accepts_none_alone():
    assert _provider(NoAuth()).contract()["auth"] == {
        "accepts": [{"kind": "none", "credential": []}]
    }
    with pytest.raises(ValueError, match="nothing else"):
        _provider(NoAuth(), Token())
    with pytest.raises(ValueError, match="at least one"):
        _provider()


def test_a_kind_is_accepted_at_most_once():
    with pytest.raises(ValueError, match="at most once"):
        _provider(Token(), Token(header="X-Token", scheme=""))


def test_an_api_key_goes_in_a_header_or_a_query_parameter():
    assert ApiKey(header="Authorization", scheme="Token").contract()["header"] == "Authorization"
    query = ApiKey(query="api_key").contract()
    assert (query["query"], query["scheme"]) == ("api_key", None)
    assert "header" not in query
    with pytest.raises(ValueError):
        ApiKey()
    with pytest.raises(ValueError):
        ApiKey(header="X-Key", query="key")
    with pytest.raises(ValueError):
        ApiKey(query="key", scheme="Bearer")


def test_oauth2_runs_only_unattended_grants_over_https():
    OAuth2(token_url="https://p.test/token", grant_types=("client_credentials", "refresh_token"))
    with pytest.raises(ValueError, match="https"):
        OAuth2(token_url="http://p.test/token")
    with pytest.raises(ValueError, match="grant types"):
        OAuth2(token_url="https://p.test/token", grant_types=("authorization_code",))
    with pytest.raises(ValueError, match="grant types"):
        OAuth2(token_url="https://p.test/token", grant_types=())
    with pytest.raises(ValueError, match="client_auth"):
        OAuth2(token_url="https://p.test/token", client_auth="jwt")
    with pytest.raises(ValueError, match="rotates"):
        OAuth2(token_url="https://p.test/token", rotates_refresh_token=True)


def test_oidc_derives_discovery_from_a_fixed_issuer_or_asks_the_credential():
    fixed = OIDC(issuer="https://login.p.test/", scopes=("read",)).contract()
    assert fixed["discovery_url"] == "https://login.p.test/.well-known/openid-configuration"
    assert fixed["scopes"] == ["read"]
    tenant = OIDC().contract()
    assert tenant["issuer"] is None and tenant["discovery_url"] is None
    assert tenant["credential"] == ["issuer_url", "client_id", "client_secret"]
    with pytest.raises(ValueError):
        OIDC(issuer="http://login.p.test")


def test_jwt_bearer_names_its_token_endpoint_and_audience():
    contract = JwtBearer(
        token_url="https://oauth2.p.test/token", audience="https://p.test", scopes=("a", "b")
    ).contract()
    assert contract["audience"] == "https://p.test"
    assert contract["scopes"] == ["a", "b"]
    assert contract["algorithm"] == "RS256"


def test_an_app_installation_names_the_installation_and_a_short_lived_jwt():
    with pytest.raises(ValueError, match="installation_id"):
        AppInstallation(token_url="https://p.test/app/access_tokens")
    with pytest.raises(ValueError, match="600"):
        AppInstallation(token_url="https://p.test/{installation_id}", jwt_lifetime_seconds=3600)
    with pytest.raises(ValueError, match="RS256"):
        AppInstallation(token_url="https://p.test/{installation_id}", algorithm="HS256")


def test_the_digest_covers_the_accepted_kinds():
    one = _provider(Token())
    assert one.digest() == _provider(Token()).digest()
    assert one.digest() != _provider(Token(scheme="token")).digest()
    assert one.digest() != _provider(Token(), Basic()).digest()
    assert _provider(Token(), Basic()).digest() != _provider(Basic(), Token()).digest()
    assert slack.PROVIDER.digest() != dataclasses.replace(slack.PROVIDER, auth=(Token(),)).digest()
