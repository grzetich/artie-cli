"""Shared helpers for inspecting schemas and examples.

These exist because several checks were crediting *presence* where they meant
to credit *substance*. An example key that holds unparseable text, or a schema
that declares `properties: {}` and nothing else, tells an agent nothing — but
a truthiness test counts both as documented.

Nothing here raises. Callers get a boolean or a list of human-readable
problems, because these feed check findings rather than control flow.
"""

from __future__ import annotations

import json
from typing import Any

import yaml

# Keys that carry real meaning about a value's shape. A schema with none of
# them constrains nothing, however many other keys it has.
_SUBSTANTIVE_KEYS = frozenset(
    {
        "type",
        "properties",
        "items",
        "enum",
        "const",
        "$ref",
        "allOf",
        "oneOf",
        "anyOf",
        "not",
        "format",
        "additionalProperties",
        "patternProperties",
        "prefixItems",
    }
)

_REF_PREFIX = "#/components/schemas/"

# Depth guard shared by the recursive walkers below. Deliberately generous:
# real specs nest far shallower, and this only exists so a malformed or
# self-referential document can't exhaust the stack.
_MAX_DEPTH = 30

_JSON_TYPE_MAP: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "array": (list,),
    "object": (dict,),
    "null": (type(None),),
}


def resolve_ref(schema: Any, components: dict[str, Any], depth: int = 0) -> Any:
    """Follow `$ref` into components.schemas until we reach a concrete schema.

    Returns the schema unchanged if it isn't a ref, if the target is missing,
    or if we hit the depth guard (which a `$ref` cycle would).
    """
    if depth > _MAX_DEPTH or not isinstance(schema, dict):
        return schema
    ref = schema.get("$ref")
    if not isinstance(ref, str) or not ref.startswith(_REF_PREFIX):
        return schema
    schemas = components.get("schemas") if isinstance(components, dict) else None
    if not isinstance(schemas, dict):
        return schema
    target = schemas.get(ref[len(_REF_PREFIX):])
    if target is None:
        return schema
    return resolve_ref(target, components, depth + 1)


def is_vacuous_schema(
    schema: Any, components: dict[str, Any] | None = None, depth: int = 0
) -> bool:
    """True if this schema constrains nothing an agent could act on.

    Vacuous means: not a mapping, empty, `properties: {}` with no other
    substantive key, or `type: object` with no properties and no
    additionalProperties. A `$ref` is resolved first, so a reference to an
    empty component is just as vacuous as an inline empty object.

    A bare `type: string` is NOT vacuous — it tells an agent the shape. The
    bar here is "says something", not "says everything".
    """
    if depth > _MAX_DEPTH:
        return False
    components = components or {}
    schema = resolve_ref(schema, components, depth)

    if not isinstance(schema, dict) or not schema:
        return True

    if not (_SUBSTANTIVE_KEYS & schema.keys()):
        return True

    properties = schema.get("properties")
    if isinstance(properties, dict) and not properties:
        # `properties: {}` is the common ReadMe/Stainless placeholder. It only
        # counts as vacuous when nothing else in the schema carries shape.
        others = (_SUBSTANTIVE_KEYS & schema.keys()) - {"properties", "type"}
        if not others:
            return True

    if schema.get("type") == "object" and "properties" not in schema:
        if not schema.get("additionalProperties") and not schema.get(
            "patternProperties"
        ):
            return True

    # A combinator whose every branch is vacuous is itself vacuous.
    for combinator in ("allOf", "oneOf", "anyOf"):
        branches = schema.get(combinator)
        if isinstance(branches, list) and branches:
            if all(
                is_vacuous_schema(branch, components, depth + 1)
                for branch in branches
            ):
                return True

    return False


def parse_example(raw: Any) -> tuple[bool, Any, str | None]:
    """Coerce an example value into structured data.

    Returns (ok, value, error). Examples arrive already-structured when the
    spec author inlined them as YAML/JSON, or as a string when they pasted a
    serialized payload. A string that is meant to be a payload but doesn't
    parse is the malformed case worth catching.

    Strings that were never meant to be structured (a plain `example: "hello"`
    on a string field) parse as themselves and are not errors.
    """
    if raw is None:
        return False, None, "example is null"

    if isinstance(raw, (dict, list, int, float, bool)):
        return True, raw, None

    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return False, None, "example is an empty string"
        # Only try structured parsing when it looks like a payload. Otherwise a
        # legitimate scalar example would be reported as malformed.
        if text[0] in "{[":
            try:
                return True, json.loads(text), None
            except json.JSONDecodeError:
                pass
            try:
                loaded = yaml.safe_load(text)
            except yaml.YAMLError as exc:
                first_line = str(exc).split("\n", 1)[0]
                return False, None, f"example is not valid JSON or YAML: {first_line}"
            if loaded is None:
                return False, None, "example parsed as empty"
            return True, loaded, None
        return True, text, None

    return True, raw, None


def validate_example(
    example: Any, schema: Any, components: dict[str, Any] | None = None
) -> list[str]:
    """Check an example against its schema. Returns human-readable violations.

    Deliberately shallow: type agreement, required properties, and enum
    membership. This is not a JSON Schema validator and does not try to be —
    it catches the errors that actually appear in published specs (an example
    missing a required field, or an object example on an array schema) without
    adding a dependency or false-failing on exotic keywords.

    An empty list means "no problems found", which is not the same as "valid".
    """
    components = components or {}
    return _validate(example, schema, components, path="", depth=0)


def _validate(
    example: Any,
    schema: Any,
    components: dict[str, Any],
    path: str,
    depth: int,
) -> list[str]:
    if depth > _MAX_DEPTH:
        return []
    schema = resolve_ref(schema, components, depth)
    if not isinstance(schema, dict) or not schema:
        return []

    where = path or "root"
    problems: list[str] = []

    declared_type = schema.get("type")
    if isinstance(declared_type, str):
        expected = _JSON_TYPE_MAP.get(declared_type)
        # bool is a subclass of int in Python; an integer schema must not
        # accept True, so screen it out before the isinstance check.
        mistyped_bool = declared_type in ("integer", "number") and isinstance(
            example, bool
        )
        if expected and (mistyped_bool or not isinstance(example, expected)):
            return [
                f"{where}: example is {type(example).__name__}, "
                f"schema declares {declared_type}"
            ]

    enum = schema.get("enum")
    if isinstance(enum, list) and enum and not isinstance(example, (dict, list)):
        if example not in enum:
            problems.append(f"{where}: example value {example!r} is not in enum")

    if isinstance(example, dict):
        required = schema.get("required")
        if isinstance(required, list):
            missing = [
                key
                for key in required
                if isinstance(key, str) and key not in example
            ]
            if missing:
                problems.append(
                    f"{where}: example omits required "
                    f"{'properties' if len(missing) > 1 else 'property'} "
                    f"{', '.join(sorted(missing))}"
                )
        properties = schema.get("properties")
        if isinstance(properties, dict):
            for key, value in example.items():
                sub_schema = properties.get(key)
                if sub_schema is not None:
                    problems.extend(
                        _validate(
                            value,
                            sub_schema,
                            components,
                            f"{path}.{key}" if path else str(key),
                            depth + 1,
                        )
                    )

    if isinstance(example, list):
        items = schema.get("items")
        if isinstance(items, dict):
            # One representative element is enough; reporting every bad element
            # of a 50-item example would bury the finding.
            for index, value in enumerate(example[:3]):
                problems.extend(
                    _validate(
                        value, items, components, f"{path}[{index}]", depth + 1
                    )
                )

    return problems
