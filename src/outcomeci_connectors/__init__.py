"""Standalone integration setup tooling for OutcomeCI.

Each connector generates and installs a third-party app (e.g. Slack) and
pushes its credential into an OutcomeCI Vault, kept in its own repository so
it can be reviewed and released independently of the core runtime. Message
delivery to that app happens through outcomeci-cli's own HTTP capability
broker, not through this package.
"""
