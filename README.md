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
    google/
      auth.py          # shared OAuth, service-account and bearer authentication
      analytics.py     # google.analytics: property-scoped GA4 reports
      drive.py         # google.drive: file reads, exports and bounded metadata writes
    github.py          # PROVIDER: read, search and write, scoped by repo
    linear/
      __init__.py      # PROVIDER: create, read and search issues by team; comment on an issue
      receiver.py      # signed webhooks: issue created, state changed, comment added
    linkedin.py        # PROVIDER: OAuth with selectable approved app scopes
    x.py               # PROVIDER: recent-post search and user-authorized text publishing
    tavily.py          # PROVIDER: bounded web search, domain grants and credit usage
    custom.py          # PROVIDER: the workflow's own HTTPS API, static auth, path-prefix grants
    media.py           # PROVIDER: platform-run processing of a trigger attachment; audio → transcript
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

## Tavily search

Bind `uses: tavily` to a Tavily API key stored as either a Vault `token` or
`api_key` credential. Both send `Authorization: Bearer <key>`. The connector
uses the same contract for platform-managed credentials and your own key;
credential selection, usage attribution and billing are runtime responsibilities.
It does not select a platform credential or implement billing itself.

`tavily` carries `managed: true` in its contract. The platform may supply its
credential; with `auth` bound the workflow's own key is used. tavily's digest
changes in this release because it is now marked managed; no other provider's
digest changes. Consumers treat a missing `managed` key as false.

Grant `tavily.search` with `topic`, `search_depth`, `include_domains`,
`exclude_domains` or `max_results` to pin those inputs. Domain grants pin the
whole list, not an arbitrary subset. Each call requires `query` (1–4000
characters), `max_results` (1–20), `topic` (`general`, `news`, `finance`),
`search_depth` (`basic`, `advanced`, `fast`, `ultra-fast`), and both domain
lists. Use empty lists for unrestricted sources. Domains must be hostnames;
include/exclude lists are limited to 300/150 entries respectively.

```yaml
secrets:
  tavily: vault:tavily/api-key
apis:
  search: {uses: tavily, auth: secrets.tavily}
# Within an agent step:
# can:
#   - search.search: {topic: general, search_depth: basic, max_results: 5}
```

The response exposes `query`, `results` (including source titles, URLs,
content and scores), `usage`, `request_id` and `response_time`. Every request
asks Tavily for usage; runtime metering should use `usage.credits` and retain
`request_id` for reconciliation. Missing usage is unknown, not zero.
Advanced search uses two credits; other depths use one. Automatic parameter
selection is disabled so it cannot silently increase search depth. The initial
connector provides search only, with no generated answers, raw-page retrieval,
crawl or extract. Domain inclusion uses Tavily's default restrictive mode;
the caller cannot change it to merely prefer the selected domains.

Reference: [Tavily Search API](https://docs.tavily.com/documentation/api-reference/endpoint/search).

## Media processing

Bind `uses: media` with no `auth`. The provider is platform-managed: its
contract carries `"managed": true`, `"base_url": null` and no `base_url_from`,
and `auth.accepts` is `none`. The platform executes every call and meters it;
the workflow supplies nothing. Supplying `auth` on the binding is a compile
error.

```yaml
apis:
  media: {uses: media}
# Within an agent step:
# can:
#   - media.process: {outputs: [transcript]}
```

A step names the attachment to process by the attachment id the run's trigger
payload exposes (email trigger attachments in v1). There is no upload, URL,
inline bytes or object key, and the caller does not name the media type: the
input schema closes those fields out. The runner forwards the reference
unchanged and the api resolves it against the run's trigger event, so an id
that does not belong to this run's trigger is refused. The media type comes
from the stored attachment's recorded content type.

```json
{
  "attachment": "att_01",
  "outputs": ["transcript"],
  "options": {"transcript": {"language": "en-US"}}
}
```

`outputs` is a non-empty list of distinct output types from the registry
below. `options` is keyed by output type and takes that type's options
schema. The grant `media.process: {outputs: [...]}` pins the whole list, as a
Tavily domain grant does: the runtime fills it in when the agent omits
`outputs` and refuses a call whose `outputs` differ. Only `outputs` is
grantable, and the grant value is a static literal list, as for every managed
provider; the compiler rejects an expression.

The support registry is media type → output type → payload schema, options
schema and description. Cells not in the table are absent, not stubbed.

| media_type | output type | payload | options |
|------------|-------------|---------|---------|
| audio | transcript | `{text: string, language: string, segments?: [{start: number, end: number, text: string}]}` | `{language?: string}` (BCP-47 hint) |

The contract carries the registry verbatim under a top-level `media.registry`
key, so the digest covers it and the api validates each call-time result
against the locked contract rather than against whichever connectors version
it imports. The cli reads the same key to check requested output types at
compile time. Adding a cell is a connectors release: the `outputs` enum and
the registry grow and nothing else in the contract moves.

The response exposes `media_type`, `outputs` keyed by output type, the
processing backend's `provider` and `model`, `duration_seconds` (present for
audio and video, absent for media with no duration) and `usage`:

```json
{
  "media_type": "audio",
  "outputs": {"transcript": {"text": "...", "language": "en", "segments": [{"start": 0.0, "end": 2.4, "text": "..."}]}},
  "provider": "<processing backend>",
  "model": "<model id>",
  "duration_seconds": 61.2,
  "usage": {"minutes": 1.02}
}
```

`usage.minutes` is the metering unit for every media type; a backend that
bills per item reports its minute equivalent. It is present on failed calls
too, reporting the minutes the backend consumed (zero when none). Missing
usage is a contract violation, not zero. `outputs` is never partial: a call
whose processor fails after producing some outputs fails as a whole. The
module exports `OUTPUT`, the result schema, for the api and tests; it is not
part of the contract document.

Call-time failures a workflow can see:

| Code | Meaning |
|------|---------|
| `integration.attachment_not_found` | `attachment` is not an attachment of the run's trigger event |
| `integration.media_unsupported` | the attachment's recorded content type is not a registry media type; carries the content type |
| `integration.output_unsupported` | an output type is registered, but not for this attachment's media type; names both |
| `integration.options_unused` | `options` carries a key that is not in `outputs` |

For runtimes: on a provider with `managed: true` and `base_url: null`, the
operation's `request` (`POST /process`, body `{{ input }}`) is not an HTTP
call the credential broker makes. It names the api's processor route,
relative to the api's own origin; the runner routes the call there and the
api answers with the result body that `expose` reads. A consumer that keyed
on `base_url: null` to mean "the workflow supplies the origin" must key on
`base_url_from` instead.

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

### OAuth scope serialization

OAuth scopes remain a list in every connector. `OAuth2.scope_separator` tells
the API and CLI how to serialize outbound scope parameters: a space by default,
or `","` for providers such as Linear and Slack. Token response scope parsing is
separate. The default is omitted from the serialized contract, preserving other
providers' contract digests. Declaring the comma separator changes Slack's digest;
workflows locked to its previous contract need to be recompiled with this version.

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
helpers but declare their own API origin and scopes. It uses the GA4 Data API, not Universal Analytics or the Admin API.

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

- **Managed Google connection:** select Analytics in the Google Add Vault form.
  OutcomeCI requests workflow permission separately from account sign-in and
  supplies short-lived bearer credentials to the runner.
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

### Google Drive module

Drive and Analytics appear under Google in Add Vault. Add multiple independent
Google credentials as needed for different accounts or workflow permissions. Bind `uses: google.drive`
to a Google connection with the needed Drive permissions. Signing in with
Google alone does not grant workflow access to Drive or Analytics. The managed
connection keeps refresh credentials in the API and gives the runner a
short-lived bearer lease. Existing OAuth and service-account credentials are
also supported.

```yaml
apiVersion: outcomeci.workflow/v1
trigger: manual
secrets:
  google: vault:google/workflows
apis:
  drive: {uses: google.drive, auth: secrets.google}
steps:
  - inspect:
      reason: Inspect documents directly inside the approved folder.
      can:
        - drive.files.list: {folder_id: "example_folder"}
        - drive.files.get: {folder_id: "example_folder"}
        - drive.files.download: {folder_id: "example_folder"}
        - drive.files.export: {folder_id: "example_folder"}
```

| Operation | Input and limits |
|---|---|
| `files.list` | `folder_id`, `page_size` (1–100), `page_token` (empty for the first page). Lists non-trashed direct children; use `next_page_token` to continue. |
| `files.get` | `file_id`. Returns metadata without content or permission lists. |
| `files.download` | `file_id`. Downloads a binary file as a local artifact, up to 20 MiB. |
| `files.export` | `file_id`, `mime_type`. Exports a Google Workspace document, up to 10 MiB; supported output formats depend on the source type. |
| `folders.create` | `folder_id`, `name`, `description` (may be empty). Creates a folder inside the granted parent. |
| `files.update` | `file_id`, `metadata` containing `name`, `description`, or both. Changes metadata only. |

Read operations accept a specific `file_id` grant or a `folder_id` grant that
checks direct parent membership before returning metadata or downloading.
Folder creation requires a parent-folder grant; updates require a file grant.
There is no arbitrary HTTP request, recursive search, upload, content replacement,
move, trash, delete, sharing or permission-management operation. Shared-drive
items are supported when the connected account has access. Downloads use the
provider origin and do not follow redirects or bypass Google's abuse warnings.

Choose **Drive read** (`drive.readonly`) to inspect existing files and download
or export their content. Add **Drive app files** (`drive.file`) for folder
creation and metadata changes to files authorized for the OAuth app. That
permission does not make every existing file writable: the app must have
created the item or the user must have explicitly opened it with the app.
Entering a file or folder ID is not Google authorization for that item.
The connector does not include a Google Picker UI.

Bring-your-own OAuth defaults to read access with optional `drive.file`;
service-account declarations include both scopes. Service accounts still need
access to the target files. Enable the Drive API in the Google Cloud project.
`drive.readonly` is a restricted Google scope, so external production apps must
meet Google's verification requirements. Google returns permission errors when
a credential lacks the scope or resource access an operation requires.

Drive's content download contract requires a runner that supports same-origin
`Download.path` and `Download.query`; older runners reject that contract. Adding
bearer authentication changes the `google.analytics` contract digest, so workflows
that lock the previous digest must refresh their connector lock. Existing OAuth
and service-account fields and defaults for Analytics are unchanged.

References: [Drive scopes](https://developers.google.com/workspace/drive/api/guides/api-specific-auth),
[file list](https://developers.google.com/workspace/drive/api/reference/rest/v3/files/list),
[file reads](https://developers.google.com/workspace/drive/api/reference/rest/v3/files/get),
[export formats](https://developers.google.com/workspace/drive/api/guides/ref-export-formats),
[folder creation](https://developers.google.com/workspace/drive/api/reference/rest/v3/files/create),
and [metadata updates](https://developers.google.com/workspace/drive/api/reference/rest/v3/files/update).

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

## Linear issues and webhook triggers

Bind `uses: linear` to a Vault credential. A personal API key (`lin_api_…`) is
saved as an `api_key` credential and sent bare in `Authorization`, as Linear
requires; a plain token value would be sent as `Bearer` and refused. For an
OAuth app, choose **Add connection → Linear → Authorize account**, register the
callback URL shown, and enter the app's client ID and secret. The flow uses
PKCE S256 and requests `read`, `issues:create` and `comments:create`. Linear
access tokens last about a day, and each refresh returns a new refresh token,
which the runner stores before using the new access token.

Every operation is a fixed GraphQL query or mutation sent to
`https://api.linear.app/graphql`; the agent supplies only its variables.

- `create_issue`: `team_id`, `title`, optional Markdown `description` and
  `label_ids`. Returns `success`, `issue` (id, identifier, url, team, state,
  assignee, labels) and `errors`.
- `issue`: `team_id` and the issue's `id`. Returns `issues`, a list of at most
  one issue with its current state, assignee and labels; empty when the issue
  is not in the team.
- `search_issues`: `team_id`, an optional Linear `filter` (such as
  `{"state": {"type": {"eq": "started"}}}` or `{"number": {"eq": 123}}`), and
  `first` (1–100, default 50) and `after` for paging. Returns `issues`,
  `page_info` and `errors`.
- `comment_issue`: `issue_id` and a Markdown `body`. Returns `success`,
  `comment` (id and url) and `errors`.

`create_issue`, `issue` and `search_issues` are granted by `team_id`, the
team's UUID: the team is pinned in the mutation's input or ANDed with any
filter the agent passes, so a grant cannot reach another team's issues.
`commentCreate` names only an issue, so `comment_issue` is granted by
`issue_id`. Linear returns GraphQL errors with HTTP 200; check `errors` before
treating an empty result as no match.

```yaml
secrets:
  linear: vault:linear/api-key
apis:
  linear: {uses: linear, auth: secrets.linear}
# Within an agent step:
# can:
#   - linear.create_issue: {team_id: "<team uuid>"}
#   - linear.search_issues: {team_id: "<team uuid>"}
#   - linear.comment_issue: {issue_id: "<issue uuid>"}
```

Workflows can also trigger on Linear webhooks:

```yaml
trigger:
  webhook:
    uses: linear
    auth: secrets.linear_webhook
    events: [issue_created, issue_state_changed, comment_added]

secrets:
  linear_webhook: vault:linear/webhook-secret
```

Create the webhook in Linear (Settings → API → Webhooks) pointing at the
workflow's webhook URL, subscribe it to the **Issues** and **Comments** resource
types, and save its signing secret as a plain Vault value granted to the
workflow. The secret is separate from API credentials.

The receiver verifies `Linear-Signature`, the HMAC-SHA256 of the raw body,
before parsing anything, and refuses a body whose `webhookTimestamp` is more
than a minute from now. `issue_created` is an `Issue` `create`,
`issue_state_changed` an `Issue` `update` whose `updatedFrom` has `stateId`,
and `comment_added` a `Comment` `create`; other updates, removals and resource
types are ignored. The trigger is `event` and `payload`, the original JSON
object; for example `trigger.payload.data.identifier` and
`trigger.payload.data.state.name`. Since Linear does not sign the
`Linear-Delivery` header, redeliveries are deduplicated on the signed entity
id, and for a state change its `updatedAt`.

References: [GraphQL API](https://linear.app/developers/graphql),
[OAuth](https://linear.app/developers/oauth-2-0-authentication),
[filtering](https://linear.app/developers/filtering) and
[webhooks](https://linear.app/developers/webhooks).

## Custom API

`custom` is the escape hatch for a service without a first-party connector.
The provider fixes no origin: the workflow names it, and the contract carries
`"base_url": null` with `"base_url_from": "workflow"`.

```yaml
secrets: {acme: vault:acme/token}
apis:
  acme:
    uses: custom
    base_url: https://api.acme.com
    auth: secrets.acme
steps:
  - sync:
      reason: Reconcile open orders.
      can:
        - acme.read: {path: /v1/orders}
        - acme.write: {path: /v1/orders}
```

Authentication is a static Vault credential only: a `token` (sent as
`Authorization: Bearer`), an `api_key`, or `basic`. For an api key the header
comes from the credential's `header_name` (default `X-API-Key`) and optional
`prefix`; first-party connectors keep their declared header and ignore the
credential's. No OAuth2, OIDC, JWT or app installation.

`read` sends GET; `write` sends POST, PUT, PATCH or DELETE and runs only in a
step that grants it. Each takes an optional `path` grant, a prefix the request
path must sit under; without one, any path on the origin. The runtime keeps
its usual protections: every request is pinned to `base_url`'s origin, private
addresses are refused (managed runners always; local runs may opt in with
`allow_private_network: true`), redirects are not followed, and the agent
cannot set Authorization, Cookie, Host or Proxy-Authorization.
