"""The GitHub REST API access a workflow can be granted with `uses: github`."""

from __future__ import annotations

from ..provider import AppInstallation, Compare, Deny, Grantable, Operation, Provider, Token

REPO = Grantable(path_prefix="/repos/{owner}/{name}", value_fields=("owner", "name"))
CHANGES = ("PATCH", "POST", "PUT")
REPOSITORY = r"^/repos/[^/]+/[^/]+"

# Writing code means branches, commits and pull requests. These are the
# repository's settings, access and merge controls, which no grant opens.
WRITE_DENY = (
    Deny(path=r"^/(?!repos/)", methods=CHANGES, reason="changes outside a repository"),
    Deny(path=REPOSITORY + r"/?$", methods=CHANGES, reason="repository settings"),
    Deny(
        path=REPOSITORY
        + r"/(transfer|collaborators|invitations|hooks|keys|actions|environments|rulesets"
        r"|pages|dependabot|codespaces|autolinks|topics|vulnerability-alerts"
        r"|automated-security-fixes|private-vulnerability-reporting|properties)(/|$)",
        reason="repository administration",
    ),
    Deny(path=REPOSITORY + r"/branches/[^/]+/protection", reason="branch protection"),
    Deny(path=REPOSITORY + r"/pulls/\d+/merge$", methods=CHANGES, reason="merging"),
    Deny(path=REPOSITORY + r"/merges$", methods=CHANGES, reason="merging"),
    Deny(path=REPOSITORY + r"/git/refs/", methods=("PATCH",), reason="moving existing branches"),
)

# A reviewer sees a committed file as a diff against the branch's current copy.
FILE_WRITE = Compare(
    path=REPOSITORY + r"/contents/.+",
    proposed="body.content",
    current="body.content",
    ref="body.branch",
    encoding="base64",
)

# A personal access token, classic or fine-grained, is sent as a bearer
# token. A GitHub App authenticates as one installation: a JWT signed with the
# app's private key buys an installation token that lasts an hour.
AUTH = (
    Token(description="A GitHub personal access token, classic or fine-grained."),
    AppInstallation(
        token_url="https://api.github.com/app/installations/{installation_id}/access_tokens",
        headers=(
            ("Accept", "application/vnd.github+json"),
            ("X-GitHub-Api-Version", "2022-11-28"),
        ),
        description=(
            "A GitHub App installation: the app's client id or app id, the installation "
            "id and the app's private key, exchanged for a one-hour installation token."
        ),
    ),
)

PROVIDER = Provider(
    name="github",
    base_url="https://api.github.com",
    auth=AUTH,
    operations={
        "read": Operation(
            description=(
                "Read from the GitHub REST API: send a GET to any path under "
                "https://api.github.com, such as /repos/{owner}/{repo}/contents/{path}."
            ),
            methods=("GET",),
            grantable={"repo": REPO},
        ),
        "write": Operation(
            description=(
                "Read and write through the GitHub REST API: create branches "
                "(POST /repos/{owner}/{repo}/git/refs), commit files "
                "(PUT /repos/{owner}/{repo}/contents/{path}) and open pull requests "
                "(POST /repos/{owner}/{repo}/pulls). DELETE, merging, branch updates and "
                "repository settings and administration are not allowed."
            ),
            methods=("GET", "PATCH", "POST", "PUT"),
            side_effect="execute",
            grantable={"repo": REPO},
            deny=WRITE_DENY,
            compare=(FILE_WRITE,),
        ),
    },
    max_requests=100,
)
