# outcomeci/connectors

Standalone setup tooling for [OutcomeCI](https://outcomeci.com) integrations,
kept in its own repository so it can be reviewed, versioned, and released
independently of the core runtime.

## Connectors

- `outcomeci_connectors.slack` -- generates the Slack app manifest, drives the
  Slack CLI to create and install the app locally, and reports setup status
  (the `oci integration slack setup`/`manifest`/`status` command surface).
  Message/reply delivery for `delivery.type: slack` human hooks is not
  implemented here; that's handled by cli's `mode: reaction`/`mode: reply`,
  resolved entirely through the generic HTTP capability broker rather than a
  local Slack CLI dependency. `oci integration slack sync-credentials` (in
  `outcomeci-cli`, not this package) pushes the installed app's bot token into
  a vault for that broker to use.

## Development

```
pip install -e '.[test]'
pytest
ruff check .
```

Versioned via git tags (`vX.Y.Z`), same convention as `outcomeci-cli`.
