"""Standalone connector implementations for OutcomeCI human-hook delivery.

Each connector is a self-contained integration (e.g. Slack) that OutcomeCI's
CLI/runtime (outcomeci-cli) depends on and calls into for a specific
delivery mechanism, kept in its own repository so it can be reviewed and
released independently of the core runtime.
"""
