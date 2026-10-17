"""Platform-run processing of a trigger attachment into typed outputs.

`media` is executed by the platform itself, not by an HTTP call to a
third-party origin, so there is no third-party API to document here. The
provider is managed (`managed: true`), takes no credential (`auth.accepts` is
`none`) and has no origin (`base_url` None with no `base_url_from`). Its one
operation, `process`, names one attachment of the current run's trigger event
and the output types to produce; the platform derives the media type from the
stored attachment's recorded content type.

`REGISTRY` is the support table, media type → output type → payload schema,
options schema and description. It is carried verbatim on the contract under
`media.registry`, so the digest covers it and the api validates call-time
results against the locked contract. `INPUT` and `OUTPUT` are derived from
the registry at import; neither is hand-maintained.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from ..provider import Grantable, NoAuth, Operation, Provider

__all__ = ["INPUT", "MEDIA_TYPES", "OUTPUT", "PROVIDER", "REGISTRY"]

# The closed set of media types a registry cell may use. `document` is here
# so a future `document → text` cell is additive; no cell ships for it.
MEDIA_TYPES = ("audio", "image", "video", "document")

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

REGISTRY: dict[str, dict[str, dict[str, Any]]] = {
    "audio": {
        "transcript": {
            "description": "Speech in the recording as text with language and timed segments.",
            "payload": TRANSCRIPT,
            "options": TRANSCRIPT_OPTIONS,
        },
    },
}

CELL_KEYS = ("description", "payload", "options")


def _check_registry(registry: Mapping[str, Mapping[str, Mapping[str, Any]]]) -> None:
    """Raise `ValueError` for a media type outside `MEDIA_TYPES` or an incomplete cell."""
    for media_type, cells in registry.items():
        if media_type not in MEDIA_TYPES:
            raise ValueError(f"unknown media type in registry: {media_type}")
        for output_type, cell in cells.items():
            missing = [key for key in CELL_KEYS if key not in cell]
            if missing:
                raise ValueError(f"registry cell {media_type}.{output_type} lacks {missing}")


def _output_types(registry: Mapping[str, Mapping[str, Any]]) -> list[str]:
    return sorted({output_type for cells in registry.values() for output_type in cells})


def _input_schema(registry: Mapping[str, Mapping[str, Mapping[str, Any]]]) -> dict[str, Any]:
    """The `process` input schema, derived from the registry.

    `outputs` enumerates every output type present in any cell. `options` is
    keyed by the same enum; an output type that appears under several media
    types with different options schemas takes their `anyOf`, and the api
    validates the exact schema once the media type is known.
    """
    output_types = _output_types(registry)
    options: dict[str, Any] = {}
    for output_type in output_types:
        schemas: list[Any] = []
        for cells in registry.values():
            if output_type in cells and cells[output_type]["options"] not in schemas:
                schemas.append(cells[output_type]["options"])
        options[output_type] = schemas[0] if len(schemas) == 1 else {"anyOf": schemas}
    return {
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
                "properties": options,
                "additionalProperties": False,
            },
        },
        "additionalProperties": False,
    }


def _output_schema(registry: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """The `process` result schema.

    `media_type` enumerates the media types present in the registry, not all
    of `MEDIA_TYPES`: a result for a media type with no cell cannot exist.
    `outputs` values are validated per cell from the registry, not here.
    """
    return {
        "type": "object",
        "required": ["media_type", "outputs", "provider", "model", "usage"],
        "properties": {
            "media_type": {"type": "string", "enum": sorted(registry)},
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


_check_registry(REGISTRY)
INPUT = _input_schema(REGISTRY)
OUTPUT = _output_schema(REGISTRY)


@dataclass(frozen=True)
class _MediaProvider(Provider):
    """A provider whose contract carries the support registry under `media.registry`."""

    registry: Mapping[str, Mapping[str, Mapping[str, Any]]] = field(
        default_factory=lambda: REGISTRY
    )

    def contract(self) -> dict[str, Any]:
        return {**super().contract(), "media": {"registry": self.registry}}


def _operation(registry: Mapping[str, Mapping[str, Mapping[str, Any]]]) -> Operation:
    return Operation(
        description=(
            "Process one attachment of the run's trigger event into typed outputs. Supply "
            "attachment (the attachment id from the trigger payload) and outputs, the output "
            "types to produce (the input schema enumerates the types the registry offers); "
            "options may carry per-output settings keyed by output type. The platform picks "
            "the media type from the stored attachment. "
            "Returns media_type, outputs keyed by output type, provider, model, "
            "duration_seconds and usage.minutes. Refuses media bytes, URLs, uploads, object "
            "keys and a caller-supplied media type."
        ),
        method="POST",
        path="/process",
        input=_input_schema(registry),
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


def _provider(registry: Mapping[str, Mapping[str, Mapping[str, Any]]]) -> _MediaProvider:
    _check_registry(registry)
    return _MediaProvider(
        name="media",
        base_url=None,
        auth=(NoAuth(),),
        max_requests=10,
        managed=True,
        operations={"process": _operation(registry)},
        registry=registry,
    )


PROVIDER = _provider(REGISTRY)
