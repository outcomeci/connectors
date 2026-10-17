# Implementation Plan: Media processor provider

**Branch**: `feat/media-processor` | **Date**: 2026-10-17 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/media-provider/spec.md`

## Summary

Ship a platform-managed `media` provider with one operation, `media.process`,
that turns a trigger attachment of the current run into typed outputs. The
contract is the product: a closed input schema `{attachment, outputs,
options?}`, an exported `OUTPUT` result schema, an exported `REGISTRY`
(`audio → transcript` only) carried verbatim on the contract under a top-level
`media.registry` key, and a grant on `outputs` only. Alongside it, `Provider`
gains `managed: bool = False`, emitted as `managed` on a contract only when
true (omitted when false, exactly as `base_url_from` is omitted when it does
not apply) and set on `tavily` and `media`, so cli and api dispatch on the flag
instead of the literal name "tavily". The change lands as one `feat(media)` release of
`outcomeci-connectors` (v0.15.0 from the current v0.14.0) that the api pins and
the cli runner image installs.

## Technical Context

**Language/Version**: Python 3.11+ (CI runs 3.12)

**Primary Dependencies**: none at runtime (stdlib dataclasses, json, hashlib);
`jsonschema>=4.23`, `pytest>=8.3`, `ruff>=0.13` for tests

**Storage**: N/A. A provider is data plus pure functions; nothing is persisted here.

**Testing**: `pytest -q`, `ruff check .`, `ruff format --check .` (`.github/workflows/test.yml`)

**Target Platform**: PyPI package consumed by the cli (compiler and runner image) and the api

**Project Type**: library (single package, `src/outcomeci_connectors`)

**Constraints**: provider modules make no network call and read no environment
at import; every contract is JSON-serialisable and digest-stable; the only
digest movement in this release is the `managed` key on `tavily`; every other
existing provider's digest is unchanged.

**Scale/Scope**: two source files touched, one created; one new test module,
two existing test modules extended; README and CONTRIBUTING additions.

## Constitution Check

This repository has no constitution file; `CONTRIBUTING.md` carries the
enforceable rules, and its "Review bar" is the gate. Checked against this plan:

| Rule (CONTRIBUTING.md) | Status |
|------------------------|--------|
| Provider is data plus pure functions; no network, no environment, no secret | PASS. `media.py` holds dicts and one `Provider`; the registry is built at import from literals. |
| Register the entry point under `outcomeci.connectors`, named for `uses:` | PASS. `media = "outcomeci_connectors.providers.media:PROVIDER"`. |
| `input` is a closed JSON Schema with bounds on strings | PASS. `additionalProperties: false`; `attachment` is 1..256 chars; `outputs` is `minItems: 1`, `uniqueItems`, enum. |
| `side_effect` is the strongest effect | PASS. `execute`: the platform runs a processor on the caller's behalf. |
| Expose only what a workflow needs; never a credentialed URL | PASS. Six named fields; no URL at all. |
| Each `Grantable` sets exactly one kind | PASS. `Grantable(field="outputs")`. |
| Auth kinds backed by documentation; `NoAuth()` stands alone | PASS. `auth=(NoAuth(),)`; there is no third-party API to document, which the module docstring says. |
| Tests cover entry point, operation contract, `auth.accepts` | PASS. See Phase 3. |
| README layout lists the provider | PASS. "Layout" line plus a "Media processing" section. |
| A contract change changes the digest, and the PR says what and why | PASS. `managed` is emitted only when true, so only `tavily`'s digest moves (and `media` is new); every other provider's digest is unchanged. Recorded in README and the PR body (Phase 4). |

Deviation to record: `Operation` today admits only a fixed shape (`method` +
`path`) or a request shape (`methods`). `process` is neither in spirit, since
the platform executes it. The plan keeps the fixed shape (see Phase 1,
decision D2) rather than adding a third operation shape, so no `provider.py`
validation changes beyond the `managed` flag. Complexity Tracking below says
why.

## Project Structure

### Documentation (this feature)

```text
specs/media-provider/
├── spec.md              # authoritative; this plan implements it
└── plan.md              # this file
```

No `research.md`, `data-model.md` or `contracts/` directory: the data model
and contract are small enough to live in this plan (Phase 1), and the shipped
contract is produced by `PROVIDER.contract()` and asserted by tests.

### Source Code (repository root)

```text
src/outcomeci_connectors/
├── provider.py                  # MODIFY: Provider.managed, contract() emits it only when true,
│                                #   base_url_from suppressed when managed
└── providers/
    ├── tavily.py                # MODIFY: managed=True
    └── media.py                 # CREATE: MEDIA_TYPES, REGISTRY, OUTPUT, PROVIDER

tests/
├── test_media.py                # CREATE: contract snapshot, schema cases, registry, growth
├── test_tavily.py               # MODIFY: assert managed is True
├── test_providers.py            # MODIFY: managed absent on every other provider
└── test_custom.py               # MODIFY: base_url_from still emitted for unmanaged custom

pyproject.toml                   # MODIFY: media entry point
README.md                        # MODIFY: Layout line, "Media processing" section,
                                 #   digest note under "Tavily search"
CONTRIBUTING.md                  # MODIFY: one paragraph on managed providers
```

**Structure Decision**: single-module provider (`providers/media.py`), as
CONTRIBUTING prescribes for a provider with operations only. No receiver,
watcher or setup tooling, so no package directory.

## Phase 0: Findings that shape the design

Read before writing code; each one is a trap the spec does not spell out.

- **F1. `base_url=None` currently implies `base_url_from: workflow`.**
  `Provider.contract()` emits `base_url_from` whenever `base_url is None`.
  FR-003 forbids it on `media`. The emission must become conditional on
  `not self.managed`, and `custom` must keep it (its test asserts it).
- **F2. `Operation.__post_init__` rejects an operation that is neither fixed nor request.**
  `process` needs `method` + `path` (or `methods`) to construct. Decision D2
  resolves this without a new operation shape.
- **F3. `managed` moves only tavily's digest (and media is new).**
  The key is emitted only when true, exactly like `base_url_from` is emitted
  only when it applies, so slack, github, google.*, x, linkedin, linear and
  custom keep their digests byte for byte and no non-tavily workflow revision
  changes. Consumers treat a missing key as false. SC-005 names tavily
  because it is the one existing provider whose contract changes; the README
  note says only that.
- **F4. `check_accepts` already enforces `NoAuth()` alone.** No auth change
  is needed; `auth.accepts` for media is `[{"kind": "none", "credential": []}]`
  exactly as FR-002 wants.
- **F5. Tests use `jsonschema.Draft202012Validator`.** `propertyNames` with
  `enum`, `uniqueItems` and `minItems` are all available; nothing in FR-007
  through FR-010 needs a newer draft.
- **F6. Release mechanics.** `publish.yml` releases on merge to `main` from
  conventional commits: `feat(media): ...` bumps v0.14.0 to v0.15.0 and the
  GitHub release notes are generated from PR titles. The contract-digest
  consequence therefore has to be in the PR title or body to reach the
  notes, and in README to reach users.
- **F7. Options-by-unrequested-output is a call-time rule by spec.** The
  edge case list says `options` keyed by an output not in `outputs` is
  rejected "at call time with `integration.options_unused`; the schema cannot
  express the dependency". It is in fact expressible (an `allOf` of
  `if options.required:[T] then outputs.contains:{const:T}` per registry
  type), but the spec is authoritative and the api owns the rule. The test
  for this case asserts the schema *accepts* it and names the api code, so a
  later change to the schema is a deliberate spec change, not drift.

## Phase 1: Design

### D1. `Provider.managed`

`provider.py`:

```python
@dataclass(frozen=True)
class Provider:
    ...
    setup_credentials: tuple[SetupCredential, ...] = ()
    managed: bool = False
```

`contract()` gains, immediately after `"name"`:

```python
**({"managed": True} if self.managed else {}),
```

and the `base_url_from` line becomes:

```python
**({"base_url_from": "workflow"} if self.base_url is None and not self.managed else {}),
```

Docstring: "`managed`: the platform may supply the credential and, when
`base_url` is None, executes the operation itself; emitted on the contract
only when true, so unmanaged providers' digests are untouched and consumers
treat a missing key as false; a managed provider with `base_url` None
carries no `base_url_from`." No `__post_init__` rule ties
`managed` to a particular auth kind: FR-006 says the combination is a runtime
decision, and tavily (managed, accepts `token`/`api_key`) proves both
combinations are valid.

`tavily.py`: add `managed=True` to the `Provider(...)` call with a comment
pointing at the README paragraph on platform-managed credentials.

### D2. `process` as a fixed operation

`Operation` must be fixed or request (F2). `process` is declared fixed:

```python
"process": Operation(
    description=(...),
    method="POST",
    path="/process",
    input=INPUT,
    body="{{ input }}",
    expose={
        "media_type": "body.media_type",
        "outputs": "body.outputs",
        "provider": "body.provider",
        "model": "body.model",
        "duration_seconds": "body.duration_seconds",
        "usage": "body.usage",
    },
    side_effect="execute",
    grantable={"outputs": Grantable(field="outputs")},
)
```

The contract therefore carries `request: {"method": "POST", "path":
"/process", "body": "{{ input }}"}` with `base_url: null` and no
`base_url_from`. The meaning for consumers: **on a provider with `managed:
true` and `base_url: null`, `request` is not an HTTP call the broker makes; it
is the processor route the api serves, relative to the api's own origin.** The
runner forwards the rendered body to the api's processor endpoint and the api
answers with the result body that `expose` reads. This is the one place the
plan asks cli and api to read a contract key differently from today; it is
recorded in README and in the report to the caller. The alternative (a third
operation shape with no `request`) is rejected in Complexity Tracking.

### D3. Registry and media types

`media.py` module-level data, all plain dicts/lists/strings:

```python
MEDIA_TYPES = ("audio", "image", "video", "document")   # FR-018, closed set

SEGMENT = {
    "type": "object",
    "required": ["start", "end", "text"],
    "properties": {
        "start": {"type": "number", "minimum": 0},
        "end": {"type": "number", "minimum": 0},
        "text": {"type": "string"},
    },
    "additionalProperties": False,
}
TRANSCRIPT = {
    "type": "object",
    "required": ["text", "language"],
    "properties": {
        "text": {"type": "string"},
        "language": {"type": "string"},
        "segments": {"type": "array", "items": SEGMENT},
    },
    "additionalProperties": False,
}
TRANSCRIPT_OPTIONS = {
    "type": "object",
    "properties": {
        # BCP-47 hint; the backend may ignore it.
        "language": {"type": "string", "pattern": r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{1,8})*$"},
    },
    "additionalProperties": False,
}

REGISTRY = {
    "audio": {
        "transcript": {
            "description": "Speech in the recording as text with language and timed segments.",
            "payload": TRANSCRIPT,
            "options": TRANSCRIPT_OPTIONS,
        },
    },
}
```

An import-time check raises `ValueError` for any registry key outside
`MEDIA_TYPES` (FR-018) and for a cell missing `payload`, `options` or
`description`. The check is a small function `_check_registry(registry)` so the
growth test (FR-024 last bullet) can exercise it on a fixture.

### D4. Derived input schema

Built by `_input_schema(registry)` at import, never hand-maintained (FR-009):

- `output_types = sorted({t for cells in registry.values() for t in cells})`
- `options.properties[t]` = the single options schema when `t` appears under
  one media type, else `{"anyOf": [<each distinct options schema>]}` (FR-010).

```python
INPUT = {
    "type": "object",
    "required": ["attachment", "outputs"],
    "properties": {
        "attachment": {"type": "string", "minLength": 1, "maxLength": 256},
        "outputs": {
            "type": "array",
            "minItems": 1,
            "uniqueItems": True,
            "items": {"type": "string", "enum": output_types},
        },
        "options": {
            "type": "object",
            "propertyNames": {"enum": output_types},
            "properties": {t: <options schema or anyOf> for t in output_types},
            "additionalProperties": False,
        },
    },
    "additionalProperties": False,
}
```

`attachment` has no pattern (FR-008). Nothing named `data`, `content`, `url`,
`file`, `object_key` or `media_type` exists; `additionalProperties: false`
rejects them (FR-011).

### D5. `OUTPUT`

```python
OUTPUT = {
    "type": "object",
    "required": ["media_type", "outputs", "provider", "model", "usage"],
    "properties": {
        "media_type": {"type": "string", "enum": sorted(REGISTRY)},
        "outputs": {"type": "object"},
        "provider": {"type": "string", "minLength": 1},
        "model": {"type": "string", "minLength": 1},
        "duration_seconds": {"type": "number", "minimum": 0},
        "usage": {
            "type": "object",
            "required": ["minutes"],
            "properties": {"minutes": {"type": "number", "minimum": 0}},
            "additionalProperties": False,
        },
    },
    "additionalProperties": False,
}
```

`media_type` enumerates the media types *present in the registry*
(`["audio"]` today), not all of `MEDIA_TYPES`: a result for a media type with
no cell cannot exist. `outputs` values are validated per cell by the api from
`media.registry`, not by `OUTPUT` (FR-013). `OUTPUT` is exported for the api
and for tests; it is not part of the contract document (no `response.schema`
key exists in `outcomeci.connector/v1`, and adding one would be a contract
change for every provider).

### D6. Contract carries the registry

`media.py` must put `{"media": {"registry": REGISTRY}}` on the contract
without giving `Provider` a media-specific field (FR-016 says other providers
must not carry the key). Two options were weighed:

- A generic `Provider.extra: Mapping[str, Any] = {}` merged into `contract()`
  at the top level. Simple, but a general hook invites unreviewed contract keys.
- A `Provider` subclass in `media.py` overriding `contract()`:

```python
@dataclass(frozen=True)
class _MediaProvider(Provider):
    def contract(self) -> dict[str, Any]:
        return {**super().contract(), "media": {"registry": REGISTRY}}
```

The subclass is chosen. `digest()` calls `self.contract()` so the registry is
covered by the digest with no further change; `entry_points` load `PROVIDER`
by attribute so the type does not matter; the override is local to the one
provider that needs it. A one-line test asserts no other registered provider's
contract has a `media` key.

### D7. Provider

```python
PROVIDER = _MediaProvider(
    name="media",
    base_url=None,
    auth=(NoAuth(),),
    max_requests=10,
    managed=True,
    operations={"process": ...},   # D2
)
```

Operation `description` (what the agent reads): names the attachment reference
as "the attachment id from the trigger payload", lists the output types the
registry offers, says the platform picks the media type from the stored
attachment, says it returns `media_type`, `outputs` keyed by output type,
`provider`, `model`, `duration_seconds` and `usage.minutes`, and says it
refuses bytes, URLs, uploads and a caller-supplied media type.

### D8. Failure codes

Named here because the registry decides them; raised by the api, surfaced by
the cli, documented in README (FR-022):

| Code | When |
|------|------|
| `integration.attachment_not_found` | `attachment` is not an attachment of the run's trigger event |
| `integration.media_unsupported` | the attachment's recorded content type is not a registry media type; carries the content type |
| `integration.output_unsupported` | an output type is registered, but not for this attachment's media type; names both |
| `integration.options_unused` | `options` carries a key not in `outputs` |

Also stated: a failed call still reports `usage.minutes` (FR-014); `outputs`
is never partial.

## Phase 2: Implementation steps

1. `src/outcomeci_connectors/provider.py`: add `managed`, emit it only when
   true, make `base_url_from` conditional (D1). Update the `Provider` docstring.
2. `src/outcomeci_connectors/providers/tavily.py`: `managed=True`.
3. `src/outcomeci_connectors/providers/media.py`: D3 to D7, in that order so
   each constant is defined before use. Module docstring states that the
   provider is platform-executed and documents no third-party API.
4. `pyproject.toml`: entry point `media = "outcomeci_connectors.providers.media:PROVIDER"`,
   placed after `custom`.
5. Tests (Phase 3).
6. Docs (Phase 4).
7. `ruff check . && ruff format --check . && pytest -q` locally before the PR.

## Phase 3: Tests

### `tests/test_media.py` (create; mirrors `tests/test_tavily.py`)

Module constants: `CONTRACT = PROVIDER.contract()`, `PROCESS =
CONTRACT["operations"]["process"]`, `CALL = {"attachment": "att_01",
"outputs": ["transcript"]}`, `RESULT = <the C1 example output>`.

- `test_entry_point_managed_no_auth_no_origin`: entry point loads `PROVIDER`;
  `contract["managed"] is True`; `contract["base_url"] is None`;
  `"base_url_from" not in contract`; `auth.accepts == [{"kind": "none",
  "credential": []}]`; `max_requests == 10`; `watchers == {}` and
  `receiver is None`.
- `test_contract_snapshot`: assert the whole `process` contract dict equals a
  literal (request, input, response.expose, side_effect, grantable, deny) and
  `contract["media"] == {"registry": REGISTRY}`. This is the snapshot the
  caller asked for; any change to it is a digest change and must be
  deliberate. Also `json.loads(json.dumps(contract)) == contract` and
  `PROVIDER.digest() == PROVIDER.digest()`.
- `test_grantable_is_outputs_only`:
  `PROCESS["grantable"] == {"outputs": {"field": "outputs"}}`.
- `test_schemas_are_valid_draft_2020_12`: `check_schema` on `PROCESS["input"]`,
  `OUTPUT`, and every `payload` and `options` in `REGISTRY` (FR-019).
- `test_accepts_example_input` (parametrized): `CALL`; `CALL` with
  `options: {transcript: {language: "en-US"}}`; `CALL` with `options: {}`;
  `attachment` of 256 chars.
- `test_rejects_inputs_the_schema_can_express` (parametrized patches, in the
  tavily style):
  `{"outputs": []}`, `{"outputs": ["transcript", "transcript"]}`,
  `{"outputs": ["summary"]}` (unknown output type), `{"outputs": "transcript"}`,
  `{"attachment": ""}`, `{"attachment": "a" * 257}`, `{"attachment": 1}`,
  `{"options": {"summary": {}}}` (option key not an output type),
  `{"options": {"transcript": {"temperature": 0}}}`,
  `{"options": {"transcript": {"language": "english!"}}}`,
  `{"media_type": "audio"}`, `{"data": "..."}`, `{"content": "..."}`,
  `{"url": "https://..."}`, `{"file": "..."}`, `{"object_key": "..."}`;
  and each required field removed.
- `test_options_for_an_unrequested_output_is_a_call_time_rule`: with
  `REGISTRY` holding one cell this cannot be built from real data, so the
  test uses the growth fixture (below) to build an input schema with two
  output types and asserts that `{"attachment": "att_01", "outputs":
  ["transcript"], "options": {"caption": {}}}` **validates**, with a comment
  naming `integration.options_unused` as the api's answer (F7). If the caller
  decides the schema should reject it instead, this is the one test to flip
  and D4 gains the `allOf`/`if`/`then` block; that is a spec change.
- `test_output_accepts_the_example_result_and_requires_usage`: `RESULT`
  validates against `OUTPUT`; `outputs.transcript` validates against
  `REGISTRY["audio"]["transcript"]["payload"]`; removing `usage` fails;
  removing `duration_seconds` passes; `usage.minutes: -1` fails;
  `media_type: "image"` fails (no cell).
- `test_registry_is_plain_data`: `REGISTRY == {"audio": {"transcript":
  {...}}}` with the exact schemas; `json.dumps(REGISTRY)` round-trips; every
  cell has `description`, `payload`, `options`.
- `test_registry_rejects_an_unknown_media_type`: `_check_registry({"gif":
  {...}})` raises `ValueError` (FR-018).
- `test_adding_a_cell_changes_only_the_enum_options_and_registry` (US4):
  build a fixture registry adding `image → caption` with its own options
  schema, call the same builders (`_input_schema`, `_output_schema`) and a
  fixture `_MediaProvider`, then diff contracts: the only keys that differ
  are `operations.process.input.properties.outputs.items.enum`,
  `operations.process.input.properties.options.properties`,
  `operations.process.input.properties.options.propertyNames`, and
  `media.registry` (plus `OUTPUT.media_type.enum` outside the contract). This
  needs the builders to take the registry as an argument, which D4/D5
  already do.
- `test_anyof_when_one_output_type_has_two_options_schemas`: fixture with
  `audio → transcript` and `video → transcript` carrying different options;
  assert `options.properties.transcript` is `{"anyOf": [...]}` with both.
- `test_no_other_provider_carries_the_media_key`: iterate the entry-point
  group; only `media` has `"media"` in its contract.

### `tests/test_tavily.py` (modify)

In `test_entry_point_and_bearer_api_key_auth`: `assert contract["managed"] is True`.

### `tests/test_providers.py` (modify)

- `test_managed_absent_when_false`: for every registered provider other than
  `tavily` and `media`, `"managed" not in contract`; for `tavily` and
  `media`, `contract["managed"] is True`.
- In `test_digest_changes_with_the_contract`: `Provider(...)` with
  `managed=True` digests differently from the same with `managed=False`.

### `tests/test_custom.py` (modify)

`test_custom_takes_its_origin_from_the_workflow` already asserts
`base_url_from == "workflow"`; add `assert "managed" not in contract` so the
conditional in D1 is pinned from both sides. Extend
`test_a_provider_with_a_fixed_origin_carries_no_base_url_from` with the media
provider, under a renamed test that says "fixed origin or managed".

## Phase 4: Documentation and release

### README.md

- "Layout": add `media.py            # PROVIDER: platform-run processing of a trigger attachment; audio → transcript`.
- New section "## Media processing" after "## Tavily search", in that
  section's style (FR-023):
  - binding: `apis: {media: {uses: media}}`, no `auth`; the contract carries
    `"managed": true`, `"base_url": null` and no `base_url_from`, and
    `auth.accepts` is `none`; supplying `auth` is a compile error.
  - how a step names an attachment: the attachment id from the trigger
    payload of the run (email trigger attachments in v1); no upload, URL,
    bytes or object key; the api resolves it against the run's trigger
    event.
  - the grant form: `can: [media.process: {outputs: [transcript]}]`; a
    static literal list only, as for every managed provider; the runtime
    fills it when omitted and refuses a call whose `outputs` differ.
  - the registry table from the spec and the sentence "cells not in the
    table are absent, not stubbed"; the contract's `media.registry` key and
    that the api validates call-time from the locked contract.
  - the output shape (C1) and the metering unit: `usage.minutes`, present on
    failures too, missing usage is a contract violation.
  - the failure codes table (D8).
  - a "For runtimes" paragraph stating D2: with `managed: true` and
    `base_url: null`, `request` names the api's processor route, not a
    broker HTTP call.
- "Tavily search": a paragraph after the first one: "`tavily` carries
  `managed: true` in its contract. The platform may supply its credential;
  with `auth` bound the workflow's own key is used. tavily's digest changes
  in this release because it is now marked managed; no other provider's
  digest changes. Consumers treat a missing `managed` key as false."
- Nothing in README uses em dashes.

### CONTRIBUTING.md

Under "Auth" (or a new short "## Managed providers" after "Setup tooling"):
what `managed=True` means, that it is set only when the platform executes or
credentials the provider, that a managed provider with `base_url=None` is
platform-executed and its `request` is the api's route, and that grants on
managed providers are static values (a cli rule stated here so a new managed
provider does not re-document it).

### Release

- Commits on the branch are conventional: `feat(media): add the media
  processor provider and the managed provider flag`. On merge, `publish.yml`
  bumps v0.14.0 to **v0.15.0**, publishes to PyPI, tags and creates the
  GitHub release with generated notes from the PR title (F6).
- PR body "What changed and why" paragraph (the review bar asks for it):
  the new provider; the `managed` key, emitted only when true, so only
  `tavily`'s digest changes and every other provider's digest and every
  non-tavily workflow revision is unchanged; D2's meaning of
  `request` on a managed origin-less provider; the four failure codes.
- Downstream, in order, outside this repo: api pins `outcomeci-connectors==0.15.0`
  and reads `managed` + `media.registry`; cli reads `managed` for the
  auth/static-grant rules and `media.registry` for the output-type check and
  bumps the runner image install; shared-infra pins the runner digest. Those
  are separate PRs and not in this plan's scope, but the api pin must land
  before any workflow binds `uses: media`, or the api will validate against a
  contract it cannot load.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| `process` is declared as a fixed `POST /process` operation although no broker HTTP call is made (D2) | `Operation` admits only fixed or request shapes; the contract version has no key for a platform-executed operation and FR-003 forbids introducing an `execution` key | A third operation shape (no `request`) would change `Operation.contract()` for every consumer, needs a cli and api parser change before any media work, and would be the second schema-shaping change in one release. Reading `request` as the api route on a `managed` + `base_url: null` provider needs no new key. |
| `_MediaProvider` subclass overriding `contract()` (D6) | FR-016 wants `media.registry` on this provider only; a `Provider` field would appear on every contract | A generic `extra` mapping on `Provider` is a hook for arbitrary unreviewed keys; the subclass keeps the deviation inside `media.py`. |

## Contract concerns for cli and api

Collected here so the caller can forward them unchanged.

1. **`base_url_from` is suppressed on managed providers.** Today
   `base_url: null` always came with `base_url_from: "workflow"`. After this
   release, `base_url: null` with `managed: true` and no `base_url_from` means
   platform-executed. A consumer that keys on `base_url is None` to mean
   "workflow supplies the origin" must key on `base_url_from` instead.
2. **`request` on `media.process` is the api's processor route, not a broker
   call** (`POST /process`, body `{{ input }}`). The runner must route by
   `managed && base_url is null`, never by the operation's `request`.
3. **Only tavily's digest changes** (the `managed` key is emitted only when
   true). Every other provider's digest and every non-tavily workflow
   revision is unchanged on this connectors version. Consumers treat a
   missing `managed` key as false.
4. **`integration.options_unused` is the api's job.** The input schema
   accepts options keyed by an output type that is not in `outputs` (spec
   edge case). If the caller would rather have the schema reject it, that is
   a spec change (F7) and the one test named in Phase 3 flips.
5. **`OUTPUT` is exported, not on the contract.** The api imports
   `outcomeci_connectors.providers.media.OUTPUT` from its pinned version to
   validate the processor's result; per-output payloads come from the locked
   contract's `media.registry`. If the api wants the result schema digest-
   locked too, that is a follow-up contract key for all providers.
6. **Grant static-value rule is a cli rule** (FR-021), applied to every
   `managed: true` provider; there is no contract field for it.
