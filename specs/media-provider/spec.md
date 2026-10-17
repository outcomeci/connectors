# Feature Specification: Media processor provider

**Feature Branch**: `feat/media-processor`

**Created**: 2026-10-17

**Status**: Draft

**Input**: A platform-managed `media` provider (`uses: media`) with one operation, `media.process`, that turns a trigger attachment of the current run into typed outputs (initially an audio transcript). This repo owns the operation contract and the support registry; cli, api and www consume them.

## Context

A provider in this repo is data plus pure functions: it declares operations, their input schemas, what a grant pins and what the response exposes. Every provider today is an HTTPS API the runtime calls through its credential broker (`base_url` plus a fixed `method`/`path`, or a request operation inside that origin). `custom` leaves the origin to the workflow; `tavily` is the first provider whose credential the platform may supply, but nothing in its contract says so, so cli and api dispatch on the literal name "tavily".

`media` is different in two ways. It is executed by the platform itself (a processor image behind the api), not by an HTTP call to a third-party origin, and it never takes a workflow credential. This spec adds what the contract needs to say for a consumer to know both facts without naming the provider, and defines the one operation and the registry of what the processor can produce.

In v1 the only media input is a trigger attachment: a file that arrived with the event that started the run (email trigger attachments). The run refers to it by the attachment identifier the trigger payload exposes. There is no file upload, no object key, no inline bytes and no runner-side transfer; the runner forwards the reference unchanged and the api resolves it server-side against the run's trigger event.

### Contract C1 (connectors produces; cli, api, www consume)

`media.process` input:

```json
{
  "attachment": "<attachment id from the trigger payload>",
  "outputs": ["transcript"],
  "options": {"transcript": {"language": "en-US"}}
}
```

`media.process` output:

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

Support registry (media_type → output type → payload schema + options schema), initially one cell:

| media_type | output type | payload | options |
|------------|-------------|---------|---------|
| audio | transcript | `{text: string, language: string, segments?: [{start: number, end: number, text: string}]}` | `{language?: string}` (BCP-47 hint) |

Cells that are not in the table are absent, not stubbed.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Transcribe an emailed recording in a workflow (Priority: P1)

A workflow author binds `apis: {media: {uses: media}}` on a workflow with an email trigger. A recording arrives as an attachment on the triggering email, and an agent step calls `media.process` with the attachment's identifier from the trigger payload and `outputs: [transcript]`. The step gets back the transcript text and language, and the run record shows the minutes consumed.

**Why this priority**: It is the whole feature. Without a working audio → transcript cell there is nothing to grant, meter or display.

**Independent Test**: Load the `media` provider, validate the example input against `operations.process.input`, validate the example output against the registry's `audio.transcript` payload schema, and confirm `PROVIDER.contract()` round-trips through JSON with a stable digest.

**Acceptance Scenarios**:

1. **Given** `uses: media` with no `auth`, **When** the workflow is compiled, **Then** the binding is accepted and the contract digest locked into the revision is the `media` provider's digest.
2. **Given** an input of `{attachment: "att_01", outputs: ["transcript"]}`, **When** it is validated against the operation's input schema, **Then** it passes.
3. **Given** the referenced attachment belongs to the run's trigger event and its recorded content type is audio, **When** the platform runs `process`, **Then** the result carries `media_type: "audio"`, `outputs.transcript` matching the registry payload schema, `provider`, `model` and `usage.minutes`.
4. **Given** `options: {transcript: {language: "en-US"}}`, **When** validated, **Then** it passes; **Given** `options: {transcript: {temperature: 0}}`, **Then** it is rejected because the options schema closes additional properties.

---

### User Story 2 - Pin what a step may produce with a grant (Priority: P2)

A policy author restricts an agent step to `media.process: {outputs: [transcript]}` so the agent cannot request other output types once more cells exist. The runtime fills `outputs` in when the agent omits it and refuses a call whose `outputs` differ from the grant.

**Why this priority**: Grants are how every provider in this repo bounds an agent; `media` must follow the same `Grantable(field=...)` shape so the runtime's existing grant enforcement applies unchanged.

**Independent Test**: `contract["operations"]["process"]["grantable"] == {"outputs": {"field": "outputs"}}`, and a grant value of a non-list or an unregistered output type is rejected by the grant schema.

**Acceptance Scenarios**:

1. **Given** `can: [media.process: {outputs: [transcript]}]`, **When** the agent calls `process` without `outputs`, **Then** the runtime supplies `["transcript"]`.
2. **Given** the same grant, **When** the agent calls with `outputs: ["transcript", "summary"]`, **Then** the call is refused by grant enforcement before the processor runs.
3. **Given** `can: [media.process: {attachment: "..."}]`, **When** compiled, **Then** it is rejected: only `outputs` is grantable.
4. **Given** `can: [media.process: {outputs: "{{ steps.pick.outputs }}"}]`, **When** compiled, **Then** it is rejected: grants on managed providers are static values only.

---

### User Story 3 - Consumers dispatch on `managed`, not on a name (Priority: P2)

The cli compiler and the api's call path read `managed: true` from a provider contract to decide that the platform supplies the execution credential, executes the call and meters it. `tavily` and `media` both carry the flag; no consumer has to know either name.

**Why this priority**: Adding `media` would otherwise add a second hard-coded name in three repos. The flag is small and pays for itself on the second managed provider.

**Independent Test**: `tavily.PROVIDER.contract()["managed"] is True`, `media.PROVIDER.contract()["managed"] is True`, `slack.PROVIDER.contract()["managed"] is False`; the tavily digest changes with this release and the README says so.

**Acceptance Scenarios**:

1. **Given** any provider contract, **When** read by a consumer, **Then** `managed` is present and boolean.
2. **Given** `managed: true` and `auth.accepts` of `[{kind: none}]`, **When** a workflow supplies `auth` for the binding, **Then** compile fails with a message that the provider is platform-managed and takes no credential.
3. **Given** `managed: true` and `auth.accepts` listing `token` (tavily), **When** a workflow supplies `auth`, **Then** the workflow's own credential is used, as today.

---

### User Story 4 - Add a new cell without touching cli or api (Priority: P3)

A maintainer adds `video → transcript` or `image → caption` by adding a registry entry (payload and options schemas) and shipping the matching processor image. cli validates the new output type on the next connectors release; api enforces it at call time from the same data.

**Why this priority**: The registry's reason to exist is that growth is a connectors release, not a three-repo contract change. This story is the test of that claim.

**Independent Test**: Add a fixture cell to the registry in a test, rebuild the contract, and assert that the operation's `outputs` item enum and the exported registry both list it with no other change to the contract shape.

**Acceptance Scenarios**:

1. **Given** a second cell is added to the registry, **When** the contract is built, **Then** `outputs.items.enum` is the sorted union of output types across all cells and `media.registry` carries the new cell's schemas.
2. **Given** a workflow compiled against the old contract, **When** it requests the new output type, **Then** the compiler rejects it (unknown output type) until the workflow is recompiled against the new connectors release.

---

### Edge Cases

- `attachment` that is not an attachment of the run's trigger event (unknown id, an attachment of another run or workspace, or a run whose trigger carried no attachments): the input schema cannot check this; the api MUST, and MUST answer `integration.attachment_not_found`. The runner never resolves the reference itself.
- Attachment whose recorded content type is missing or not one of the registry's media types: fails at call time with `integration.media_unsupported` carrying the recorded content type.
- Output type registered somewhere, but not for this attachment's media type (for example `transcript` requested for an image once `image → caption` exists): fails at call time with `integration.output_unsupported` naming the media type and the output type. The compiler cannot catch this because the media type is only known from the stored attachment.
- `outputs` empty, duplicated, or holding a value not in the registry: rejected by the input schema (`minItems: 1`, `uniqueItems`, enum).
- `options` keyed by an output type not in `outputs`: rejected at call time with `integration.options_unused`; the schema cannot express the dependency.
- Caller supplies media bytes, a URL or an object key (`data`, `content`, `url`, `file`, `object_key`): rejected, the input schema closes additional properties.
- Caller supplies `media_type`: rejected for the same reason. The platform derives it from the stored attachment's recorded content type, never from the caller.
- A call whose processor fails after partially producing outputs: the call fails as a whole; `outputs` is never partial. `usage.minutes` is present on the failure and reports the minutes the backend consumed (zero when it consumed none), so the api can meter failed calls from the same field as successful ones.
- `duration_seconds` absent: allowed for media types that have no duration (image, document). For audio and video it is present.

## Requirements *(mandatory)*

### Functional Requirements

**Provider and contract**

- **FR-001**: The package MUST register a provider named `media` under the `outcomeci.connectors` entry point group, at `outcomeci_connectors.providers.media:PROVIDER`.
- **FR-002**: `media` MUST declare `auth=(NoAuth(),)`, so the contract's `auth.accepts` is `[{"kind": "none", "credential": []}]`. A workflow binding `uses: media` MUST NOT supply `auth`; consumers reject it on the `kind: none` + `managed: true` combination (FR-006).
- **FR-003**: `media` MUST declare `base_url=None`, and its contract MUST NOT carry `base_url_from`. `managed: true` (FR-005) is the sole signal that the platform executes the operation; no new `base_url_from` value and no separate `execution` key is introduced. A runtime that sees `managed: true` with no `base_url` routes the call to the api's processor path instead of the broker's HTTP path.
- **FR-004**: `media` MUST expose exactly one operation, `process`, with `side_effect: "execute"` and `max_requests` of 10 (the same bound as tavily).
- **FR-005**: `Provider` MUST gain a `managed: bool = False` field, emitted in every contract as `managed`. `tavily` and `media` set it to `True`. This changes every provider's digest once (the key is always present) and the tavily README section MUST note that workflows locked to the previous contract recompile on upgrade, as the Slack scope-serialization note does today.
- **FR-006**: A `managed` provider that accepts `none` is platform-only: the platform supplies execution and metering and the workflow supplies nothing. A `managed` provider that accepts credential kinds (tavily) uses the workflow's credential when one is bound and the platform's when it is not. The contract states no more than the flag and the accepted kinds; the choice is a runtime responsibility, as the README already says for tavily.

**Operation input**

- **FR-007**: `process.input` MUST be a closed object (`additionalProperties: false`) with required `attachment` and `outputs`, optional `options`.
- **FR-008**: `attachment` MUST be a non-empty string of at most 256 characters: a reference to one attachment of the current run's trigger event, spelled as the attachment identifier the trigger payload exposes (v1: email trigger attachments). The schema imposes no pattern; the reference is opaque to the runner, which forwards it unchanged, and meaningful only to the api, which resolves it against the run's trigger event and rejects any reference that does not belong to it (`integration.attachment_not_found`).
- **FR-009**: `outputs` MUST be an array, `minItems: 1`, `uniqueItems: true`, whose items are an enum of every output type present in any registry cell. The enum is derived from the registry at import time, never hand-maintained.
- **FR-010**: `options` MUST be a closed object whose property names are the same output-type enum and whose value for each output type is that type's options schema from the registry. When one output type appears under several media types with different options schemas, the input schema uses their `anyOf`; the api validates the exact schema once the media type is known.
- **FR-011**: The input MUST NOT accept media bytes, URLs, file uploads, object keys or a caller-supplied media type. These are not optional fields; they do not exist. The media type comes from the stored attachment's recorded content type.

**Operation output**

- **FR-012**: `process.expose` MUST expose `media_type`, `outputs`, `provider`, `model`, `duration_seconds` and `usage` from the result body, by those names.
- **FR-013**: The module MUST export `OUTPUT` (the result schema): a closed object requiring `media_type` (enum of registry media types), `outputs` (object), `provider` (string), `model` (string) and `usage` (`{minutes: number >= 0}`), with optional `duration_seconds` (number >= 0). `outputs` values are validated per cell by the registry, not by `OUTPUT`.
- **FR-014**: `usage.minutes` is the metering unit for every media type, including those without a duration; a backend that bills per item reports its minute equivalent. Missing usage is a contract violation, not zero. `usage.minutes` is present on failed calls as well as successful ones.

**Support registry**

- **FR-015**: The module MUST export `REGISTRY`, a mapping `media_type → output_type → {"payload": <JSON Schema>, "options": <JSON Schema>, "description": str}`. It is plain data (dicts, lists, strings), JSON-serialisable, and importable without side effects.
- **FR-016**: The contract MUST carry the registry verbatim under a top-level key `media: {"registry": REGISTRY}` on the media provider contract, so the digest covers it and the api validates at call time from the locked contract rather than from whatever connectors version it happens to import. cli reads the same key for its compile-time output-type check. Other providers' contracts MUST NOT carry the key.
- **FR-017**: The initial registry MUST contain exactly `audio → transcript`, payload `{text: string, language: string, segments?: [{start: number, end: number, text: string}]}` (closed objects, `segments` items closed, `end >= start` is not schema-checked), options `{language?: string}` where `language` is a BCP-47 tag (`^[A-Za-z]{2,3}(-[A-Za-z0-9]{1,8})*$`, a hint, not a requirement the backend must honour).
- **FR-018**: Media types are the closed set `audio`, `image`, `video`, `document`. A registry cell for a media type outside the set is a programming error raised at import.
- **FR-019**: Every schema in the registry, `process.input` and `OUTPUT` MUST pass `jsonschema.Draft202012Validator.check_schema`, enforced by a test.

**Grants**

- **FR-020**: `process.grantable` MUST be exactly `{"outputs": Grantable(field="outputs")}`. A grant pins the whole `outputs` list, as tavily's domain grants pin a whole list.
- **FR-021**: Grant values MUST be static: a literal list of output types in the workflow file. The compiler rejects an expression. This is a cli rule, not a contract field: cli applies it to every `managed: true` provider, generalising the rule it already applies to tavily, so `media` needs no per-provider rule. The README states it.

**Failure codes (api surface, named here because the registry decides them)**

- **FR-022**: The README MUST document the call-time failures a workflow can see and what each means: `integration.attachment_not_found` (the reference is not an attachment of the run's trigger event), `integration.media_unsupported` (the attachment's recorded content type is not a registry media type), `integration.output_unsupported` (output type not registered for the attachment's media type), `integration.options_unused` (options for an output type not requested).

**Documentation and tests**

- **FR-023**: README MUST gain a "Media processing" section in the style of "Tavily search": the binding with no `auth`, how a step names a trigger attachment, the `can:` grant form, the registry table, the output shape, the metering unit and the failure codes, plus a "Layout" line for `media.py`.
- **FR-024**: Tests MUST cover: entry-point registration; contract keys (`managed`, absence of `base_url_from`, `media.registry`); input acceptance and rejection for each edge case above that the schema can express; `OUTPUT` acceptance of the example result; registry schemas being valid; `tavily` carrying `managed: true`; and that adding a fixture cell changes only the enum and the registry.

### Key Entities

- **Provider `media`**: the `uses: media` binding. Managed, platform-executed, no credential, one operation.
- **Operation `process`**: one trigger attachment in, one result out. Grantable on `outputs` only.
- **Registry cell**: `(media_type, output_type)` → payload schema, options schema, description. The unit of growth; present or absent, never stubbed.
- **Trigger attachment**: a file that arrived with the run's trigger event (v1: email), identified by the attachment identifier the trigger payload exposes. Its recorded content type decides the media type. Resolved by the api, never by the runner.
- **Result**: `media_type`, `outputs` keyed by output type, backend `provider` and `model`, optional `duration_seconds`, `usage.minutes`.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A workflow with `uses: media` and `can: [media.process: {outputs: [transcript]}]` compiles against this release with no cli change beyond reading `managed` and `media.registry`.
- **SC-002**: The example input and output in Contract C1 validate against the shipped schemas, and every invalid example in Edge Cases that the schema can express is rejected, in the test suite.
- **SC-003**: Adding a registry cell in a test changes the contract only in `outputs.items.enum`, `options.properties` and `media.registry`; no other key of any provider's contract moves.
- **SC-004**: `grep -rn '"tavily"'` in cli and api dispatch code can be replaced by a `managed` check once this release is pinned; no consumer needs the string "media".
- **SC-005**: `tavily`'s digest changes exactly once in this release (the `managed` key) and the README records why.

## Assumptions

- The processor image, the api endpoint that runs it, attachment storage and the trigger-event ownership check live in api and the processor repo; this spec covers only what the contract says about them.
- Email trigger payloads already expose a stable per-attachment identifier and the api stores each attachment with its content type; the `attachment` reference reuses that identifier rather than introducing a new one.
- `max_requests` 10 per run is enough for a first release; a long recording is one call.
- The registry's `description` string is for www and the compiler's error messages, not for the agent's prompt; the operation `description` serves the agent.
- `document` is in the media-type set now so a future `document → text` cell is additive; no cell ships for it.
- `Grantable(field=...)` equality semantics (runtime fills when omitted, refuses when different) apply to a list value as they do for tavily's domain lists; no new grantable kind is needed.
