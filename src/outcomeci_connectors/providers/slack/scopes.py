"""Bot permissions shared by app installation and trigger setup."""

# post: chat:write. thread: the history scope of each conversation type.
# file: files:read. reactions: reactions:read. channels and members: the read
# scope of each channel type. usergroups and usergroup_members:
# usergroups:read. user_by_email: users:read.email.
OPERATION_SCOPES = (
    "channels:history",
    "channels:read",
    "chat:write",
    "files:read",
    "groups:history",
    "groups:read",
    "im:history",
    "mpim:history",
    "reactions:read",
    "usergroups:read",
    "users:read",
    "users:read.email",
)
