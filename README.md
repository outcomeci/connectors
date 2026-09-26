# outcomeci/connectors

Standalone human-hook delivery connectors for [OutcomeCI](https://outcomeci.com).

Each connector implements a delivery mechanism `outcomeci-cli` calls into at
runtime (e.g. Slack), kept in its own repository so it can be reviewed,
versioned, and released independently of the core runtime.

## Connectors

- `outcomeci_connectors.slack` -- Slack message and reply delivery for
  `delivery.type: slack` human hooks, plus the `oci integration slack`
  setup/status/run command surface.

## Development

```
pip install -e '.[test]'
pytest
ruff check .
```

Versioned via git tags (`vX.Y.Z`), same convention as `outcomeci-cli`.
