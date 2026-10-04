"""The credential kinds a provider's API accepts.

A workflow names a credential, never an auth method: `auth: secrets.github`.
The runtime resolves that secret from the Vault and reads the method from the
credential itself: a plain value is a token, and a typed credential carries its
`credential_type`. A provider declares which kinds its API accepts, in order
of preference, and the fixed parameters it knows for each one, such as a token
endpoint or the header an API key goes in, so a user never types them.

Each kind lists `credential`: the fields the credential supplies, secrets and
account-specific values alike. Everything else in a kind's contract is fixed
by the provider and takes precedence over the credential's configuration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

GRANT_TYPES = {"client_credentials", "refresh_token"}
CLIENT_AUTH = {"basic", "body"}


def _https(value: str, name: str) -> None:
    if not value.startswith("https://"):
        raise ValueError(f"{name} must be an https URL")


@dataclass(frozen=True)
class NoAuth:
    """The API takes no credential. A workflow binds it without `auth`."""

    kind: ClassVar[str] = "none"

    def contract(self) -> dict[str, Any]:
        return {"kind": self.kind, "credential": []}


@dataclass(frozen=True)
class Token:
    """A static token sent as `<header>: <scheme> <token>`, such as a bearer token.

    A plain Vault value is this kind, as is an `auth_header` credential.
    """

    kind: ClassVar[str] = "token"
    header: str = "Authorization"
    scheme: str = "Bearer"
    description: str = ""

    def __post_init__(self) -> None:
        if not self.header:
            raise ValueError("a token names the header it is sent in")

    def contract(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "description": self.description,
            "credential": ["value"],
            "header": self.header,
            "scheme": self.scheme,
        }


@dataclass(frozen=True)
class ApiKey:
    """A static key sent in one header, or in one query parameter.

    With a header, the value is `<scheme> <key>` when `scheme` is set, else the
    bare key. The Vault holds it as an `api_key` credential.
    """

    kind: ClassVar[str] = "api_key"
    header: str | None = None
    query: str | None = None
    scheme: str | None = None
    description: str = ""

    def __post_init__(self) -> None:
        if (self.header is None) == (self.query is None):
            raise ValueError("an api key goes in exactly one of a header or a query parameter")
        if self.scheme is not None and self.header is None:
            raise ValueError("only an api key sent in a header takes a scheme")

    def contract(self) -> dict[str, Any]:
        placement = {"header": self.header} if self.header else {"query": self.query}
        return {
            "kind": self.kind,
            "description": self.description,
            "credential": ["api_key"],
            **placement,
            "scheme": self.scheme,
        }


@dataclass(frozen=True)
class Basic:
    """HTTP Basic authentication from a username and password."""

    kind: ClassVar[str] = "basic"
    description: str = ""

    def contract(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "description": self.description,
            "credential": ["username", "password"],
        }


@dataclass(frozen=True)
class OAuth2:
    """An access token from an OAuth 2.0 token endpoint, sent as a bearer token.

    `grant_types` are the grants the runtime may run unattended:
    `client_credentials` (the credential holds a client id and secret) and
    `refresh_token` (it also holds a refresh token from an earlier
    authorization). `client_auth` is how the client id and secret reach the
    token endpoint: HTTP Basic, or form fields in the body. When
    `rotates_refresh_token` is set, every refresh returns a new refresh token
    and revokes the one it used, so the runtime writes the new one back to the
    credential before anything else uses it.

    `authorization_url` opts into the runtime's shared interactive account
    connection flow. It requires a refresh grant; `pkce` defaults
    to true for interactive connections. Confidential clients may explicitly disable
    PKCE when the provider does not support it. Unset metadata is omitted so existing
    provider contracts and digests do not change.
    """

    kind: ClassVar[str] = "oauth2"
    token_url: str
    grant_types: tuple[str, ...] = ("client_credentials",)
    scopes: tuple[str, ...] = ()
    optional_scopes: tuple[str, ...] = ()
    audience: str | None = None
    client_auth: str = "basic"
    rotates_refresh_token: bool = False
    description: str = ""
    authorization_url: str | None = None
    pkce: bool | None = None
    authorization_parameters: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _https(self.token_url, "token_url")
        if not self.grant_types or set(self.grant_types) - GRANT_TYPES:
            raise ValueError(f"oauth2 grant types are one or more of {sorted(GRANT_TYPES)}")
        if self.client_auth not in CLIENT_AUTH:
            raise ValueError(f"client_auth is one of {sorted(CLIENT_AUTH)}")
        if self.rotates_refresh_token and "refresh_token" not in self.grant_types:
            raise ValueError("only a refresh_token grant rotates its refresh token")
        if self.authorization_parameters:
            if not self.authorization_url or set(self.authorization_parameters) - {
                "access_type",
                "prompt",
                "include_granted_scopes",
            }:
                raise ValueError("unsupported authorization parameters")
            if not all(
                isinstance(value, str) and value for value in self.authorization_parameters.values()
            ):
                raise ValueError("authorization parameters require nonempty strings")
        if self.authorization_url is not None:
            _https(self.authorization_url, "authorization_url")
            if "refresh_token" not in self.grant_types:
                raise ValueError("interactive authorization requires a refresh_token grant")
        elif self.pkce is not None:
            raise ValueError("pkce requires authorization_url")
        if self.pkce is not None and type(self.pkce) is not bool:
            raise ValueError("pkce must be a boolean")
        if self.optional_scopes:
            if not self.authorization_url:
                raise ValueError("optional_scopes requires authorization_url")
            if (
                len(set(self.optional_scopes)) != len(self.optional_scopes)
                or set(self.optional_scopes) & set(self.scopes)
                or any(
                    not scope or any(c.isspace() for c in scope) for scope in self.optional_scopes
                )
            ):
                raise ValueError("optional_scopes must be unique scope names disjoint from scopes")

    def contract(self) -> dict[str, Any]:
        credential = ["client_id", "client_secret"]
        if "refresh_token" in self.grant_types:
            credential.append("refresh_token")
        return {
            "kind": self.kind,
            "description": self.description,
            "credential": credential,
            "token_url": self.token_url,
            "grant_types": list(self.grant_types),
            "scopes": list(self.scopes),
            **({"optional_scopes": list(self.optional_scopes)} if self.optional_scopes else {}),
            "audience": self.audience,
            "client_auth": self.client_auth,
            "rotates_refresh_token": self.rotates_refresh_token,
            **(
                {"authorization_parameters": dict(self.authorization_parameters)}
                if self.authorization_parameters
                else {}
            ),
            **(
                {
                    "authorization_url": self.authorization_url,
                    "pkce": self.pkce if self.pkce is not None else True,
                }
                if self.authorization_url is not None
                else {}
            ),
        }


@dataclass(frozen=True)
class OIDC:
    """OAuth 2.0 client credentials against an OpenID Connect issuer.

    The runtime reads the token endpoint from the issuer's discovery document,
    `<issuer>/.well-known/openid-configuration` unless `discovery_url` names
    another. An issuer that varies per account, such as a tenant, is left
    unset and comes from the credential's `issuer_url`.
    """

    kind: ClassVar[str] = "oidc"
    issuer: str | None = None
    discovery_url: str | None = None
    scopes: tuple[str, ...] = ()
    audience: str | None = None
    description: str = ""

    def __post_init__(self) -> None:
        if self.issuer is not None:
            _https(self.issuer, "issuer")
        if self.discovery_url is not None:
            _https(self.discovery_url, "discovery_url")

    def contract(self) -> dict[str, Any]:
        discovery = self.discovery_url
        if discovery is None and self.issuer is not None:
            discovery = self.issuer.rstrip("/") + "/.well-known/openid-configuration"
        credential = ["client_id", "client_secret"]
        if self.issuer is None and self.discovery_url is None:
            credential.insert(0, "issuer_url")
        return {
            "kind": self.kind,
            "description": self.description,
            "credential": credential,
            "issuer": self.issuer,
            "discovery_url": discovery,
            "scopes": list(self.scopes),
            "audience": self.audience,
        }


@dataclass(frozen=True)
class JwtBearer:
    """The RFC 7523 JWT bearer grant: the runtime signs a short-lived RS256 JWT
    with the credential's private key and exchanges it at `token_url`
    (grant_type `urn:ietf:params:oauth:grant-type:jwt-bearer`) for an access
    token, sent as a bearer token. The JWT's `aud` is `audience`, else
    `token_url`.
    """

    kind: ClassVar[str] = "jwt_bearer"
    token_url: str
    audience: str | None = None
    scopes: tuple[str, ...] = ()
    description: str = ""
    subject_required: bool = True

    def __post_init__(self) -> None:
        _https(self.token_url, "token_url")

    def contract(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "description": self.description,
            "credential": [
                "issuer",
                *(["subject"] if self.subject_required else []),
                "private_key",
            ],
            "token_url": self.token_url,
            "audience": self.audience,
            "scopes": list(self.scopes),
            "algorithm": "RS256",
        }


@dataclass(frozen=True)
class AppInstallation:
    """An app installation token, the way a GitHub App authenticates.

    Not an OAuth grant. The runtime signs a JWT with the app's private key
    (`algorithm`; claims `iss` = the credential's `app_id`, `iat` 60 seconds in
    the past, `exp` at most `jwt_lifetime_seconds` after that), POSTs to
    `token_url` with `installation_id` filled in from the credential and the
    JWT as `Authorization: Bearer <jwt>`, and reads the installation token from
    `token_field` and its expiry from `expires_field` in the JSON response. It
    sends that token as `Authorization: <scheme> <token>` until it expires.
    """

    kind: ClassVar[str] = "app_installation"
    token_url: str
    algorithm: str = "RS256"
    jwt_lifetime_seconds: int = 600
    token_field: str = "token"
    expires_field: str = "expires_at"
    scheme: str = "Bearer"
    headers: tuple[tuple[str, str], ...] = ()
    description: str = ""

    def __post_init__(self) -> None:
        _https(self.token_url, "token_url")
        if "{installation_id}" not in self.token_url:
            raise ValueError("an app installation token_url names {installation_id}")
        if self.algorithm != "RS256":
            raise ValueError("app installation JWTs are RS256")
        if not 0 < self.jwt_lifetime_seconds <= 600:
            raise ValueError("an app JWT lives at most 600 seconds")

    def contract(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "description": self.description,
            "credential": ["app_id", "installation_id", "private_key"],
            "token_url": self.token_url,
            "method": "POST",
            "headers": dict(self.headers),
            "algorithm": self.algorithm,
            "jwt_lifetime_seconds": self.jwt_lifetime_seconds,
            "token_field": self.token_field,
            "expires_field": self.expires_field,
            "scheme": self.scheme,
        }


Auth = NoAuth | Token | ApiKey | Basic | OAuth2 | OIDC | JwtBearer | AppInstallation
KINDS = {
    item.kind for item in (NoAuth, Token, ApiKey, Basic, OAuth2, OIDC, JwtBearer, AppInstallation)
}


def check_accepts(accepts: tuple[Auth, ...]) -> None:
    """A provider accepts at least one kind, each at most once, and `none` alone."""
    if not accepts:
        raise ValueError("a provider accepts at least one credential kind, or NoAuth()")
    kinds = [item.kind for item in accepts]
    if len(set(kinds)) != len(kinds):
        raise ValueError("a provider accepts each credential kind at most once")
    if "none" in kinds and len(kinds) > 1:
        raise ValueError("a provider that takes no credential accepts nothing else")


def auth_contract(accepts: tuple[Auth, ...]) -> dict[str, Any]:
    return {"accepts": [item.contract() for item in accepts]}
