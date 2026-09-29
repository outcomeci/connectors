"""Declarative provider definitions: what `uses: <provider>` gives a workflow.

A provider is data plus pure functions. It never makes a network call and
never holds a secret: the OutcomeCI runtime executes every request through
its credential broker, which journals each call. A provider only describes
the operations a workflow may be granted, how a grant argument constrains a
call, how to read a watched response (a reaction or a reply), and how to turn
the provider's own inbound request into a workflow trigger.

The runtime reads a provider through `Provider.contract()`, a plain JSON
document versioned by `CONTRACT_VERSION`, so the runtime never depends on
these classes' shape. Its `auth` field is `{"accepts": [<kind>, ...]}`: the
credential kinds the API accepts, in order of preference, each with the
fixed parameters the provider knows (see `auth.py`).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from .auth import (
    OIDC,
    ApiKey,
    AppInstallation,
    Auth,
    Basic,
    JwtBearer,
    NoAuth,
    OAuth2,
    Token,
    auth_contract,
    check_accepts,
)

__all__ = [
    "CONTRACT_VERSION",
    "OIDC",
    "ApiKey",
    "AppInstallation",
    "Auth",
    "Basic",
    "Deny",
    "Download",
    "Grantable",
    "JwtBearer",
    "NoAuth",
    "OAuth2",
    "Operation",
    "Provider",
    "Reception",
    "Receiver",
    "Token",
    "Watcher",
]

CONTRACT_VERSION = "outcomeci.connector/v1"
ENTRY_POINT_GROUP = "outcomeci.connectors"
SIDE_EFFECTS = {"read", "create", "update", "delete", "execute"}


@dataclass(frozen=True)
class Grantable:
    """How one grant argument constrains a call.

    `field`: the call's input field must equal the granted value; the runtime
    fills it in when the agent leaves it out. `path_prefix`: a request path
    template, formatted with the granted value's fields, that the call's path
    must equal or sit under, e.g. "/repos/{owner}/{name}". `response_in`:
    response paths of lists, one of which must contain the granted value, for
    a resource whose request cannot name its scope, such as a file and the
    conversations it is shared in. The runtime checks it before anything else
    happens with the response, a download included.
    """

    field: str | None = None
    path_prefix: str | None = None
    value_fields: tuple[str, ...] = ()
    response_in: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        kinds = (self.field is not None, self.path_prefix is not None, bool(self.response_in))
        if sum(kinds) != 1:
            raise ValueError(
                "a grantable argument sets exactly one of field, path_prefix or response_in"
            )

    def contract(self) -> dict[str, Any]:
        if self.field is not None:
            return {"field": self.field}
        if self.response_in:
            return {"response_in": list(self.response_in)}
        return {"path_prefix": self.path_prefix, "value_fields": list(self.value_fields)}


@dataclass(frozen=True)
class Download:
    """The file a response points to, fetched with the same credential and saved
    where the agent can open it.

    `url`, `name` and `content_type` are response paths. The runtime fetches
    only an https URL on one of `hosts`, and at most `max_bytes`.
    """

    url: str
    hosts: tuple[str, ...]
    name: str
    content_type: str
    max_bytes: int = 20 * 1024 * 1024

    def __post_init__(self) -> None:
        if not self.hosts or self.max_bytes < 1:
            raise ValueError("a download names at least one host and a positive size limit")

    def contract(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "hosts": list(self.hosts),
            "name": self.name,
            "content_type": self.content_type,
            "max_bytes": self.max_bytes,
        }


@dataclass(frozen=True)
class Deny:
    """Requests an operation refuses whatever the grants allow.

    Applies to request operations: a call whose method is in `methods` (all
    methods when empty) and whose path matches the `path` regular expression
    is refused, with `reason` as the explanation.
    """

    path: str
    reason: str
    methods: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        re.compile(self.path)

    def contract(self) -> dict[str, Any]:
        return {"methods": sorted(self.methods), "path": self.path, "reason": self.reason}


@dataclass(frozen=True)
class Compare:
    """A write that replaces a file, shown to a policy reviewer as a diff.

    Applies to request operations: a call whose method is in `methods` and
    whose path matches the `path` regular expression. The runtime reads the
    current file with a GET to the same path, passing the request field `ref`
    (a request path such as "body.branch") as the `ref` query parameter, and
    diffs the response's `current` against the request's `proposed`. Both are
    decoded with `encoding` ("base64" or "text").
    """

    path: str
    proposed: str
    current: str
    methods: tuple[str, ...] = ("PUT",)
    ref: str | None = None
    encoding: str = "text"

    def __post_init__(self) -> None:
        re.compile(self.path)
        if self.encoding not in {"base64", "text"}:
            raise ValueError(f"unsupported encoding: {self.encoding}")
        if not all(
            value.startswith("body")
            for value in (self.proposed, self.current, *([self.ref] if self.ref else []))
        ):
            raise ValueError("compare fields are body paths")

    def contract(self) -> dict[str, Any]:
        return {
            "methods": sorted(self.methods),
            "path": self.path,
            "proposed": self.proposed,
            "current": self.current,
            "ref": self.ref,
            "encoding": self.encoding,
        }


@dataclass(frozen=True)
class Operation:
    """One grantable operation.

    A fixed operation sends `method` to `path`, with `query` and `body`
    templates rendered from the call's input ("{{ input.x }}", or "{{ input }}"
    for the whole input). A request operation (`methods` set, no `path`) lets
    the agent choose the method and path within the provider's origin.
    """

    description: str
    method: str | None = None
    path: str | None = None
    methods: tuple[str, ...] = ()
    input: Mapping[str, Any] = field(default_factory=lambda: {"type": "object"})
    query: Mapping[str, Any] | None = None
    body: Any = None
    expose: Mapping[str, str] = field(default_factory=lambda: {"result": "body"})
    side_effect: str = "read"
    grantable: Mapping[str, Grantable] = field(default_factory=dict)
    deny: tuple[Deny, ...] = ()
    download: Download | None = None
    compare: tuple[Compare, ...] = ()

    def __post_init__(self) -> None:
        fixed = self.method is not None and self.path is not None
        if self.download is not None and not fixed:
            raise ValueError("only a fixed operation can download")
        if self.compare and fixed:
            raise ValueError("only a request operation can compare")
        if fixed == bool(self.methods):
            raise ValueError(
                "an operation is either fixed (method and path) or a request (methods)"
            )
        if self.side_effect not in SIDE_EFFECTS:
            raise ValueError(f"unsupported side effect: {self.side_effect}")

    def contract(self) -> dict[str, Any]:
        request: dict[str, Any]
        if self.methods:
            request = {"methods": sorted(self.methods)}
        else:
            request = {"method": self.method, "path": self.path}
            if self.query is not None:
                request["query"] = dict(self.query)
            if self.body is not None:
                request["body"] = self.body
        return {
            "description": self.description,
            "input": dict(self.input),
            "request": request,
            "response": {
                "expose": dict(self.expose),
                **({"download": self.download.contract()} if self.download else {}),
            },
            "side_effect": self.side_effect,
            "grantable": {name: item.contract() for name, item in self.grantable.items()},
            "deny": [item.contract() for item in self.deny],
            **({"compare": [item.contract() for item in self.compare]} if self.compare else {}),
        }


@dataclass(frozen=True)
class Watcher:
    """Provider-specific match logic for a human signal the runtime waits on.

    The runtime owns the loop, timeouts and durability: it calls `operation`
    on the watched message and passes the result to `match`. A watcher that
    carries a conversation also names how to answer in it: the `respond`
    operation, with the watched message's id in `thread_field`. `attachment`
    names the operation that fetches a file a reply carries: the runtime calls
    it with `{"file": <id>}`, granted the watched message's `channel`.
    """

    operation: str
    match: Callable[..., Any]
    description: str = ""
    respond: str | None = None
    thread_field: str | None = None
    attachment: str | None = None


RECEPTIONS = {"reject", "respond", "ignore", "trigger"}


@dataclass(frozen=True)
class Reception:
    """What to do with one inbound request.

    `reject`: the request did not prove it came from the provider. `respond`:
    answer with `response` and start nothing, as for a URL handshake. `ignore`:
    acknowledge and start nothing. `trigger`: start a run with `trigger` as its
    input, once per `event_id` however often the provider redelivers it.
    """

    status: str
    reason: str = ""
    response: Mapping[str, Any] | None = None
    event_id: str | None = None
    trigger: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.status not in RECEPTIONS:
            raise ValueError(f"unsupported reception: {self.status}")
        if (self.status == "respond") != (self.response is not None):
            raise ValueError("a respond reception carries a response, and only it does")
        if (self.status == "trigger") != (self.trigger is not None and self.event_id is not None):
            raise ValueError("a trigger reception carries a trigger and an event_id")


@dataclass(frozen=True)
class Receiver:
    """Turns the provider's inbound HTTP request into a workflow trigger.

    `receive(headers, body, *, secret, events, now)` gets lowercased headers,
    the raw body bytes, the signing secret the workflow granted, the event
    names the workflow asked for (keys of `events`) and the current Unix time,
    and returns a `Reception`. The runtime owns the route, the secret and
    deduplication.
    """

    receive: Callable[..., Reception]
    events: Mapping[str, str]
    description: str = ""


@dataclass(frozen=True)
class Provider:
    """One API a workflow can bind with `uses: <name>`.

    `auth` lists the credential kinds the API accepts, in order of preference;
    the credential a workflow binds picks one at run time (see `auth.py`).
    """

    name: str
    base_url: str
    operations: Mapping[str, Operation]
    auth: tuple[Auth, ...] = (Token(),)
    max_requests: int = 50
    watchers: Mapping[str, Watcher] = field(default_factory=dict)
    receiver: Receiver | None = None

    def __post_init__(self) -> None:
        check_accepts(self.auth)
        for name, watcher in self.watchers.items():
            if watcher.operation not in self.operations:
                raise ValueError(f"watcher {name} reads unknown operation {watcher.operation}")
            if watcher.respond is not None and watcher.respond not in self.operations:
                raise ValueError(
                    f"watcher {name} responds with unknown operation {watcher.respond}"
                )
            if (watcher.respond is None) != (watcher.thread_field is None):
                raise ValueError(f"watcher {name} sets both respond and thread_field, or neither")
            if watcher.attachment is not None and watcher.attachment not in self.operations:
                raise ValueError(
                    f"watcher {name} fetches attachments with unknown operation "
                    f"{watcher.attachment}"
                )

    def contract(self) -> dict[str, Any]:
        return {
            "schema_version": CONTRACT_VERSION,
            "name": self.name,
            "base_url": self.base_url,
            "auth": auth_contract(self.auth),
            "max_requests": self.max_requests,
            "operations": {name: item.contract() for name, item in self.operations.items()},
            "watchers": {
                name: {
                    "operation": watcher.operation,
                    "description": watcher.description,
                    "respond": watcher.respond,
                    "thread_field": watcher.thread_field,
                    "attachment": watcher.attachment,
                }
                for name, watcher in self.watchers.items()
            },
            "receiver": None
            if self.receiver is None
            else {
                "description": self.receiver.description,
                "events": dict(self.receiver.events),
            },
        }

    def digest(self) -> str:
        """Content hash of the contract, recorded like a lock file entry.

        It covers everything the contract carries, the accepted credential
        kinds and their fixed parameters included, so a change to how a
        provider authenticates changes its digest.
        """
        encoded = json.dumps(self.contract(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode()).hexdigest()
