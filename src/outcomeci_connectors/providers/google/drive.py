"""Bounded Google Drive file reads and app-authorized metadata writes."""

from ...provider import Download, Grantable, Operation, Provider
from .auth import authentication

READ_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
WRITE_SCOPE = "https://www.googleapis.com/auth/drive.file"
# drive.file applies to files created by or explicitly opened with the OAuth app,
# not every file in the user's Drive. Managed connections request scopes on demand.
# https://developers.google.com/workspace/drive/api/guides/api-specific-auth
ID = {"type": "string", "minLength": 1, "maxLength": 256, "pattern": r"^[A-Za-z0-9_-]+$(?![\s\S])"}
PAGE_TOKEN = {"type": "string", "maxLength": 4096}
NAME = {"type": "string", "minLength": 1, "maxLength": 255}
DESCRIPTION = {"type": "string", "maxLength": 4000}
FIELDS = (
    "id,name,mimeType,description,parents,size,modifiedTime,webViewLink,capabilities(canDownload)"
)
FILE_PATH = "/drive/v3/files/{{ input.file_id }}"
FILE_GRANTS = {
    "file_id": Grantable(field="file_id"),
    "folder_id": Grantable(response_in=("body.parents",)),
}
EXPOSE = {
    "id": "body.id",
    "name": "body.name",
    "mime_type": "body.mimeType",
    "description": "body.description",
    "parents": "body.parents",
    "size": "body.size",
    "modified_time": "body.modifiedTime",
    "web_view_link": "body.webViewLink",
}
# Supported formats vary by source type; Google refuses incompatible pairs.
# https://developers.google.com/workspace/drive/api/guides/ref-export-formats
EXPORT_TYPES = (
    "application/pdf",
    "text/plain",
    "text/csv",
    "text/tab-separated-values",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "image/png",
    "image/jpeg",
    "image/svg+xml",
)


def schema(properties, required):
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def file_read(description, *, export=False, download=False):
    """Metadata is fetched and response folder grants checked before content."""
    return Operation(
        description=description,
        method="GET",
        path=FILE_PATH,
        input=schema(
            {"file_id": ID, **({"mime_type": {"enum": list(EXPORT_TYPES)}} if export else {})},
            ["file_id", *(["mime_type"] if export else [])],
        ),
        query={"fields": FIELDS, "supportsAllDrives": True},
        expose=EXPOSE,
        grantable=FILE_GRANTS,
        download=Download(
            url=None,
            path=FILE_PATH + ("/export" if export else ""),
            query={"mimeType": "{{ input.mime_type }}"}
            if export
            else {"alt": "media", "supportsAllDrives": True},
            hosts=("www.googleapis.com",),
            name="body.name",
            content_type="input.mime_type" if export else "body.mimeType",
            max_bytes=(10 if export else 20) * 1024 * 1024,
        )
        if download or export
        else None,
    )


PROVIDER = Provider(
    name="google.drive",
    base_url="https://www.googleapis.com",
    auth=authentication((READ_SCOPE,), optional_scopes=(WRITE_SCOPE,)),
    max_requests=25,
    operations={
        # https://developers.google.com/workspace/drive/api/reference/rest/v3/files/list
        "files.list": Operation(
            description=(
                "List non-trashed direct children of one granted folder, including shared-drive "
                "items the account can access. Returns bounded metadata and next_page_token; "
                "pass an empty page_token for the first page. No recursive or arbitrary search."
            ),
            method="GET",
            path="/drive/v3/files",
            input=schema(
                {
                    "folder_id": ID,
                    "page_size": {"type": "integer", "minimum": 1, "maximum": 100},
                    "page_token": PAGE_TOKEN,
                },
                ["folder_id", "page_size", "page_token"],
            ),
            query={
                "q": "'{{ input.folder_id }}' in parents and trashed = false",
                "pageSize": "{{ input.page_size }}",
                "pageToken": "{{ input.page_token }}",
                "fields": f"nextPageToken,incompleteSearch,files({FIELDS})",
                "supportsAllDrives": True,
                "includeItemsFromAllDrives": True,
                "spaces": "drive",
            },
            expose={
                "files": "body.files",
                "next_page_token": "body.nextPageToken",
                "incomplete_search": "body.incompleteSearch",
            },
            grantable={"folder_id": Grantable(field="folder_id")},
        ),
        # https://developers.google.com/workspace/drive/api/reference/rest/v3/files/get
        "files.get": file_read(
            "Get one granted file's metadata, without content or permission lists. "
            "An optional folder grant requires the file to be a direct child."
        ),
        "files.download": file_read(
            "Download one granted binary file as a local artifact, up to 20 MiB. "
            "Folder membership is verified before downloading. Use files.export for Google "
            "Workspace documents. No abuse-warning bypass or redirect following.",
            download=True,
        ),
        # https://developers.google.com/workspace/drive/api/reference/rest/v3/files/export
        "files.export": file_read(
            "Export one granted Google Workspace document as a local artifact, up to 10 MiB. "
            "Choose a supported mime_type; Google rejects formats incompatible with the source. "
            "Folder membership is verified before exporting. No permission changes.",
            export=True,
        ),
        # https://developers.google.com/workspace/drive/api/reference/rest/v3/files/create
        "folders.create": Operation(
            description=(
                "Create a folder directly inside the granted parent folder. Requires drive.file "
                "and an app-authorized parent. Returns metadata; does not share or upload files."
            ),
            method="POST",
            path="/drive/v3/files",
            input=schema(
                {"folder_id": ID, "name": NAME, "description": DESCRIPTION},
                ["folder_id", "name", "description"],
            ),
            query={"fields": FIELDS, "supportsAllDrives": True},
            body={
                "name": "{{ input.name }}",
                "description": "{{ input.description }}",
                "mimeType": "application/vnd.google-apps.folder",
                "parents": ["{{ input.folder_id }}"],
            },
            expose=EXPOSE,
            side_effect="create",
            grantable={"folder_id": Grantable(field="folder_id")},
        ),
        # https://developers.google.com/workspace/drive/api/reference/rest/v3/files/update
        "files.update": Operation(
            description=(
                "Rename or change the description of one granted app-authorized file or folder. "
                "Requires drive.file. No content replacement, moving, trashing, deletion or "
                "sharing. Returns updated metadata."
            ),
            method="PATCH",
            path=FILE_PATH,
            input=schema(
                {
                    "file_id": ID,
                    "metadata": {
                        **schema({"name": NAME, "description": DESCRIPTION}, []),
                        "minProperties": 1,
                    },
                },
                ["file_id", "metadata"],
            ),
            query={"fields": FIELDS, "supportsAllDrives": True},
            body="{{ input.metadata }}",
            expose=EXPOSE,
            side_effect="update",
            # Do not offer a response-only folder guard for a write: checking it
            # after PATCH would be too late to prevent a cross-folder mutation.
            grantable={"file_id": Grantable(field="file_id")},
        ),
    },
)
