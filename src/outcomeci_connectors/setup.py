"""Discoverable setup inputs, independent of any UI, API, or secret store."""

import re
from dataclasses import asdict, dataclass
from typing import Literal


@dataclass(frozen=True)
class SetupCredential:
    """A separate plain secret needed by a receiver, not API authentication.

    `required` applies when using `used_by`; it does not make this a prerequisite
    for outbound API calls. Suggested paths are defaults, never account IDs.
    """

    id: str
    label: str
    description: str
    suggested_path: str
    required: bool = True
    used_by: Literal["receiver"] = "receiver"
    secret: bool = True

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_]*", self.id):
            raise ValueError("setup credential id must be a stable identifier")
        if not self.label.strip() or not self.description.strip():
            raise ValueError("setup credentials need a label and description")
        if not re.fullmatch(r"[a-zA-Z0-9_-]+(?:/[a-zA-Z0-9_-]+)*", self.suggested_path):
            raise ValueError("setup credentials need a relative Vault path")
        if self.used_by != "receiver" or self.secret is not True:
            raise ValueError("setup credentials currently describe receiver secrets")

    def contract(self) -> dict:
        return asdict(self)
