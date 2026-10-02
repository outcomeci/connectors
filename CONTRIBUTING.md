# Adding a connector

This guide is for anyone adding or changing a provider, people and coding
agents alike. A connector request usually starts as a GitHub issue naming an
API; the pull request that answers it follows the steps below and meets the
review bar at the end.

## What a provider is

A provider is data plus pure functions. It never makes a network call, never
reads the environment and never holds a secret. The OutcomeCI runtime executes
every request through its credential broker, which enforces grants and deny
rules and journals each call. The runtime reads a provider only through
`Provider.contract()`, a JSON document versioned `outcomeci.connector/v1`, and
locks its digest into each workflow revision.

A workflow binds a provider like this:

```yaml
apis:
  acme:
    uses: acme
    auth: secrets.acme
```

The workflow names a credential, never an auth method. The runtime takes the
method from the credential the secret resolves to, and the provider says which
methods its API accepts.

## File layout

A provider with only operations is one module; a provider with a receiver,
watchers or setup tooling is a package.

```
src/outcomeci_connectors/providers/
  acme.py                # PROVIDER = Provider(...)
  acme/                  # or, for a larger provider:
    __init__.py          # PROVIDER, watcher match functions
    receiver.py          # RECEIVER = Receiver(...)
    setup.py             # app manifests and install tooling, if any
tests/
  test_acme.py
```

Register it as an entry point in `pyproject.toml` so the cli finds it:

```toml
[project.entry-points."outcomeci.connectors"]
acme = "outcomeci_connectors.providers.acme:PROVIDER"
```

The entry point name is what `uses:` names. Keep it the provider's own lowercase
name.

## Operations

An `Operation` is one thing a workflow can be granted. There are two shapes.

A fixed operation sends one method to one path, with `query` and `body`
templates rendered from the call's input. `expose` maps output names to
response paths.

```python
"post": Operation(
    description="Post one message to a channel.",
    method="POST",
    path="/api/messages",
    input={
        "type": "object",
        "required": ["channel", "text"],
        "properties": {
            "channel": {"type": "string", "minLength": 1},
            "text": {"type": "string", "minLength": 1, "maxLength": 4000},
        },
        "additionalProperties": False,
    },
    body="{{ input }}",
    expose={"id": "body.id"},
    side_effect="create",
    grantable={"channel": Grantable(field="channel")},
),
```

A request operation (`methods`, no `path`) lets the agent choose the method and
path within `base_url`. Use it for broad REST access, and pair it with a
grantable path prefix and deny rules.

Rules for operations:

- `description` is what the agent reads. Say what the operation does, what it
  returns and what it refuses.
- `input` is a JSON Schema with `additionalProperties: false` and bounds on
  strings the API bounds.
- `side_effect` is the strongest effect the operation can have: `read`,
  `create`, `update`, `delete` or `execute` (a request operation that writes).
- Expose only what a workflow needs. Never expose a URL that carries a
  credential; fetch it with `download` instead.
- `download` saves the file a response points to, fetched with the same
  credential from `hosts` only, up to `max_bytes`. Only a fixed operation
  downloads.

## Grantables

A grant scopes an operation to a value, such as one channel or one repository.
Each `Grantable` sets exactly one of:

- `field`: the call's input field must equal the granted value, and the runtime
  fills it in when the agent leaves it out.
- `path_prefix`: a path template, formatted with the granted value's
  `value_fields`, that the request path must equal or sit under, such as
  `"/repos/{owner}/{name}"`.
- `response_in`: response paths of lists, one of which must contain the
  granted value, for a resource whose request cannot name its scope. The
  runtime checks it before it does anything else with the response.
- `query_qualifier`: a `QueryQualifier` for a request operation's search
  query parameter (`param`, such as `"q"`). Its `term`, a qualifier template
  formatted with the granted value's `value_fields`, such as
  `"repo:{owner}/{name}"`, must be one of the query's whitespace-separated
  terms, and the runtime appends it when the agent leaves it out. The query
  may hold no other qualifier named in `exclusive` (the names that set a
  search's scope, the term's own included) and none of the boolean
  `operators` that could widen or negate the term, such as `OR` and `NOT`.

## Deny rules

A request operation lists `Deny` rules for requests it refuses whatever the
grant allows: a `path` regular expression, optional `methods` (all methods
when empty) and a `reason` the agent sees. Deny account and repository
administration, permission changes, billing, destructive bulk actions and
anything that moves a protected resource, such as merging or force-updating a
branch. Test each rule with an allowed and a refused request.

## Compared writes

A request operation that writes files lists `Compare` rules, so a policy
reviewer sees each write as a diff against the file's current copy rather
than as the whole file. A rule matches a call by `methods` and a `path`
regular expression. For a write of one file, the runtime reads the current
copy with a GET to the same path, passing the request field `ref` (such as
`"body.branch"`) as the `ref` query parameter, and diffs the response's
`current` field against the request's `proposed` field. Both are body paths,
decoded with `encoding` (`"base64"` or `"text"`), or the current copy with
`current_encoding` when the two differ.

```python
FILE_WRITE = Compare(
    path=r"^/repos/[^/]+/[^/]+/contents/.+",
    proposed="body.content",
    current="body.content",
    ref="body.branch",
    encoding="base64",
)
```

A write of several files at once sets `entries`, the body path of the list of
files. In each entry, `entry_path` names the file and `proposed` its new
content, and an entry whose `deletion` field is present and null deletes the
file. The runtime reads each file's current copy with a GET to
`current_path`, formatted with the named groups of `path` and `{file}`, the
entry's file path. An entry with neither new content nor a deletion, such as
one that points at an existing blob, is noted rather than diffed.

```python
TREE_WRITE = Compare(
    path=r"^/repos/(?P<owner>[^/]+)/(?P<repo>[^/]+)/git/trees$",
    methods=("POST",),
    entries="body.tree",
    entry_path="path",
    proposed="content",
    deletion="sha",
    current_path="/repos/{owner}/{repo}/contents/{file}",
    current="body.content",
    encoding="text",
    current_encoding="base64",
)
```

## Watchers

A `Watcher` is the match logic behind `await` and `converse`: it names the
`operation` the runtime polls and a pure `match` function over that
operation's output. The runtime owns the loop, timeouts and durability. A
watcher that carries a conversation also names `respond` (the operation that
answers) with `thread_field` (the input field that holds the watched message's
id), and `attachment` (the operation that fetches a file a reply carries).

## Receiver

A `Receiver` turns the provider's inbound webhook into a workflow trigger.
`receive(headers, body, *, secret, events, now)` gets lowercased headers, the
raw body, the signing secret the workflow granted, the event names the
workflow asked for and the current Unix time, and returns a `Reception`:

- `reject` when the request does not prove it came from the provider. Verify
  the signature with `hmac.compare_digest` and refuse stale timestamps.
- `respond` with a `response` for a handshake, such as a URL challenge.
- `ignore` for anything that should not start a run.
- `trigger` with the run's input and an `event_id` stable across redeliveries.

`events` maps each event name a workflow can ask for to a description.

## Auth

`Provider.auth` lists the credential kinds the API accepts, in order of
preference, each with the fixed parameters the provider knows. A user never
types a token endpoint, a header name or a default scope: the provider
declares them. Declare every kind the API supports that the runtime can use
unattended, and only those. The default is `(Token(),)`.

The contract carries them as `auth.accepts`. Each entry has a `kind`, a
`description`, `credential` (the fields the credential supplies) and the fixed
parameters. The provider's parameters take precedence over the credential's
configuration.

| Kind | Class | Fixed parameters | The credential supplies |
|------|-------|------------------|-------------------------|
| `none` | `NoAuth()` | none | nothing |
| `token` | `Token()` | `header`, `scheme` | `value` |
| `api_key` | `ApiKey(...)` | `header` or `query`, `scheme` | `api_key` |
| `basic` | `Basic()` | none | `username`, `password` |
| `oauth2` | `OAuth2(...)` | `token_url`, `grant_types`, `scopes`, `audience`, `client_auth`, `rotates_refresh_token` | `client_id`, `client_secret`, and `refresh_token` for a refresh grant |
| `oidc` | `OIDC(...)` | `issuer` or `discovery_url`, `scopes`, `audience` | `client_id`, `client_secret`, and `issuer_url` when the issuer varies per account |
| `jwt_bearer` | `JwtBearer(...)` | `token_url`, `audience`, `scopes` | `issuer`, `subject`, `private_key` |
| `app_installation` | `AppInstallation(...)` | `token_url` with `{installation_id}`, `headers`, JWT and response fields | `app_id`, `installation_id`, `private_key` |

Examples of each:

```python
from outcomeci_connectors.provider import (
    OIDC,
    ApiKey,
    AppInstallation,
    Basic,
    JwtBearer,
    NoAuth,
    OAuth2,
    Token,
)

# A public API.
auth = (NoAuth(),)

# A bearer token: "Authorization: Bearer <token>".
auth = (Token(),)

# A token with another scheme: "Authorization: token <token>".
auth = (Token(scheme="token"),)

# An API key in a header, bare: "X-API-Key: <key>".
auth = (ApiKey(header="X-API-Key"),)

# An API key in the query string: "?api_key=<key>".
auth = (ApiKey(query="api_key"),)

# HTTP Basic from a username and password, such as an email and an API token.
auth = (Basic(),)

# OAuth 2.0 client credentials with default scopes.
auth = (
    OAuth2(
        token_url="https://auth.acme.test/oauth/token",
        grant_types=("client_credentials",),
        scopes=("read", "write"),
        audience="https://api.acme.test",
    ),
)

# A refresh token that the server rotates on every use.
auth = (
    OAuth2(
        token_url="https://acme.test/oauth/token",
        grant_types=("refresh_token",),
        client_auth="body",
        rotates_refresh_token=True,
    ),
)

# OpenID Connect client credentials against a fixed issuer.
auth = (OIDC(issuer="https://login.acme.test", scopes=("api",)),)

# OpenID Connect where each account has its own issuer, such as a tenant.
auth = (OIDC(),)

# The RFC 7523 JWT bearer grant, as a Google service account uses.
auth = (
    JwtBearer(
        token_url="https://oauth2.googleapis.com/token",
        scopes=("https://www.googleapis.com/auth/drive.readonly",),
    ),
)

# A GitHub App installation token.
auth = (
    AppInstallation(
        token_url="https://api.github.com/app/installations/{installation_id}/access_tokens",
    ),
)

# Several kinds, in order of preference.
auth = (Token(), OAuth2(token_url="https://acme.test/oauth/token"))
```

Rules for auth:

- Declare a kind only when the provider's documentation says the API accepts
  it, and link that documentation in a comment.
- `oauth2` grants are the ones the runtime runs unattended:
  `client_credentials` and `refresh_token`. Set `rotates_refresh_token` when
  each refresh revokes the refresh token it used, so the runtime stores the new
  one.
- An app that exchanges a signed JWT for a token at a provider-specific
  endpoint, as a GitHub App does, is `app_installation`, not `jwt_bearer`.
  `jwt_bearer` is the standard `urn:ietf:params:oauth:grant-type:jwt-bearer`
  grant only.
- Token endpoints, issuers and discovery URLs are https.
- `NoAuth()` stands alone.
- An API whose method fits none of these kinds needs a new kind in `auth.py`,
  with its parameters, validation and tests, and a matching change in the
  runtime. Say so in the pull request.

## Setup tooling

A provider whose credential comes from an app the user installs, as Slack's
does, can ship setup helpers in `setup.py`: an app manifest generated from the
scopes its operations use, and commands that drive the provider's own CLI.
Setup code may run subprocesses; `PROVIDER` and everything it references stay
pure.

## Testing

```
python -m venv .venv
.venv/bin/pip install -e '.[test]'
.venv/bin/pytest
.venv/bin/ruff check .
.venv/bin/ruff format --check .
```

A new provider's tests cover:

- The entry point loads `PROVIDER`.
- The contract of each operation: request, `expose`, `grantable`,
  `side_effect`, and `download` when present.
- Every deny rule, with a request it allows and one it refuses.
- Every watcher's `match` over realistic responses, including bots, the root
  message and empty output.
- A receiver's signature check, stale and forged requests, the handshake,
  ignored events and a stable `event_id`.
- `contract()["auth"]["accepts"]`, with each fixed parameter.

Use recorded or hand-written response bodies. Tests never reach the network.

## Review bar

A pull request that adds or changes a provider is ready when:

- Every operation, grantable, deny rule and auth kind is backed by the
  provider's public API documentation, linked in a comment where it is not
  obvious.
- Operations are the smallest set the issue needs. Write access sits behind a
  grantable scope and deny rules for administration and irreversible actions.
- Descriptions tell the agent what each operation returns and refuses.
- No secret, token, real workspace id or personal data is in code, tests or
  fixtures.
- The provider module makes no network call and reads no environment at
  import or in `PROVIDER`.
- Tests cover the list above, and `pytest`, `ruff check` and
  `ruff format --check` pass.
- The README layout lists the provider.
- A change to a provider's contract changes its digest, so workflows that
  locked the old digest see it. The pull request says what changed and why.
