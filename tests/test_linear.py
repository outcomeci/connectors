from importlib.metadata import entry_points

import jsonschema
import pytest

from outcomeci_connectors.providers.linear import (
    COMMENT_ISSUE,
    CREATE_ISSUE,
    PROVIDER,
    READ_ISSUE,
    SEARCH_ISSUES,
)

TEAM = "9cfb482a-81e3-4154-b5b9-2c805e70a02d"


def operation(name):
    return PROVIDER.contract()["operations"][name]


def test_entry_point_loads_provider():
    registered = {ep.name: ep.load() for ep in entry_points(group="outcomeci.connectors")}
    assert registered["linear"] is PROVIDER


def test_api_key_is_sent_bare_and_oauth_rotates_refresh_tokens():
    contract = PROVIDER.contract()
    assert contract["base_url"] == "https://api.linear.app"
    api_key, oauth = contract["auth"]["accepts"]
    assert api_key == {
        "kind": "api_key",
        "description": api_key["description"],
        "credential": ["api_key"],
        "header": "Authorization",
        "scheme": None,
    }
    assert oauth == {
        "kind": "oauth2",
        "description": oauth["description"],
        "credential": ["client_id", "client_secret", "refresh_token"],
        "token_url": "https://api.linear.app/oauth/token",
        "authorization_url": "https://linear.app/oauth/authorize",
        "pkce": True,
        "grant_types": ["refresh_token"],
        "scopes": ["read", "issues:create", "comments:create"],
        "scope_separator": ",",
        "audience": None,
        "client_auth": "body",
        "rotates_refresh_token": True,
    }


def test_operations_are_fixed_graphql_posts_with_fixed_queries():
    queries = {
        "create_issue": CREATE_ISSUE,
        "issue": READ_ISSUE,
        "search_issues": SEARCH_ISSUES,
        "comment_issue": COMMENT_ISSUE,
    }
    operations = PROVIDER.contract()["operations"]
    assert set(operations) == set(queries)
    for name, query in queries.items():
        assert operations[name]["request"] == {
            "method": "POST",
            "path": "/graphql",
            "body": {"query": query, "variables": "{{ input }}"},
        }
        assert operations[name]["deny"] == []
        assert operations[name]["response"]["expose"]["errors"] == "body.errors"


def test_every_input_field_is_a_declared_graphql_variable():
    queries = {
        "create_issue": CREATE_ISSUE,
        "issue": READ_ISSUE,
        "search_issues": SEARCH_ISSUES,
        "comment_issue": COMMENT_ISSUE,
    }
    for name, query in queries.items():
        header = query.split(") {", 1)[0]
        for field in operation(name)["input"]["properties"]:
            assert f"${field}:" in header, (name, field)


def test_create_issue_is_scoped_to_the_granted_team():
    create = operation("create_issue")
    assert create["side_effect"] == "create"
    assert create["grantable"] == {"team_id": {"field": "team_id"}}
    assert "teamId: $team_id" in CREATE_ISSUE
    assert create["response"]["expose"] == {
        "success": "body.data.issueCreate.success",
        "issue": "body.data.issueCreate.issue",
        "errors": "body.errors",
    }
    for field in ("identifier", "url", "team {", "state {", "labels {"):
        assert field in CREATE_ISSUE


def test_reads_filter_by_the_granted_team():
    for name, query in (("issue", READ_ISSUE), ("search_issues", SEARCH_ISSUES)):
        read = operation(name)
        assert read["side_effect"] == "read"
        assert read["grantable"] == {"team_id": {"field": "team_id"}}
        assert "team: {id: {eq: $team_id}}" in query
    assert "id: {eq: $id}" in READ_ISSUE
    # The agent's filter can only narrow the team's issues.
    assert "and: [$filter]" in SEARCH_ISSUES
    assert "or:" not in SEARCH_ISSUES
    assert operation("issue")["response"]["expose"] == {
        "issues": "body.data.issues.nodes",
        "errors": "body.errors",
    }
    assert operation("search_issues")["response"]["expose"] == {
        "issues": "body.data.issues.nodes",
        "page_info": "body.data.issues.pageInfo",
        "errors": "body.errors",
    }
    for field in ("state {", "assignee {", "labels {"):
        assert field in READ_ISSUE


def test_comment_is_scoped_to_the_granted_issue():
    comment = operation("comment_issue")
    assert comment["side_effect"] == "create"
    assert comment["grantable"] == {"issue_id": {"field": "issue_id"}}
    assert "issueId: $issue_id" in COMMENT_ISSUE
    assert comment["response"]["expose"] == {
        "success": "body.data.commentCreate.success",
        "comment": "body.data.commentCreate.comment",
        "errors": "body.errors",
    }


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("create_issue", {"team_id": TEAM, "title": "Login fails"}),
        (
            "create_issue",
            {
                "team_id": TEAM,
                "title": "Login fails",
                "description": "## Steps",
                "label_ids": ["a"],
            },
        ),
        ("issue", {"team_id": TEAM, "id": "2174add1-f7c8-44e3-bbf3-2d60b5ea8bc9"}),
        ("search_issues", {"team_id": TEAM}),
        (
            "search_issues",
            {"team_id": TEAM, "filter": {"number": {"eq": 7}}, "first": 100, "after": "c"},
        ),
        ("comment_issue", {"issue_id": "ENG-7", "body": "Fixed in #12."}),
    ],
)
def test_valid_inputs(name, value):
    schema = operation(name)["input"]
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(value, schema)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("create_issue", {"team_id": TEAM}),
        ("create_issue", {"team_id": TEAM, "title": ""}),
        ("create_issue", {"team_id": TEAM, "title": "x", "query": "mutation { x }"}),
        ("issue", {"team_id": TEAM}),
        ("search_issues", {}),
        ("search_issues", {"team_id": TEAM, "first": 0}),
        ("search_issues", {"team_id": TEAM, "first": 101}),
        ("search_issues", {"team_id": TEAM, "filter": "team"}),
        ("comment_issue", {"issue_id": "ENG-7"}),
        ("comment_issue", {"issue_id": "ENG-7", "body": ""}),
    ],
)
def test_invalid_inputs(name, value):
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(value, operation(name)["input"])


def test_webhook_secret_is_a_setup_credential_separate_from_auth():
    contract = PROVIDER.contract()
    (credential,) = contract["setup"]["credentials"]
    assert credential["id"] == "webhook_secret"
    assert credential["suggested_path"] == "linear/webhook-secret"
    assert credential["used_by"] == "receiver"
    assert set(contract["receiver"]["events"]) == {
        "issue_created",
        "issue_state_changed",
        "comment_added",
    }
