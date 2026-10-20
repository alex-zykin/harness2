"""Versioned, strict data-only boundary between a product and offline replay.

The small validator supports exactly the JSON Schema keywords used below. No dependency,
network reference resolution, commands or object construction from input are involved.
"""

import re

VERSION = "1.0"
POLICIES = ["draft_only", "suppress", "insufficient"]
NEXT_STEPS = ["review_draft", "record_opt_out", "request_details", "verify_signal", "request_permission"]
IDENTIFIER = {"type": "string", "pattern": r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}$"}


def object_schema(properties):
    return {"type": "object", "properties": properties,
            "required": list(properties), "additionalProperties": False}


EPISODE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "urn:harness2-business:episode:1.0",
    **object_schema({
        "schema_version": {"const": VERSION}, "synthetic": {"const": True},
        "episode_id": IDENTIFIER, "instance_id": IDENTIFIER, "product_id": IDENTIFIER,
        "contact_id": IDENTIFIER, "thread_id": IDENTIFIER,
        "permission": {"enum": ["allowed", "unknown", "denied"]},
        "suppressed": {"type": "boolean"},
        "event": object_schema({
            "event_id": IDENTIFIER,
            "kind": {"enum": ["inbound_email", "reply", "unsubscribe", "quote_request", "click"]},
            "text": {"type": "string", "maxLength": 16000},
        }),
    }),
}
RESULT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "urn:harness2-business:result:1.0",
    **object_schema({
        "schema_version": {"const": VERSION}, "episode_id": IDENTIFIER,
        "authority": {"const": "advisory_only"}, "policy": {"enum": POLICIES},
        "next_step": {"enum": NEXT_STEPS},
        "evidence_event_ids": {"type": "array", "minItems": 1, "maxItems": 1, "items": IDENTIFIER},
    }),
}
EXPECTED_SCHEMA = object_schema({
    "policy": {"enum": POLICIES}, "next_step": {"enum": NEXT_STEPS},
})


def validate(schema, value, path="$"):
    kind = schema.get("type")
    checks = {"object": dict, "string": str, "boolean": bool, "array": list}
    if kind and type(value) is not checks[kind]:
        raise ValueError(f"{path}: expected {kind}")
    if "const" in schema and (type(value) is not type(schema["const"]) or value != schema["const"]):
        raise ValueError(f"{path}: unsupported constant/version")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{path}: unsupported value")
    if kind == "object":
        properties = schema["properties"]
        if set(value) != set(properties):
            raise ValueError(f"{path}: missing or unknown fields")
        for key, child in properties.items():
            validate(child, value[key], f"{path}.{key}")
    elif kind == "string":
        if len(value) > schema.get("maxLength", 16000):
            raise ValueError(f"{path}: text too long")
        if "pattern" in schema and not re.fullmatch(schema["pattern"], value):
            raise ValueError(f"{path}: invalid identifier")
    elif kind == "array":
        if not schema.get("minItems", 0) <= len(value) <= schema.get("maxItems", 100):
            raise ValueError(f"{path}: wrong array length")
        for child in value:
            validate(schema["items"], child, path + "[]")
    return value


def validate_episode(document):
    return validate(EPISODE_SCHEMA, document)


def validate_result(document, episode):
    validate_episode(episode)
    validate(RESULT_SCHEMA, document)
    if document["episode_id"] != episode["episode_id"]:
        raise ValueError("Result episode does not match input")
    if document["evidence_event_ids"] != [episode["event"]["event_id"]]:
        raise ValueError("Result evidence does not match input")
    blocked = episode["suppressed"] or episode["permission"] == "denied" or episode["event"]["kind"] == "unsubscribe"
    if blocked and (document["policy"], document["next_step"]) != ("suppress", "record_opt_out"):
        raise ValueError("Result cannot overrule suppression, denial or opt-out")
    if episode["permission"] == "unknown" and document["policy"] == "draft_only":
        raise ValueError("Result cannot grant permission")
    return document
