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
  provider.py          # Provider, Operation, Grantable, Deny, Watcher
  providers/
    slack/
      __init__.py      # PROVIDER: post, thread, reactions; reaction and reply watchers
      setup.py         # app manifest, Slack CLI setup and status
    github.py          # PROVIDER: read and write, scoped by repo
```

Each provider package owns everything about its provider:

- **Operations:** what `uses: <provider>` resolves to, with input shapes,
  request templates and response mapping.
- **Grant vocabulary:** which arguments a grant may scope, such as a Slack
  `channel` or `thread_ts`, or a GitHub `repo`, and the requests an operation
  refuses whatever the grant.
- **Watchers:** the match logic behind `await` and `converse`, such as an
  emoji reaction or a human reply in a thread. The runtime owns the loop,
  timeouts and durability.
- **Setup:** for Slack, generating the app manifest and driving the Slack CLI
  to create and install the app (the `oci integration slack setup`,
  `manifest` and `status` commands).

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
