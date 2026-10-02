from __future__ import annotations

from importlib.metadata import entry_points

import pytest

from outcomeci_connectors.provider import (
    CONTRACT_VERSION,
    Compare,
    Download,
    Grantable,
    Operation,
    Provider,
    QueryQualifier,
    Watcher,
)
from outcomeci_connectors.providers import github, slack


def test_built_in_providers_are_registered_as_entry_points():
    registered = {item.name: item.load() for item in entry_points(group="outcomeci.connectors")}
    assert registered["slack"] is slack.PROVIDER
    assert registered["github"] is github.PROVIDER


def test_slack_contract_carries_the_first_built_ins():
    contract = slack.PROVIDER.contract()
    assert contract["schema_version"] == CONTRACT_VERSION
    assert sorted(contract["operations"]) == ["file", "post", "reactions", "thread"]
    post = contract["operations"]["post"]
    assert post["request"] == {
        "method": "POST",
        "path": "/api/chat.postMessage",
        "body": "{{ input }}",
    }
    assert post["grantable"] == {
        "channel": {"field": "channel"},
        "thread_ts": {"field": "thread_ts"},
    }
    assert post["response"]["expose"] == {
        "channel": "body.channel",
        "ts": "body.ts",
        "thread_ts": "body.message.thread_ts",
    }
    assert contract["watchers"]["reaction"]["operation"] == "reactions"
    assert contract["watchers"]["reply"]["operation"] == "thread"
    assert contract["watchers"]["reply"]["respond"] == "post"
    assert contract["watchers"]["reply"]["thread_field"] == "thread_ts"
    assert contract["watchers"]["reaction"]["respond"] == "post"
    assert contract["watchers"]["reply"]["attachment"] == "file"


def test_a_slack_file_is_read_only_where_it_is_shared_and_downloaded_from_slack():
    file = slack.PROVIDER.contract()["operations"]["file"]

    assert file["request"] == {
        "method": "GET",
        "path": "/api/files.info",
        "query": {"file": "{{ input.file }}"},
    }
    assert file["grantable"] == {
        "channel": {"response_in": ["body.file.channels", "body.file.groups", "body.file.ims"]}
    }
    assert file["response"]["download"] == {
        "url": "body.file.url_private_download",
        "hosts": ["files.slack.com"],
        "name": "body.file.name",
        "content_type": "body.file.mimetype",
        "max_bytes": 2 * 1024 * 1024,
    }
    assert "url" not in " ".join(file["response"]["expose"].values())


REPO_QUERY = QueryQualifier(param="q", term="repo:{owner}/{name}", exclusive=("org", "repo"))


def test_a_grantable_argument_has_exactly_one_kind():
    Grantable(response_in=("body.file.channels",))
    Grantable(query_qualifier=REPO_QUERY, value_fields=("owner", "name"))
    with pytest.raises(ValueError):
        Grantable()
    with pytest.raises(ValueError):
        Grantable(field="channel", response_in=("body.file.channels",))
    with pytest.raises(ValueError):
        Grantable(path_prefix="/repos/{owner}/{name}", query_qualifier=REPO_QUERY)
    with pytest.raises(ValueError):
        Grantable(field="q", query_qualifier=REPO_QUERY)


def test_a_query_qualifier_is_a_name_value_term_its_exclusive_names_include():
    with pytest.raises(ValueError):
        QueryQualifier(param="", term="repo:{owner}/{name}", exclusive=("repo",))
    with pytest.raises(ValueError):
        QueryQualifier(param="q", term="{owner}/{name}", exclusive=("repo",))
    with pytest.raises(ValueError):
        QueryQualifier(param="q", term="repo:{owner}/{name}", exclusive=("org",))


def test_only_a_request_operation_scopes_a_query():
    scoped = {"repo": Grantable(query_qualifier=REPO_QUERY, value_fields=("owner", "name"))}
    Operation(description="x", methods=("GET",), grantable=scoped)
    with pytest.raises(ValueError):
        Operation(description="x", method="GET", path="/search", grantable=scoped)


def test_only_a_fixed_operation_downloads():
    download = Download(url="body.url", hosts=("files.example.com",), name="n", content_type="t")
    with pytest.raises(ValueError):
        Operation(description="x", methods=("GET",), download=download)
    with pytest.raises(ValueError):
        Download(url="body.url", hosts=(), name="n", content_type="t")


def test_only_a_request_operation_compares():
    compare = Compare(path=r"^/files/.+", proposed="body.content", current="body.content")
    with pytest.raises(ValueError):
        Operation(description="x", method="PUT", path="/files/a", compare=(compare,))
    with pytest.raises(ValueError):
        Compare(path=r"^/f", proposed="content", current="body.content")
    with pytest.raises(ValueError):
        Compare(path=r"^/f", proposed="body.c", current="body.c", encoding="hex")


def test_a_github_file_commit_is_reviewed_as_a_diff_against_its_branch():
    import re

    rule, _ = github.PROVIDER.contract()["operations"]["write"]["compare"]
    assert rule == {
        "methods": ["PUT"],
        "path": rule["path"],
        "proposed": "body.content",
        "current": "body.content",
        "ref": "body.branch",
        "encoding": "base64",
    }
    assert re.search(rule["path"], "/repos/o/r/contents/src/app.py")
    assert not re.search(rule["path"], "/repos/o/r/pulls")
    assert "compare" not in github.PROVIDER.contract()["operations"]["read"]


def test_a_single_file_compare_contract_names_no_entries():
    compare = Compare(path=r"^/f/.+", proposed="body.c", current="body.c", ref="body.b")
    assert compare.contract() == {
        "methods": ["PUT"],
        "path": r"^/f/.+",
        "proposed": "body.c",
        "current": "body.c",
        "ref": "body.b",
        "encoding": "text",
    }


def test_compared_entries_name_each_file_and_how_to_read_it():
    entries = {
        "path": r"^/r/(?P<repo>[^/]+)/tree$",
        "methods": ("POST",),
        "entries": "body.tree",
        "entry_path": "path",
        "proposed": "content",
        "current": "body.content",
        "current_path": "/r/{repo}/files/{file}",
    }
    assert Compare(**entries, deletion="sha", current_encoding="base64").contract() == {
        "methods": ["POST"],
        "path": r"^/r/(?P<repo>[^/]+)/tree$",
        "proposed": "content",
        "current": "body.content",
        "ref": None,
        "encoding": "text",
        "current_encoding": "base64",
        "entries": "body.tree",
        "entry_path": "path",
        "deletion": "sha",
        "current_path": "/r/{repo}/files/{file}",
    }
    for broken in (
        {"entry_path": None},
        {"current_path": None},
        {"entries": "tree"},
        {"current": "content"},
        {"current_path": "/r/{repo}/files"},
        {"current_path": "/r/{owner}/files/{file}"},
        {"current_encoding": "hex"},
    ):
        with pytest.raises(ValueError):
            Compare(**{**entries, **broken})
    with pytest.raises(ValueError):
        Compare(path=r"^/f", proposed="body.c", current="body.c", entry_path="path")
    with pytest.raises(ValueError):
        Compare(path=r"^/f", proposed="body.c", current="body.c", current_path="/f/{file}")


def test_a_github_tree_is_reviewed_as_a_diff_of_each_file():
    import re

    _, rule = github.PROVIDER.contract()["operations"]["write"]["compare"]
    assert rule == {
        "methods": ["POST"],
        "path": rule["path"],
        "proposed": "content",
        "current": "body.content",
        "ref": None,
        "encoding": "text",
        "current_encoding": "base64",
        "entries": "body.tree",
        "entry_path": "path",
        "deletion": "sha",
        "current_path": "/repos/{owner}/{repo}/contents/{file}",
    }
    match = re.search(rule["path"], "/repos/o/r/git/trees")
    assert match and match.groupdict() == {"owner": "o", "repo": "r"}
    assert not re.search(rule["path"], "/repos/o/r/git/trees/abc")
    assert not re.search(rule["path"], "/repos/o/r/git/commits")


def test_a_reply_can_be_files_alone():
    output = {
        "messages": [
            {"ts": "1.0", "text": "plan", "bot_id": "B1"},
            {
                "ts": "2.0",
                "text": "",
                "user": "U1",
                "subtype": "file_share",
                "files": [
                    {
                        "id": "F1",
                        "name": "shot.png",
                        "mimetype": "image/png",
                        "size": 10,
                        "url_private": "https://files.slack.com/secret",
                    }
                ],
            },
        ]
    }

    (reply,) = slack.human_replies(output)

    assert reply["files"] == [{"id": "F1", "name": "shot.png", "mimetype": "image/png", "size": 10}]


def test_github_read_and_write_are_request_operations_scoped_by_repo():
    operations = github.PROVIDER.contract()["operations"]
    assert operations["read"]["request"] == {"methods": ["GET"]}
    assert operations["write"]["request"] == {"methods": ["GET", "PATCH", "POST", "PUT"]}
    assert operations["write"]["grantable"]["repo"] == {
        "path_prefix": "/repos/{owner}/{name}",
        "value_fields": ["owner", "name"],
    }


def test_github_search_is_a_get_of_code_search_scoped_by_the_repo_qualifier():
    operations = github.PROVIDER.contract()["operations"]
    search = operations["search"]
    assert search["request"] == {"methods": ["GET"]}
    assert search["side_effect"] == operations["read"]["side_effect"] == "read"
    assert search["grantable"] == {
        "repo": {
            "query_qualifier": {
                "param": "q",
                "term": "repo:{owner}/{name}",
                "exclusive": ["org", "owner", "repo", "user"],
                "operators": ["NOT", "OR"],
            },
            "value_fields": ["owner", "name"],
        }
    }
    assert "repo:" in search["description"] and "default branch" in search["description"]
    assert "\u2014" not in search["description"]
    assert "compare" not in search


@pytest.mark.parametrize(
    ("path", "denied"),
    [
        ("/search/code", False),
        ("/search/code/", True),
        ("/search/commits", True),
        ("/search/issues", True),
        ("/search/codex", True),
        ("/repos/o/r/contents/a.py", True),
        ("/", True),
    ],
)
def test_github_search_denies_every_path_but_code_search(path, denied):
    import re

    rules = github.PROVIDER.contract()["operations"]["search"]["deny"]
    assert any(re.search(rule["path"], path) for rule in rules) is denied


def test_github_read_and_write_are_unchanged_by_search():
    operations = github.PROVIDER.contract()["operations"]
    assert set(operations) == {"read", "search", "write"}
    assert operations["read"]["grantable"] == operations["write"]["grantable"]
    assert operations["read"]["deny"] == []


def test_digest_changes_with_the_contract():
    assert slack.PROVIDER.digest() == slack.PROVIDER.digest()
    assert slack.PROVIDER.digest() != github.PROVIDER.digest()


def test_reaction_watcher_matches_the_emoji_only():
    output = {"reactions": [{"name": "eyes", "count": 2}, {"name": "+1", "count": 1}]}
    assert slack.reaction_matches(output, "+1")
    assert not slack.reaction_matches(output, "tada")
    assert not slack.reaction_matches({"reactions": None}, "+1")


def test_reply_watcher_skips_the_root_bots_and_already_read_replies():
    output = {
        "messages": [
            {"ts": "1.0", "text": "plan", "bot_id": "B1"},
            {"ts": "2.0", "text": "why?", "user": "U1"},
            {"ts": "3.0", "text": "answer", "bot_id": "B1"},
            {"ts": "4.0", "text": "", "user": "U1"},
            {"ts": "5.0", "text": "joined", "subtype": "channel_join"},
            {"ts": "6.0", "text": "go ahead", "user": "U1"},
        ]
    }
    assert [reply["text"] for reply in slack.human_replies(output)] == ["why?", "go ahead"]
    assert [reply["ts"] for reply in slack.human_replies(output, after="2.0")] == ["6.0"]


def test_operations_are_either_fixed_or_requests():
    with pytest.raises(ValueError):
        Operation(description="x", method="GET")
    with pytest.raises(ValueError):
        Operation(description="x", method="GET", path="/x", methods=("GET",))
    with pytest.raises(ValueError):
        Grantable()
    assert (
        Provider(name="p", base_url="https://p.test", operations={}).contract()["operations"] == {}
    )


def test_a_watcher_must_read_a_declared_operation():
    with pytest.raises(ValueError, match="unknown operation"):
        Provider(
            name="p",
            base_url="https://p.test",
            operations={},
            watchers={"reaction": Watcher(operation="reactions", match=lambda output: True)},
        )


def _denied(method: str, path: str) -> bool:
    import re

    for rule in github.PROVIDER.contract()["operations"]["write"]["deny"]:
        if (not rule["methods"] or method in rule["methods"]) and re.search(rule["path"], path):
            return True
    return False


@pytest.mark.parametrize(
    ("method", "path", "denied"),
    [
        ("POST", "/repos/o/r/git/refs", False),
        ("PUT", "/repos/o/r/contents/src/app.py", False),
        ("POST", "/repos/o/r/pulls", False),
        ("PATCH", "/repos/o/r/pulls/7", False),
        ("GET", "/repos/o/r", False),
        ("PATCH", "/repos/o/r", True),
        ("POST", "/repos/o/r/transfer", True),
        ("PUT", "/repos/o/r/collaborators/eve", True),
        ("POST", "/repos/o/r/hooks", True),
        ("PUT", "/repos/o/r/pulls/7/merge", True),
        ("POST", "/repos/o/r/merges", True),
        ("PATCH", "/repos/o/r/git/refs/heads/main", True),
        ("PUT", "/repos/o/r/branches/main/protection", True),
        ("PUT", "/repos/o/r/actions/secrets/TOKEN", True),
        ("POST", "/user/repos", True),
        ("POST", "/orgs/o/repos", True),
    ],
)
def test_github_write_denies_administration_and_merging(method, path, denied):
    assert _denied(method, path) is denied


def test_watchers_can_require_one_user():
    reactions = {"reactions": [{"name": "+1", "count": 1, "users": ["U2"]}]}
    assert slack.reaction_matches(reactions, "+1")
    assert slack.reaction_matches(reactions, "+1", by="U2")
    assert not slack.reaction_matches(reactions, "+1", by="U1")
    thread = {"messages": [{"ts": "1.0"}, {"ts": "2.0", "text": "go", "user": "U2"}]}
    assert slack.human_replies(thread, by="U1") == []
    assert slack.human_replies(thread, by="U2")[0]["text"] == "go"
