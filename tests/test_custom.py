from __future__ import annotations

import pytest

from outcomeci_connectors.provider import CONTRACT_VERSION, ApiKey, Operation, Provider, Token
from outcomeci_connectors.providers import custom, github, media, slack, tavily


def test_custom_takes_its_origin_from_the_workflow():
    contract = custom.PROVIDER.contract()
    assert contract["schema_version"] == CONTRACT_VERSION
    assert contract["name"] == "custom"
    assert contract["base_url"] is None
    assert contract["base_url_from"] == "workflow"
    assert "managed" not in contract
    assert contract["max_requests"] == 50
    assert contract["watchers"] == {} and contract["receiver"] is None


def test_custom_accepts_static_credentials_only():
    accepts = custom.PROVIDER.contract()["auth"]["accepts"]
    assert [entry["kind"] for entry in accepts] == ["token", "api_key", "basic"]
    token, api_key, _ = accepts
    assert (token["header"], token["scheme"]) == ("Authorization", "Bearer")
    assert api_key["header"] is None and api_key["scheme"] is None
    assert api_key["header_from"] == "credential"
    assert api_key["default_header"] == "X-API-Key"
    assert api_key["credential"] == ["api_key"]


def test_custom_read_and_write_are_request_operations_scoped_by_path_prefix():
    operations = custom.PROVIDER.contract()["operations"]
    assert sorted(operations) == ["read", "write"]
    assert operations["read"]["request"] == {"methods": ["GET"]}
    assert operations["read"]["side_effect"] == "read"
    assert operations["write"]["request"] == {"methods": ["DELETE", "PATCH", "POST", "PUT"]}
    assert operations["write"]["side_effect"] == "execute"
    for operation in operations.values():
        assert operation["grantable"] == {
            "path": {"path_prefix": "{path}", "value_fields": ["path"]}
        }
        assert operation["deny"] == []
        assert operation["input"]["required"] == ["method", "path"]


def test_a_provider_with_a_fixed_origin_or_managed_carries_no_base_url_from():
    for provider in (slack.PROVIDER, github.PROVIDER, tavily.PROVIDER, media.PROVIDER):
        assert "base_url_from" not in provider.contract()
        assert "header_from" not in str(provider.contract()["auth"])
    assert media.PROVIDER.contract()["base_url"] is None


def test_an_api_key_read_from_the_credential_fixes_nothing_else():
    with pytest.raises(ValueError):
        ApiKey(header_from_credential=True, header="X-Key")
    with pytest.raises(ValueError):
        ApiKey(header_from_credential=True, query="key")
    with pytest.raises(ValueError):
        ApiKey(header_from_credential=True, scheme="Bearer")
    with pytest.raises(ValueError):
        ApiKey(header_from_credential=True, default_header="")


def test_an_origin_less_provider_digests_its_contract():
    one = Provider(name="a", base_url=None, operations={"get": Operation("g", methods=("GET",))})
    other = Provider(
        name="a", base_url="https://a.example", operations={"get": Operation("g", methods=("GET",))}
    )
    assert one.digest() != other.digest()
    assert isinstance(Token().contract(), dict)
