from importlib.metadata import entry_points

import jsonschema
import pytest

from outcomeci_connectors.providers.x import PROVIDER


def test_entry_point_and_bearer_auth():
    registered = {ep.name: ep.load() for ep in entry_points(group="outcomeci.connectors")}
    assert registered["x"] is PROVIDER
    contract = PROVIDER.contract()
    assert contract["base_url"] == "https://api.x.com"
    assert contract["max_requests"] == 10
    auth, oauth = contract["auth"]["accepts"]
    assert auth["kind"] == "token"
    assert auth["credential"] == ["value"]
    assert auth["header"] == "Authorization"
    assert auth["scheme"] == "Bearer"
    assert oauth == {
        "kind": "oauth2",
        "description": oauth["description"],
        "credential": ["client_id", "client_secret", "refresh_token"],
        "token_url": "https://api.x.com/2/oauth2/token",
        "authorization_url": "https://x.com/i/oauth2/authorize",
        "pkce": True,
        "grant_types": ["refresh_token"],
        "scopes": ["tweet.read", "tweet.write", "users.read", "offline.access"],
        "audience": None,
        "client_auth": "basic",
        "rotates_refresh_token": True,
    }


def test_search_is_fixed_read_only_and_bounded():
    operations = PROVIDER.contract()["operations"]
    assert set(operations) == {"search_recent", "post"}
    search = operations["search_recent"]
    assert search["request"] == {
        "method": "GET",
        "path": "/2/tweets/search/recent",
        "query": {
            "query": "{{ input.query }}",
            "max_results": "{{ input.max_results }}",
            "sort_order": "recency",
            "tweet.fields": "author_id,created_at,conversation_id,public_metrics,lang",
            "expansions": "author_id",
            "user.fields": "name,username,description,public_metrics",
        },
    }
    assert search["side_effect"] == "read"
    assert search["grantable"] == {
        "query": {"field": "query"},
        "max_results": {"field": "max_results"},
    }
    assert search["deny"] == []  # Fixed GET path; no arbitrary requests or writes.
    assert search["response"] == {
        "expose": {
            "posts": "body.data",
            "authors": "body.includes.users",
            "meta": "body.meta",
            "errors": "body.errors",
        }
    }


@pytest.mark.parametrize("limit", [10, 25, 100])
def test_valid_search_inputs(limit):
    schema = PROVIDER.contract()["operations"]["search_recent"]["input"]
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(
        {"query": '("agent workflows" OR MCP) -is:retweet', "max_results": limit}, schema
    )


@pytest.mark.parametrize(
    "inputs",
    [
        {},
        {"query": "MCP"},
        {"query": "", "max_results": 10},
        {"query": "x" * 4097, "max_results": 10},
        {"query": "MCP", "max_results": 9},
        {"query": "MCP", "max_results": 101},
        {"query": "MCP", "max_results": "10"},
        {"query": "MCP", "max_results": True},
        {"query": "MCP", "max_results": 10, "path": "/2/users/me"},
        {"query": "MCP", "max_results": 10, "method": "POST"},
        {"query": "MCP", "max_results": 10, "access_token": "not-a-secret"},
    ],
)
def test_invalid_or_extra_inputs_are_rejected(inputs):
    schema = PROVIDER.contract()["operations"]["search_recent"]["input"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(inputs, schema)


def test_post_is_fixed_scopable_and_has_no_other_write_features():
    post = PROVIDER.contract()["operations"]["post"]
    assert post["request"] == {"method": "POST", "path": "/2/tweets", "body": "{{ input }}"}
    assert post["side_effect"] == "create"
    assert post["grantable"] == {"text": {"field": "text"}, "reply": {"field": "reply"}}
    assert post["response"] == {"expose": {"id": "body.data.id", "text": "body.data.text"}}


@pytest.mark.parametrize(
    "inputs",
    [
        {"text": "Hello from a workflow."},
        {"text": "Thanks!", "reply": {"in_reply_to_tweet_id": "12345"}},
    ],
)
def test_valid_post_inputs(inputs):
    schema = PROVIDER.contract()["operations"]["post"]["input"]
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(inputs, schema)


@pytest.mark.parametrize(
    "inputs",
    [
        {},
        {"text": ""},
        {"text": "x" * 281},
        {"text": "hello", "reply": {}},
        {"text": "hello", "reply": {"in_reply_to_tweet_id": "bad"}},
        {"text": "hello", "reply": {"in_reply_to_tweet_id": "1", "extra": True}},
        {"text": "hello", "media": {"media_ids": ["1"]}},
        {"text": "hello", "quote_tweet_id": "1"},
        {"text": "hello", "method": "DELETE"},
        {"text": "hello", "access_token": "not-a-secret"},
    ],
)
def test_invalid_post_inputs(inputs):
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(inputs, PROVIDER.contract()["operations"]["post"]["input"])
