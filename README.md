# outcomeci/connectors

The providers an [OutcomeCI](https://outcomeci.com) workflow can connect to,
kept in their own repository so they can be reviewed, versioned and released
independently of the runtime.

A provider is data plus pure functions. It never makes a request or holds a
secret: the OutcomeCI runtime executes every call through its credential
broker, which journals it. An `outcomeci.workflow/v1` workflow names a provider
with `uses:`, and the cli finds installed providers through the
`outcomeci.connectors` entry point group.

## Layout

```
outcomeci_connectors/
  provider.py          # Provider, Operation, Grantable, Deny, Download, Watcher, Receiver
  providers/
    slack/
      __init__.py      # PROVIDER: post, thread, file, reactions; reaction and reply watchers
      messages.py      # the files and subtypes a message carries
      receiver.py      # signed Events API requests to a workflow trigger
      setup.py         # app manifest, Slack CLI setup and status
    github.py          # PROVIDER: read and write, scoped by repo
```

Each provider package owns everything about its provider:

- **Operations:** what `uses: <provider>` resolves to, with input shapes,
  request templates and response mapping.
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
revision.

## Development

```
pip install -e '.[test]'
pytest
ruff check .
```

Versioned via git tags (`vX.Y.Z`), the same convention as `outcomeci-cli`.
