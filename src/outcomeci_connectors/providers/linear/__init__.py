"""The Linear GraphQL API operations a workflow can be granted with `uses: linear`.

Linear has one GraphQL endpoint, so every operation is a fixed POST to
/graphql with a fixed query document; the call's input is only its variables.
An agent cannot change a query, and a team grant pins the variable every
query filters or creates by.
https://linear.app/developers/graphql
"""

from __future__ import annotations

from ...provider import ApiKey, Grantable, OAuth2, Operation, Provider
from ...setup import SetupCredential
from .receiver import RECEIVER

TEAM = Grantable(field="team_id")
# A comment names only its issue: commentCreate cannot be scoped to a team.
ISSUE = Grantable(field="issue_id")

ISSUE_FIELDS = """
    id
    identifier
    title
    url
    team { id key name }
    state { id name type }
    assignee { id name }
    labels { nodes { id name } }
"""

CREATE_ISSUE = (
    "mutation CreateIssue("
    "$team_id: String!, $title: String!, $description: String, $label_ids: [String!]"
    ") {\n"
    "  issueCreate(input: {"
    "teamId: $team_id, title: $title, description: $description, labelIds: $label_ids"
    "}) {\n"
    "    success\n"
    "    issue {" + ISSUE_FIELDS + "    }\n"
    "  }\n"
    "}"
)

# A read filters by the granted team and the issue id, both ANDed, so an
# issue in another team reads as no issue.
READ_ISSUE = (
    "query Issue($team_id: ID!, $id: ID!) {\n"
    "  issues(filter: {team: {id: {eq: $team_id}}, id: {eq: $id}}, first: 1) {\n"
    "    nodes {" + ISSUE_FIELDS + "    }\n"
    "  }\n"
    "}"
)

# The agent's filter sits inside `and`, beside the team filter, so it can only
# narrow the granted team's issues.
# https://linear.app/developers/filtering
SEARCH_ISSUES = (
    "query SearchIssues("
    "$team_id: ID!, $filter: IssueFilter = {}, $first: Int = 50, $after: String"
    ") {\n"
    "  issues(filter: {team: {id: {eq: $team_id}}, and: [$filter]}, "
    "first: $first, after: $after) {\n"
    "    nodes {" + ISSUE_FIELDS + "    }\n"
    "    pageInfo { hasNextPage endCursor }\n"
    "  }\n"
    "}"
)

COMMENT_ISSUE = (
    "mutation CommentIssue($issue_id: String!, $body: String!) {\n"
    "  commentCreate(input: {issueId: $issue_id, body: $body}) {\n"
    "    success\n"
    "    comment { id url }\n"
    "  }\n"
    "}"
)

TEAM_ID = {"type": "string", "minLength": 1}

# A personal API key is sent bare, "Authorization: <API_KEY>"; an OAuth access
# token as a bearer token. OAuth apps support PKCE, expire access tokens after
# a day and return a new refresh token on every refresh.
# https://linear.app/developers/graphql#authentication
# https://linear.app/developers/oauth-2-0-authentication
AUTH = (
    ApiKey(
        header="Authorization",
        description="A Linear personal API key (lin_api_), sent bare in Authorization.",
    ),
    OAuth2(
        token_url="https://api.linear.app/oauth/token",
        authorization_url="https://linear.app/oauth/authorize",
        pkce=True,
        grant_types=("refresh_token",),
        scopes=("read", "issues:create", "comments:create"),
        scope_separator=",",
        client_auth="body",
        rotates_refresh_token=True,
        description=(
            "Authorize a Linear account to read issues, create issues and comment, "
            "with rotating refresh tokens."
        ),
    ),
)

PROVIDER = Provider(
    name="linear",
    receiver=RECEIVER,
    setup_credentials=(
        SetupCredential(
            id="webhook_secret",
            label="Webhook signing secret",
            description=(
                "Find this on the webhook's page in Linear (Settings → API → Webhooks). "
                "Verifies incoming Linear events; not needed for outbound API calls. "
                "Configure the webhook URL and resource types separately in Linear."
            ),
            suggested_path="linear/webhook-secret",
        ),
    ),
    base_url="https://api.linear.app",
    auth=AUTH,
    operations={
        "create_issue": Operation(
            description=(
                "Create one issue in the granted team, with a title and optional Markdown "
                "description and label ids. Returns success, the issue's id, identifier "
                "(such as ENG-123), url, team, state, assignee and labels, and any GraphQL "
                "errors."
            ),
            method="POST",
            path="/graphql",
            input={
                "type": "object",
                "required": ["team_id", "title"],
                "properties": {
                    "team_id": TEAM_ID,
                    "title": {"type": "string", "minLength": 1, "maxLength": 255},
                    "description": {"type": "string", "maxLength": 100000},
                    "label_ids": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1},
                        "maxItems": 20,
                    },
                },
                "additionalProperties": False,
            },
            body={"query": CREATE_ISSUE, "variables": "{{ input }}"},
            expose={
                "success": "body.data.issueCreate.success",
                "issue": "body.data.issueCreate.issue",
                "errors": "body.errors",
            },
            side_effect="create",
            grantable={"team_id": TEAM},
        ),
        "issue": Operation(
            description=(
                "Read one issue of the granted team by its id: its identifier, title, url, "
                "current state, assignee and labels. Returns an empty list when the issue "
                "is not in the team. Find an issue's id with search_issues."
            ),
            method="POST",
            path="/graphql",
            input={
                "type": "object",
                "required": ["team_id", "id"],
                "properties": {"team_id": TEAM_ID, "id": {"type": "string", "minLength": 1}},
                "additionalProperties": False,
            },
            body={"query": READ_ISSUE, "variables": "{{ input }}"},
            expose={"issues": "body.data.issues.nodes", "errors": "body.errors"},
            grantable={"team_id": TEAM},
        ),
        "search_issues": Operation(
            description=(
                "List the granted team's issues, optionally narrowed by a "
                "Linear IssueFilter, such as "
                '{"state": {"type": {"eq": "started"}}}, '
                '{"number": {"eq": 123}}, {"labels": {"name": {"eq": "Bug"}}} or '
                '{"searchableContent": {"contains": "login"}}. The filter is ANDed with '
                "the team, so it cannot reach other teams. Returns up to `first` issues "
                "(default 50, at most 100) and pageInfo; pass pageInfo.endCursor as "
                "`after` for the next page."
            ),
            method="POST",
            path="/graphql",
            input={
                "type": "object",
                "required": ["team_id"],
                "properties": {
                    "team_id": TEAM_ID,
                    "filter": {"type": "object"},
                    "first": {"type": "integer", "minimum": 1, "maximum": 100},
                    "after": {"type": "string", "minLength": 1},
                },
                "additionalProperties": False,
            },
            body={"query": SEARCH_ISSUES, "variables": "{{ input }}"},
            expose={
                "issues": "body.data.issues.nodes",
                "page_info": "body.data.issues.pageInfo",
                "errors": "body.errors",
            },
            grantable={"team_id": TEAM},
        ),
        "comment_issue": Operation(
            description=(
                "Add one Markdown comment to the granted issue, named by its id or "
                "identifier as granted. Returns success, the comment's id and url, and "
                "any GraphQL errors."
            ),
            method="POST",
            path="/graphql",
            input={
                "type": "object",
                "required": ["issue_id", "body"],
                "properties": {
                    "issue_id": {"type": "string", "minLength": 1},
                    "body": {"type": "string", "minLength": 1, "maxLength": 100000},
                },
                "additionalProperties": False,
            },
            body={"query": COMMENT_ISSUE, "variables": "{{ input }}"},
            expose={
                "success": "body.data.commentCreate.success",
                "comment": "body.data.commentCreate.comment",
                "errors": "body.errors",
            },
            side_effect="create",
            grantable={"issue_id": ISSUE},
        ),
    },
    max_requests=50,
)
