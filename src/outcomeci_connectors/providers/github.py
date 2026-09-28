"""The GitHub REST API access a workflow can be granted with `uses: github`."""

from __future__ import annotations

from ..provider import Deny, Grantable, Operation, Provider

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

PROVIDER = Provider(
    name="github",
    base_url="https://api.github.com",
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
        ),
    },
    max_requests=100,
)
