from dataclasses import replace
from importlib.metadata import entry_points

import pytest

from outcomeci_connectors.providers.linkedin import PROVIDER, SCOPES


def test_linkedin_is_discoverable_with_selectable_scopes_and_confidential_web_oauth():
    registered = {item.name: item.load() for item in entry_points(group="outcomeci.connectors")}
    assert registered["linkedin"] is PROVIDER
    auth = PROVIDER.contract()["auth"]["accepts"][0]
    assert auth["authorization_url"] == "https://www.linkedin.com/oauth/v2/authorization"
    assert auth["token_url"] == "https://www.linkedin.com/oauth/v2/accessToken"
    assert auth["pkce"] is False
    assert auth["client_auth"] == "body"
    assert auth["grant_types"] == ["refresh_token"]
    assert auth["rotates_refresh_token"] is False
    assert auth["scopes"] == []
    assert auth["optional_scopes"] == list(SCOPES)
    assert len(set(SCOPES)) == 12
    assert PROVIDER.contract()["operations"] == {}


@pytest.mark.parametrize("scopes", [("read", "read"), ("",), ("two scopes",)])
def test_invalid_optional_scope_names_are_rejected(scopes):
    with pytest.raises(ValueError, match="optional_scopes"):
        replace(PROVIDER.auth[0], optional_scopes=scopes)


def test_optional_scopes_cannot_overlap_required_scopes_or_exist_without_consent():
    with pytest.raises(ValueError, match="optional_scopes"):
        replace(PROVIDER.auth[0], scopes=(SCOPES[0],))
    with pytest.raises(ValueError, match="optional_scopes"):
        replace(PROVIDER.auth[0], authorization_url=None, pkce=None)
