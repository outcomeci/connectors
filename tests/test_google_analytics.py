import dataclasses

import jsonschema
import pytest

from outcomeci_connectors.providers.google.analytics import PROVIDER, SCOPES


def test_google_analytics_auth_and_origin():
    contract = PROVIDER.contract()
    assert contract["name"] == "google.analytics"
    assert contract["base_url"] == "https://analyticsdata.googleapis.com"
    oauth, service = contract["auth"]["accepts"]
    assert oauth["kind"] == "oauth2"
    assert oauth["authorization_parameters"] == {"access_type": "offline", "prompt": "consent"}
    assert oauth["pkce"] is True
    assert oauth["grant_types"] == ["refresh_token"]
    assert service["kind"] == "jwt_bearer"
    assert oauth["scopes"] == service["scopes"] == list(SCOPES)
    assert service["token_url"] == oauth["token_url"] == "https://oauth2.googleapis.com/token"


@pytest.mark.parametrize("name", ["report", "realtime", "metadata"])
def test_fixed_property_scoped_reads(name):
    operation = PROVIDER.contract()["operations"][name]
    assert operation["side_effect"] == "read"
    assert operation["grantable"] == {"property": {"field": "property"}}
    assert operation["request"]["path"].startswith("/v1beta/properties/{{ input.property }}")
    jsonschema.Draft202012Validator.check_schema(operation["input"])


@pytest.mark.parametrize("property", ["1234", "987654321"])
def test_valid_report(property):
    jsonschema.validate(
        {
            "property": property,
            "report": {
                "metrics": [{"name": "activeUsers"}],
                "dateRanges": [{"startDate": "7daysAgo", "endDate": "yesterday"}],
                "limit": "100",
            },
        },
        PROVIDER.operations["report"].input,
    )


@pytest.mark.parametrize(
    "patch",
    [
        {"property": "../accounts/123"},
        {"property": "0"},
        {"property": "123?key=x"},
        {"report": {"metrics": [], "limit": "10"}},
        {"report": {"metrics": [{"name": "activeUsers"}], "limit": "250000"}},
        {"path": "/admin"},
        {"method": "DELETE"},
    ],
)
def test_refuses_unbounded_or_unscoped_inputs(patch):
    value = {"property": "123", "report": {"metrics": [{"name": "activeUsers"}], "limit": "100"}}
    value.update(patch)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(value, PROVIDER.operations["realtime"].input)


@pytest.mark.parametrize("key", ["state", "redirect_uri", "scope", "client_id", "code_challenge"])
def test_provider_cannot_override_runtime_oauth_security_parameters(key):
    with pytest.raises(ValueError):
        dataclasses.replace(PROVIDER.auth[0], authorization_parameters={key: "override"})
