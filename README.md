# outcomeci/connectors

The providers an [OutcomeCI](https://outcomeci.com) workflow can connect to,
kept in their own repository so they can be reviewed, versioned and released
independently of the runtime.

A provider is data plus pure functions. It never makes a request or holds a
secret: the OutcomeCI runtime executes every call through its credential
broker, which journals it. An `outcomeci.workflow/v1` workflow names a provider
with `uses:`, and the cli finds installed providers through the
`outcomeci.connectors` entry point group.

## Request a connector

Missing a service or an operation? [Request a connector](https://github.com/outcomeci/connectors/issues/new?template=connector-request.yml)
and tell us what you want your workflow to do.

## Layout

```
outcomeci_connectors/
  provider.py          # Provider, Operation, Grantable, Deny, Compare, Download, Watcher, Receiver
  auth.py              # the credential kinds a provider accepts
  providers/
    slack/
      __init__.py      # PROVIDER: post, thread, file, reactions; reaction and reply watchers
      messages.py      # the files and subtypes a message carries
      receiver.py      # signed Events API requests to a workflow trigger
      setup.py         # app manifest, Slack CLI setup and status
    github.py          # PROVIDER: read, search and write, scoped by repo
    linkedin.py        # PROVIDER: OAuth with selectable approved app scopes
    x.py               # PROVIDER: recent-post search and user-authorized text publishing
```

Each provider package owns everything about its provider:

- **Operations:** what `uses: <provider>` resolves to, with input shapes,
  request templates and response mapping.
- **Auth:** the credential kinds the API accepts, in order of preference, with
  the fixed parameters the provider knows, such as a token endpoint or the
  header a key goes in. A workflow names only a credential
  (`auth: secrets.github`), and the runtime takes the method from that
  credential. Slack accepts a bot token, or a refresh token for an app with
  token rotation; GitHub accepts a personal access token, a GitHub App
  installation, or an authorized OAuth account.
- **Grant vocabulary:** which arguments a grant may scope, such as a Slack
  `channel` or `thread_ts`, or a GitHub `repo`, and the requests an operation
  refuses whatever the grant. A grant pins an input field, bounds a request
  path, or, for a resource whose request cannot name its scope, requires the
  granted value in the response: a Slack file is readable only where it is
  shared.
- **Downloads:** the file a response points to, fetched with the same
  credential from the hosts the provider names and saved for the agent to
  open, such as a screenshot attached to a Slack message.
- **Watchers:** the match logic behind `await` and `converse`, such as an
  emoji reaction or a human reply in a thread. The runtime owns the loop,
  timeouts and durability.
- **Receiver:** how the provider's own inbound request becomes a workflow
  trigger: verifying it, answering a URL handshake, ignoring what should not
  start a run, and the event id a redelivery is deduplicated on. For Slack,
  signed @mentions and direct messages, top-level only.
- **Setup:** for Slack, generating an app manifest with only the scopes the
  operations use and an event subscription to the workflow's webhook URL,
  then driving the Slack CLI to create and install the app (the
  `oci integration slack setup`, `manifest` and `status` commands).

The runtime reads a provider through `Provider.contract()`, the versioned
`outcomeci.connector/v1` document, and locks its digest into each workflow
revision. The contract's `auth` field is `{"accepts": [...]}`, one entry per
accepted kind:

```json
{"kind": "token", "description": "...", "credential": ["value"],
 "header": "Authorization", "scheme": "Bearer"}
```

## X search and publishing

Use `uses: x` with a Vault `token` credential containing your X app's bearer
token. No client ID or client secret is needed for search-only access. Your X
account must have recent-search access and sufficient API credits; X usage
is billed separately from OutcomeCI.

Grant `x.search_recent` to search the last seven days. Calls require `query`
and `max_results` (10–100). The operation returns one page, with `posts`,
expanded `authors`, `meta`, and any partial `errors`. Missing result fields
may be null; inspect errors before treating an empty response as no matches.
Post links can be built as `https://x.com/i/status/<id>`.

Search does not automatically paginate. Neither operation likes, follows, or reads DMs.
It allows at most ten requests per provider budget. Pin `query` and
`max_results` in a grant to constrain a workflow's search and page size:

```yaml
secrets:
  x: vault:x/bearer-token
apis:
  x: {uses: x, auth: secrets.x}
# Within an agent step:
# can:
#   - x.search_recent: {query: '"agent workflows" -is:retweet lang:en', max_results: 10}
```

See [X's recent-search reference](https://docs.x.com/x-api/posts/search-recent-posts).
The connector must be released and installed in the API/compiler and runner
before a cloud workflow can use it. Existing Slack and GitHub contracts are unchanged.

### Connect an account to publish

Publishing requires an X **user-authorized OAuth credential**, not an app-only
bearer token. Configure your X app as a confidential Web App or automated bot,
enable OAuth 2.0 and register the exact callback URL shown by OutcomeCI's
connection flow. Enter the app's client ID and secret through the secure
connection form, then authorize the account that should publish. Do not paste
credentials into agent conversations.

The connector declares the authorization endpoint, token endpoint and scopes:
`tweet.read`, `tweet.write`, `users.read`, and `offline.access`. These allow
reading and posting as the account and keeping that connection refreshed.
The shared runtime performs the consent flow with PKCE S256 and stores the
result in Vault; no X-specific authorization handler is required.

Grant `x.post` separately from `x.search_recent`. Its input is `text` (1–280
characters), plus optional `reply: {in_reply_to_tweet_id: "..."}`. It returns
`id` and `text`. X additionally enforces its weighted character limit; media
and quote posts are not supported. Pin the `text` and `reply` grant arguments
to constrain approved content and target. The connector does **not** add an
approval step automatically: put an explicit human approval before publishing.
Do not blindly retry timed-out publishing requests, which may already have
created a post.

X restricts self-serve replies to eligible conversations, including where the
original author mentioned the account or quoted one of its posts. Search
results alone do not establish reply eligibility. Manual replies may therefore
be the appropriate action for growth recommendations.

References: [OAuth authorization](https://docs.x.com/fundamentals/authentication/oauth-2-0/authorization-code),
[confidential client exchange](https://docs.x.com/fundamentals/authentication/oauth-2-0/user-access-token),
[publishing and reply restrictions](https://docs.x.com/x-api/posts/manage-tweets/introduction).

## Adding a connector

[CONTRIBUTING.md](CONTRIBUTING.md) is the authoring guide, for people and
coding agents: file layout, operations, grantables, deny rules, compared writes, watchers,
receivers, auth declarations with an example of each kind, testing and the
review bar.

## Development

```
pip install -e '.[test]'
pytest
ruff check .
```

## Releases

Every merge to `main` releases automatically. `.github/workflows/publish.yml`
reads the conventional commits since the last `vX.Y.Z` tag: `fix:` releases a
patch, `feat:` a minor version, and while the version is 0.x a breaking change
(`feat!:`) is a minor version too. Commits such as `docs:` or `ci:` release
nothing. The workflow tests, builds with `python -m build` (hatch-vcs reads the
version from the tag), publishes to PyPI through trusted publishing with no
stored token, pushes the tag and creates a GitHub release with generated
notes. Pushing a `vX.Y.Z` tag by hand releases that exact version the same way.

## GitHub account authorization

In Vault, choose **Add connection → GitHub → Authorize account**. Register a
GitHub.com OAuth app with the exact callback URL shown in the form, then enter
its client ID and client secret. PAT and GitHub App installation remain separate
options.

The OAuth flow uses PKCE S256 and requests `repo` plus `offline_access`. `repo`
gives repository access as the authorizing user; use a fine-grained PAT or GitHub
App installation when narrower provider permissions are needed. Workflow grants
still restrict what each step can do. `offline_access` requests expiring access
tokens and rotating refresh tokens. Vault stores the client secret and refresh
token encrypted, and the runner persists refresh-token rotation before using a
new access token. Reconnect repeats authorization while keeping the Vault path
and workflow grants.

This targets GitHub.com. Older GitHub Enterprise Server releases may not support
PKCE or expiring OAuth tokens. Authorization is rejected if a refresh token or
the required repository scope is missing.

Roll out the updated connector, API OAuth exchange, and CLI runner together:
the API discovers this option from its installed connector package, and both
the authorization exchange and runner refresh request JSON from GitHub.

Reference: [GitHub OAuth authorization](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps).


### Slack app installation

The Slack connector supports a bot token or interactive app installation through
Vault. For installation, enable PKCE and token rotation in the Slack app’s OAuth
settings, register Vault’s public HTTPS callback, and provide the app’s client ID
and secret. Localhost redirects cannot request bot scopes with PKCE. Enabling
PKCE is a one-way Slack setting; its refresh tokens expire after 30 days.
See [Slack’s PKCE documentation](https://docs.slack.dev/authentication/using-pkce/).

Installation requests the bot permissions used by the connector’s operations.
Vault stores the encrypted refresh token and app secret; the runner refreshes
access tokens and persists replacement refresh tokens. Event subscriptions and
the signing secret still require the separate Slack trigger setup. Deploy the
connector, API, runner, and web changes together to expose Install app in Vault.

### Discovering setup credentials

`Provider.contract()` includes optional `setup.credentials` metadata for secrets
used by receivers, independently of the API authentication choices. These are
plain secret values, stored separately from bot tokens or OAuth credentials.
`required` applies only when using `used_by` (currently `receiver`); it does not
make event setup a prerequisite for outbound API calls. `suggested_path` is a
customizable default so multiple app connections can use separate paths.

No OutcomeCI web app or API is needed to inspect the declaration:

```python
from outcomeci_connectors.providers.slack import PROVIDER

for credential in PROVIDER.contract().get("setup", {}).get("credentials", []):
    print(credential["label"], credential["description"], credential["suggested_path"])
```

Use the existing local Vault commands to save the value interactively:

```sh
oci vault local init  # once per repository
oci vault local put slack/signing-secret
```

Reference `vault:slack/signing-secret` in the workflow's receiver binding. Any
other client or secret store can consume the same JSON declaration. It contains
metadata only, never credential values, and does not install event subscriptions.

### Google Analytics module

Bind `uses: google.analytics` to a Vault credential. Google modules share auth
helpers but declare their own API origin and scopes; Analytics is the first
module. It uses the GA4 Data API, not Universal Analytics or the Admin API.

```yaml
apiVersion: outcomeci.workflow/v1
trigger: manual
secrets:
  google: vault:google/analytics
apis:
  analytics: {uses: google.analytics, auth: secrets.google}
steps:
  - summarize:
      reason: Summarize active users over the last seven days.
      can:
        - analytics.report: {property: "123456789"}
        - analytics.metadata: {property: "123456789"}
```

Operations are `report`, `realtime`, and `metadata`. Reports take a `report`
object containing metrics, optional dimensions, and an explicit string `limit`
(up to `"10000"`). Historical reports also require `dateRanges` and support a
string `offset` for pagination. This initial module exposes basic reports and
metadata, not filters, pivots, cohorts, administration, or property discovery.
Property IDs are numeric strings; the runtime enforces each property grant.

Enable the Google Analytics Data API in your Cloud project. Either authenticate
as a user with property access, or add a service account’s email to the GA4
property with Viewer access. Only `analytics.readonly` is requested.

- **OAuth:** use a web OAuth client with the callback shown by Vault. The
  declaration requests offline access and consent so a refresh token is issued.
  For headless/local use, obtain a refresh token through your own OAuth client,
  then store `client_secret` and `refresh_token` as an `oauth2` credential with
  `client_id` and `grant_type=refresh_token`. No OutcomeCI API is needed to use it.
- **Service account:** upload the downloaded JSON key in Vault, or use the
  existing local Vault command with the email as `issuer` and the private key:

```sh
jq -r '.private_key' service-account.json |
  oci vault local put google/analytics --credential-type jwt_bearer \
    --issuer service-account@project.iam.gserviceaccount.com --value-stdin
```

The connector fixes the token endpoint and scope. Google service accounts do
not require a subject or domain-wide delegation for access to a GA4 property.
The runtime signs an RS256 assertion, exchanges it for an access token, and
caches the token; OAuth credentials use the existing refresh flow.

References: [GA4 quickstart](https://developers.google.com/analytics/devguides/reporting/data/v1/quickstart),
[report API](https://developers.google.com/analytics/devguides/reporting/data/v1/rest/v1beta/properties/runReport),
[OAuth](https://developers.google.com/identity/protocols/oauth2/web-server), and
[service accounts](https://developers.google.com/identity/protocols/oauth2/service-account).

## LinkedIn account authorization

Use your own LinkedIn developer app's client ID and secret. Register the callback
URL shown by your client. Choose only scopes listed in your app's Auth tab;
all twelve Community Management scopes are available in the connector's
`auth.accepts[].optional_scopes`. None are requested automatically. Clients must
request at least one, persist the chosen subset in the credential's `scopes`,
and verify the consent response grants that subset. Required `scopes` on other
providers remain unchanged. The CLI's existing OAuth broker uses the credential's
configured scopes when the provider has no fixed scopes.

This connector establishes OAuth credentials only; it does not yet expose
LinkedIn API operations. It uses LinkedIn's confidential-client web flow with
client-secret authentication and state protection, without PKCE. LinkedIn's
separate native-PKCE flow is not used. Programmatic refresh-token access requires
LinkedIn approval; Community Management scope approval alone does not prove it.
Apps without refresh-token access cannot use this unattended connection flow.
Refresh tokens expire on LinkedIn's schedule and require reauthorization.

## GitHub webhook triggers

GitHub App and repository webhooks can use the same verified receiver:

```yaml
trigger:
  webhook:
    uses: github
    auth: secrets.github_webhook
    events: [issues, issue_comment, pull_request]

secrets:
  github_webhook: vault:github/webhook-secret
```

Save the webhook secret as a plain Vault value and grant it to the workflow.
Use the identical secret in GitHub's webhook settings, set the payload format
to JSON for repository webhooks, and point the webhook URL at the workflow's
production webhook URL. Subscribe to the matching events in GitHub; install
GitHub Apps on the repositories you want to receive events from. This secret
is separate from an API token or GitHub App private key. The connector's setup
metadata exposes it to clients without requiring the OutcomeCI UI.

The receiver verifies `X-Hub-Signature-256` against the original body bytes
before parsing or accepting any event, including pings. Signed pings are
acknowledged without starting a run. Supported events are `push`, `issues`,
`issue_comment`, `pull_request`, `pull_request_review`,
`pull_request_review_comment`, `check_run`, `check_suite`, `workflow_run`, and
`release`. All actions within a selected event are delivered; inspect
`trigger.payload.action` in the workflow when only certain actions matter.

The trigger contains `event`, `delivery_id`, and `payload` (the original JSON
object). For example, use `trigger.payload.repository.full_name` for the
repository and `trigger.payload.issue.number` for an issue. This differs from
an unverified generic webhook's `body_base64` envelope; update workflows when
switching their trigger to this receiver.

The runtime deduplicates redeliveries using `X-GitHub-Delivery`. GitHub does not
sign a timestamp or its event/delivery headers, so this does not provide
Slack's five-minute freshness check or prevent replays with altered headers.
Keep the webhook URL private. Outbound GitHub API credentials still need their
own workflow grants.

After deploying a release containing this receiver to the API and runtime,
recompile and sync the workflow so its pinned connector contract includes it.
Test a matching event in GitHub and check both Recent deliveries and the
OutcomeCI run. A successful webhook response confirms receipt, not completion.
