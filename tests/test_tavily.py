from importlib.metadata import entry_points

import jsonschema
import pytest

from outcomeci_connectors.providers.tavily import PROVIDER

SEARCH = PROVIDER.contract()["operations"]["search"]
CALL = {
    "query": "Python context manager documentation",
    "max_results": 5,
    "topic": "general",
    "search_depth": "basic",
    "include_domains": ["docs.python.org"],
    "exclude_domains": [],
}


def test_entry_point_and_bearer_api_key_auth():
    registered = {item.name: item.load() for item in entry_points(group="outcomeci.connectors")}
    assert registered["tavily"] is PROVIDER
    contract = PROVIDER.contract()
    assert contract["base_url"] == "https://api.tavily.com"
    assert set(contract["operations"]) == {"search"}
    token, api_key = contract["auth"]["accepts"]
    assert (token["kind"], token["credential"]) == ("token", ["value"])
    assert (api_key["kind"], api_key["credential"]) == ("api_key", ["api_key"])
    for auth in (token, api_key):
        assert auth["header"] == "Authorization"
        assert auth["scheme"] == "Bearer"
        assert "query" not in auth


def test_fixed_search_always_requests_usage_without_automatic_cost_changes():
    assert SEARCH["request"] == {
        "method": "POST",
        "path": "/search",
        "body": {
            "query": "{{ input.query }}",
            "max_results": "{{ input.max_results }}",
            "topic": "{{ input.topic }}",
            "search_depth": "{{ input.search_depth }}",
            "include_domains": "{{ input.include_domains }}",
            "exclude_domains": "{{ input.exclude_domains }}",
            "include_usage": True,
            "auto_parameters": False,
            "include_answer": False,
            "include_raw_content": False,
            "include_images": False,
        },
    }
    assert SEARCH["side_effect"] == "read"
    assert SEARCH["grantable"] == {
        key: {"field": key}
        for key in ("max_results", "topic", "search_depth", "include_domains", "exclude_domains")
    }
    jsonschema.Draft202012Validator.check_schema(SEARCH["input"])


@pytest.mark.parametrize("topic", ["general", "news", "finance"])
@pytest.mark.parametrize("depth", ["basic", "advanced", "fast", "ultra-fast"])
@pytest.mark.parametrize("limit", [1, 20])
def test_accepts_supported_searches(topic, depth, limit):
    jsonschema.validate(
        {**CALL, "topic": topic, "search_depth": depth, "max_results": limit}, SEARCH["input"]
    )


def test_accepts_unrestricted_sources_and_domain_limit_boundaries():
    jsonschema.validate({**CALL, "include_domains": []}, SEARCH["input"])
    jsonschema.validate(
        {
            **CALL,
            "include_domains": [f"source{i}.example.com" for i in range(300)],
            "exclude_domains": [f"excluded{i}.example.com" for i in range(150)],
        },
        SEARCH["input"],
    )


@pytest.mark.parametrize(
    "patch",
    [
        {"query": ""},
        {"query": " \n\t"},
        {"query": "q" * 4001},
        {"max_results": 0},
        {"max_results": 21},
        {"max_results": True},
        {"max_results": 1.5},
        {"topic": "documentation"},
        {"search_depth": "auto"},
        {"include_domains": ["https://docs.python.org"]},
        {"include_domains": ["example.com/path"]},
        {"include_domains": ["user@example.com"]},
        {"exclude_domains": ["example.com:443"]},
        {"include_domains": ["*.example.com"]},
        {"exclude_domains": ["-bad.example.com"]},
        {"include_domains": ["a.example.com\n"]},
        {"include_domains": ["a.example.com"] * 2},
        {"include_domains": [f"source{i}.example.com" for i in range(301)]},
        {"exclude_domains": [f"source{i}.example.com" for i in range(151)]},
        {"include_domains": None},
        {"url": "https://example.com"},
        {"path": "/crawl"},
        {"method": "DELETE"},
        {"headers": {"Authorization": "override"}},
        {"api_key": "override"},
        {"include_usage": False},
        {"auto_parameters": True},
        {"include_domains_mode": "prefer"},
        {"include_answer": True},
        {"include_raw_content": True},
        {"include_images": True},
        {"chunks_per_source": 100},
    ],
)
def test_rejects_unbounded_inputs_scope_widening_and_request_overrides(patch):
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**CALL, **patch}, SEARCH["input"])


@pytest.mark.parametrize("field", list(CALL))
def test_all_search_settings_are_explicit(field):
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            {key: value for key, value in CALL.items() if key != field}, SEARCH["input"]
        )


def test_response_preserves_citations_and_reported_usage():
    assert SEARCH["response"]["expose"] == {
        "query": "body.query",
        "results": "body.results",
        "usage": "body.usage",
        "request_id": "body.request_id",
        "response_time": "body.response_time",
    }
    # Whole-object mappings preserve source URLs/content and the provider's
    # actual credits. No derived estimate or zero default enters the contract.
    assert "default" not in str(SEARCH["response"])
