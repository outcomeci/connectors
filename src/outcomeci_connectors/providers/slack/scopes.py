"""Bot permissions shared by app installation and trigger setup."""

# post: chat:write. thread: the history scope of each conversation type.
# file: files:read. reactions: reactions:read.
OPERATION_SCOPES = (
    "channels:history",
    "chat:write",
    "files:read",
    "groups:history",
    "im:history",
    "mpim:history",
    "reactions:read",
)
