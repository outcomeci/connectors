from dataclasses import replace
from importlib.metadata import entry_points

import jsonschema
import pytest

from outcomeci_connectors.provider import Download
from outcomeci_connectors.providers.google.drive import (
    EXPORT_TYPES,
    FILE_PATH,
    PROVIDER,
    READ_SCOPE,
    WRITE_SCOPE,
)


def test_registered_google_module_and_auth():
    registered = {item.name: item.load() for item in entry_points(group="outcomeci.connectors")}
    assert registered["google.drive"] is PROVIDER
    contract = PROVIDER.contract()
    assert contract["name"] == "google.drive"
    assert contract["base_url"] == "https://www.googleapis.com"
    oauth, service, token = contract["auth"]["accepts"]
    assert oauth["scopes"] == [READ_SCOPE]
    assert oauth["optional_scopes"] == [WRITE_SCOPE]
    assert oauth["authorization_parameters"] == {"access_type": "offline", "prompt": "consent"}
    assert oauth["pkce"] is True
    assert service["scopes"] == [READ_SCOPE, WRITE_SCOPE]
    assert token["kind"] == "token"
    assert token["header"] == "Authorization"
    assert token["scheme"] == "Bearer"


def test_only_fixed_bounded_operations_no_arbitrary_request_or_permissions():
    operations = PROVIDER.contract()["operations"]
    assert set(operations) == {
        "files.list",
        "files.get",
        "files.download",
        "files.export",
        "folders.create",
        "files.update",
    }
    for name, operation in operations.items():
        jsonschema.Draft202012Validator.check_schema(operation["input"])
        assert operation["input"]["additionalProperties"] is False
        assert "methods" not in operation["request"]
        assert operation["side_effect"] == {
            "folders.create": "create",
            "files.update": "update",
        }.get(name, "read")


def test_list_is_constrained_to_direct_folder_children():
    operation = PROVIDER.contract()["operations"]["files.list"]
    assert operation["grantable"] == {"folder_id": {"field": "folder_id"}}
    request = operation["request"]
    assert request["path"] == "/drive/v3/files"
    assert request["query"]["q"] == "'{{ input.folder_id }}' in parents and trashed = false"
    assert request["query"]["supportsAllDrives"] is True
    assert request["query"]["includeItemsFromAllDrives"] is True
    assert operation["response"]["expose"]["next_page_token"] == "body.nextPageToken"
    jsonschema.validate(
        {"folder_id": "folder_example-1", "page_size": 100, "page_token": ""}, operation["input"]
    )


@pytest.mark.parametrize("operation", ["files.get", "files.download", "files.export"])
def test_reads_fetch_metadata_first_and_validate_folder_membership(operation):
    contract = PROVIDER.contract()["operations"][operation]
    assert contract["request"]["method"] == "GET"
    assert contract["request"]["path"] == FILE_PATH
    assert "parents" in contract["request"]["query"]["fields"]
    assert contract["grantable"] == {
        "file_id": {"field": "file_id"},
        "folder_id": {"response_in": ["body.parents"]},
    }
    assert "exportLinks" not in str(contract["response"]["expose"])


def test_content_download_and_export_are_bounded_same_origin_requests():
    operations = PROVIDER.contract()["operations"]
    download = operations["files.download"]["response"]["download"]
    export = operations["files.export"]["response"]["download"]
    assert download == {
        "path": FILE_PATH,
        "query": {"alt": "media", "supportsAllDrives": True},
        "hosts": ["www.googleapis.com"],
        "name": "body.name",
        "content_type": "body.mimeType",
        "max_bytes": 20 * 1024 * 1024,
    }
    assert export == {
        **download,
        "path": FILE_PATH + "/export",
        "query": {"mimeType": "{{ input.mime_type }}"},
        "content_type": "input.mime_type",
        "max_bytes": 10 * 1024 * 1024,
    }
    for mime in EXPORT_TYPES:
        jsonschema.validate(
            {"file_id": "file_example", "mime_type": mime},
            operations["files.export"]["input"],
        )


def test_writes_scope_targets_before_the_request():
    create = PROVIDER.contract()["operations"]["folders.create"]
    update = PROVIDER.contract()["operations"]["files.update"]
    assert create["request"]["body"]["parents"] == ["{{ input.folder_id }}"]
    assert create["request"]["body"]["mimeType"] == "application/vnd.google-apps.folder"
    assert create["grantable"] == {"folder_id": {"field": "folder_id"}}
    assert update["request"]["body"] == "{{ input.metadata }}"
    assert update["grantable"] == {"file_id": {"field": "file_id"}}
    jsonschema.validate({"file_id": "example", "metadata": {"name": "Renamed"}}, update["input"])
    jsonschema.validate({"file_id": "example", "metadata": {"description": ""}}, update["input"])


@pytest.mark.parametrize(
    "identifier",
    ["../other", "a/b", "a?alt=media", "a#x", "a' or 'b", "a\n", "a%2fb", "", "a" * 257],
)
@pytest.mark.parametrize("operation,field", [("files.get", "file_id"), ("files.list", "folder_id")])
def test_identifiers_cannot_escape_request_path_or_parent_query(identifier, operation, field):
    value = {field: identifier}
    if operation == "files.list":
        value.update(page_size=10, page_token="")
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(value, PROVIDER.operations[operation].input)


@pytest.mark.parametrize(
    "operation,value",
    [
        ("files.list", {"folder_id": "example", "page_size": 101, "page_token": ""}),
        (
            "files.list",
            {"folder_id": "example", "page_size": 1, "page_token": "", "q": "trashed = false"},
        ),
        ("files.list", {"folder_id": "example", "page_size": 1, "page_token": "a" * 4097}),
        ("files.export", {"file_id": "example", "mime_type": "application/x-unknown"}),
        ("files.update", {"file_id": "example", "metadata": {"trashed": True}}),
        ("files.update", {"file_id": "example", "metadata": {"parents": ["other"]}}),
        ("files.update", {"file_id": "example", "metadata": {}}),
        (
            "folders.create",
            {"folder_id": "example", "name": "folder", "description": "", "permissions": []},
        ),
    ],
)
def test_refuses_unbounded_or_unsupported_operations(operation, value):
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(value, PROVIDER.operations[operation].input)


def test_legacy_response_download_contract_is_unchanged():
    assert Download(
        url="body.url", hosts=("example.test",), name="body.name", content_type="body.type"
    ).contract() == {
        "url": "body.url",
        "hosts": ["example.test"],
        "name": "body.name",
        "content_type": "body.type",
        "max_bytes": 20 * 1024 * 1024,
    }


@pytest.mark.parametrize(
    "patch",
    [
        {"url": "body.url"},
        {"path": None},
        {"path": "https://other.test/file"},
        {"path": "//other.test/file"},
        {"path": "/files/../secret"},
        {"path": "/files?key=secret"},
        {"path": "/files#fragment"},
        {"path": "/files\\secret"},
        {"path": "/files/{{ body.secret }}"},
        {"query": {"x": "{{ secret }}"}},
        {"query": {"x": {"nested": "value"}}},
        {"max_bytes": 101 * 1024 * 1024},
        {"content_type": "secrets.token"},
        {"name": "input.name"},
    ],
)
def test_request_download_refuses_ambiguous_or_untrusted_targets(patch):
    with pytest.raises(ValueError):
        replace(PROVIDER.operations["files.download"].download, **patch)


def test_request_download_without_query_serializes_empty_query():
    contract = replace(PROVIDER.operations["files.download"].download, query=None).contract()
    assert contract["query"] == {}
    assert "url" not in contract
