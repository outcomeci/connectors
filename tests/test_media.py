from __future__ import annotations

import json
from importlib.metadata import entry_points

import jsonschema
import pytest

from outcomeci_connectors.providers import media
from outcomeci_connectors.providers.media import (
    MEDIA_TYPES,
    OUTPUT,
    PROVIDER,
    REGISTRY,
    TRANSCRIPT,
    TRANSCRIPT_OPTIONS,
    _check_registry,
    _input_schema,
    _output_schema,
    _provider,
)

CONTRACT = PROVIDER.contract()
PROCESS = CONTRACT["operations"]["process"]
CALL = {"attachment": "att_01", "outputs": ["transcript"]}
RESULT = {
    "media_type": "audio",
    "outputs": {
        "transcript": {
            "text": "hello",
            "language": "en",
            "segments": [{"start": 0.0, "end": 2.4, "text": "hello"}],
        }
    },
    "provider": "backend",
    "model": "model-1",
    "duration_seconds": 61.2,
    "usage": {"minutes": 1.02},
}
CAPTION = {
    "description": "A one-line caption.",
    "payload": {
        "type": "object",
        "required": ["text"],
        "properties": {"text": {"type": "string"}},
        "additionalProperties": False,
    },
    "options": {
        "type": "object",
        "properties": {"style": {"type": "string", "enum": ["short", "long"]}},
        "additionalProperties": False,
    },
}
GROWN = {**REGISTRY, "image": {"caption": CAPTION}}


def test_entry_point_managed_no_auth_no_origin():
    registered = {item.name: item.load() for item in entry_points(group="outcomeci.connectors")}
    assert registered["media"] is PROVIDER
    assert CONTRACT["name"] == "media"
    assert CONTRACT["managed"] is True
    assert CONTRACT["base_url"] is None
    assert "base_url_from" not in CONTRACT
    assert CONTRACT["auth"] == {"accepts": [{"kind": "none", "credential": []}]}
    assert CONTRACT["max_requests"] == 10
    assert CONTRACT["watchers"] == {} and CONTRACT["receiver"] is None
    assert set(CONTRACT["operations"]) == {"process"}


def test_contract_snapshot():
    expected = {
        "description": PROCESS["description"],
        "input": {
            "type": "object",
            "required": ["attachment", "outputs"],
            "properties": {
                "attachment": {"type": "string", "minLength": 1, "maxLength": 256},
                "outputs": {
                    "type": "array",
                    "minItems": 1,
                    "uniqueItems": True,
                    "items": {"type": "string", "enum": ["transcript"]},
                },
                "options": {
                    "type": "object",
                    "propertyNames": {"enum": ["transcript"]},
                    "properties": {"transcript": TRANSCRIPT_OPTIONS},
                    "additionalProperties": False,
                },
            },
            "additionalProperties": False,
        },
        "request": {"method": "POST", "path": "/process", "body": "{{ input }}"},
        "response": {
            "expose": {
                "media_type": "body.media_type",
                "outputs": "body.outputs",
                "provider": "body.provider",
                "model": "body.model",
                "duration_seconds": "body.duration_seconds",
                "usage": "body.usage",
            }
        },
        "side_effect": "execute",
        "grantable": {"outputs": {"field": "outputs"}},
        "deny": [],
    }
    assert expected == PROCESS
    assert "attachment id from the trigger payload" in PROCESS["description"]
    assert "—" not in PROCESS["description"]
    assert CONTRACT["media"] == {"registry": REGISTRY}
    assert json.loads(json.dumps(CONTRACT)) == CONTRACT
    assert PROVIDER.digest() == PROVIDER.digest()


def test_grantable_is_outputs_only():
    assert PROCESS["grantable"] == {"outputs": {"field": "outputs"}}


def test_schemas_are_valid_draft_2020_12():
    jsonschema.Draft202012Validator.check_schema(PROCESS["input"])
    jsonschema.Draft202012Validator.check_schema(OUTPUT)
    for cells in REGISTRY.values():
        for cell in cells.values():
            jsonschema.Draft202012Validator.check_schema(cell["payload"])
            jsonschema.Draft202012Validator.check_schema(cell["options"])


@pytest.mark.parametrize(
    "call",
    [
        CALL,
        {**CALL, "options": {"transcript": {"language": "en-US"}}},
        {**CALL, "options": {"transcript": {"language": "en"}}},
        {**CALL, "options": {"transcript": {}}},
        {**CALL, "options": {}},
        {**CALL, "attachment": "a" * 256},
    ],
)
def test_accepts_example_input(call):
    jsonschema.validate(call, PROCESS["input"])


@pytest.mark.parametrize(
    "patch",
    [
        {"outputs": []},
        {"outputs": ["transcript", "transcript"]},
        {"outputs": ["summary"]},
        {"outputs": "transcript"},
        {"attachment": ""},
        {"attachment": "a" * 257},
        {"attachment": 1},
        {"options": {"summary": {}}},
        {"options": {"transcript": {"temperature": 0}}},
        {"options": {"transcript": {"language": "english!"}}},
        {"options": {"transcript": {"language": ""}}},
        {"options": []},
        {"media_type": "audio"},
        {"data": "AAAA"},
        {"content": "AAAA"},
        {"url": "https://example.com/a.mp3"},
        {"file": "a.mp3"},
        {"object_key": "runs/1/a.mp3"},
    ],
)
def test_rejects_inputs_the_schema_can_express(patch):
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**CALL, **patch}, PROCESS["input"])


@pytest.mark.parametrize("field", list(CALL))
def test_attachment_and_outputs_are_required(field):
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            {key: value for key, value in CALL.items() if key != field}, PROCESS["input"]
        )


def test_options_for_an_unrequested_output_is_a_call_time_rule():
    # The schema cannot express the dependency between `options` keys and
    # `outputs`; the api answers `integration.options_unused` at call time.
    # Flipping this test is a spec change (plan F7).
    schema = _input_schema(GROWN)
    jsonschema.validate({**CALL, "options": {"caption": {}}}, schema)


def test_output_accepts_the_example_result_and_requires_usage():
    jsonschema.validate(RESULT, OUTPUT)
    jsonschema.validate(RESULT["outputs"]["transcript"], REGISTRY["audio"]["transcript"]["payload"])
    jsonschema.validate({**RESULT, "outputs": {}}, OUTPUT)
    without_duration = {key: value for key, value in RESULT.items() if key != "duration_seconds"}
    jsonschema.validate(without_duration, OUTPUT)
    jsonschema.validate({**RESULT, "usage": {"minutes": 0}}, OUTPUT)
    for broken in (
        {key: value for key, value in RESULT.items() if key != "usage"},
        {**RESULT, "usage": {}},
        {**RESULT, "usage": {"minutes": -1}},
        {**RESULT, "usage": {"minutes": 1, "credits": 1}},
        {**RESULT, "media_type": "image"},
        {**RESULT, "media_type": "gif"},
        {**RESULT, "provider": ""},
        {**RESULT, "duration_seconds": -1},
        {**RESULT, "extra": True},
    ):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(broken, OUTPUT)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"text": "x"}, REGISTRY["audio"]["transcript"]["payload"])
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            {"text": "x", "language": "en", "segments": [{"start": 0, "end": 1}]},
            REGISTRY["audio"]["transcript"]["payload"],
        )


def test_registry_is_plain_data():
    assert MEDIA_TYPES == ("audio", "image", "video", "document")
    assert REGISTRY == {
        "audio": {
            "transcript": {
                "description": "Speech in the recording as text with language and timed segments.",
                "payload": {
                    "type": "object",
                    "required": ["text", "language"],
                    "properties": {
                        "text": {"type": "string"},
                        "language": {"type": "string"},
                        "segments": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "required": ["start", "end", "text"],
                                "properties": {
                                    "start": {"type": "number", "minimum": 0},
                                    "end": {"type": "number", "minimum": 0},
                                    "text": {"type": "string"},
                                },
                                "additionalProperties": False,
                            },
                        },
                    },
                    "additionalProperties": False,
                },
                "options": {
                    "type": "object",
                    "properties": {
                        "language": {
                            "type": "string",
                            "pattern": r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{1,8})*$",
                        }
                    },
                    "additionalProperties": False,
                },
            }
        }
    }
    assert REGISTRY["audio"]["transcript"]["payload"] is TRANSCRIPT
    assert json.loads(json.dumps(REGISTRY)) == REGISTRY
    for cells in REGISTRY.values():
        for cell in cells.values():
            assert set(cell) == {"description", "payload", "options"}


def test_registry_rejects_an_unknown_media_type_or_incomplete_cell():
    with pytest.raises(ValueError, match="gif"):
        _check_registry({"gif": {"caption": CAPTION}})
    with pytest.raises(ValueError, match="payload"):
        _check_registry({"image": {"caption": {"description": "x", "options": {}}}})
    with pytest.raises(ValueError):
        _provider({"gif": {"caption": CAPTION}})
    _check_registry({})


def _flatten(value, prefix=""):
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            out.update(_flatten(item, f"{prefix}{key}."))
        return out
    return {prefix.rstrip("."): json.dumps(value, sort_keys=True)}


def test_adding_a_cell_changes_only_the_enum_options_and_registry():
    grown = _provider(GROWN).contract()
    before, after = _flatten(CONTRACT), _flatten(grown)
    changed = {key for key in set(before) | set(after) if before.get(key) != after.get(key)}
    prefixes = (
        "operations.process.input.properties.outputs.items.enum",
        "operations.process.input.properties.options.properties.",
        "operations.process.input.properties.options.propertyNames.enum",
        "media.registry.",
    )
    assert changed and all(key.startswith(prefixes) for key in changed), changed
    assert grown["operations"]["process"]["input"]["properties"]["outputs"]["items"]["enum"] == [
        "caption",
        "transcript",
    ]
    assert grown["media"]["registry"]["image"]["caption"] == CAPTION
    assert _output_schema(GROWN)["properties"]["media_type"]["enum"] == ["audio", "image"]
    assert _provider(GROWN).digest() != PROVIDER.digest()


def test_anyof_when_one_output_type_has_two_options_schemas():
    video_options = {
        "type": "object",
        "properties": {"language": {"type": "string"}, "speakers": {"type": "integer"}},
        "additionalProperties": False,
    }
    registry = {
        **REGISTRY,
        "video": {"transcript": {**REGISTRY["audio"]["transcript"], "options": video_options}},
    }
    schema = _input_schema(registry)
    assert schema["properties"]["outputs"]["items"]["enum"] == ["transcript"]
    assert schema["properties"]["options"]["properties"]["transcript"] == {
        "anyOf": [TRANSCRIPT_OPTIONS, video_options]
    }
    same = {**REGISTRY, "video": {"transcript": REGISTRY["audio"]["transcript"]}}
    assert _input_schema(same)["properties"]["options"]["properties"]["transcript"] == (
        TRANSCRIPT_OPTIONS
    )


def test_no_other_provider_carries_the_media_key():
    for item in entry_points(group="outcomeci.connectors"):
        contract = item.load().contract()
        assert ("media" in contract) is (item.name == "media"), item.name
    assert media.PROVIDER.contract()["media"]["registry"] is REGISTRY
