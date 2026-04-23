"""Rebuild context.yml from mappings.yml + api_knowledge.yml.

Applies global rules (camelCase→snake_case, boolean→integer, FK extraction,
timestamp fields, etc.) then overlays per-resource overrides from
api_knowledge.yml.

Usage: python system/rebuild_context.py
Input:  schema/mappings.yml, system/api_knowledge.yml
Output: schema/context.yml

This makes context.yml fully reproducible — no manual field-by-field
decisions needed.
"""

import os
import re
import sys
import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.logging_config import get_logger

logger = get_logger(__name__)


def find_files():
    """Locate input files, supporting project root, schema/, or /app."""
    for base in [".", "/app"]:
        m = os.path.join(base, "schema", "mappings.yml")
        k = os.path.join(base, "system", "api_knowledge.yml")
        if os.path.exists(m) and os.path.exists(k):
            return m, k, os.path.join(base, "schema", "context.yml")
    logger.error("Cannot find mappings.yml and api_knowledge.yml")
    sys.exit(1)


def camel_to_snake(name):
    """Convert camelCase to snake_case."""
    s1 = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def is_fk_object(field_info):
    """Check if a mappings field looks like an FK object (has 'id' in nested_keys)."""
    if field_info.get("api_type") != "object":
        return False
    nested = field_info.get("nested_keys", [])
    return "id" in nested


def is_array_of_objects(field_info):
    """Check if a mappings field is an array of objects."""
    return (
        field_info.get("api_type") == "array"
        and "array_item_keys" in field_info
    )


def build_field_context(api_name, field_info, resource_name, knowledge):
    """Build the context.yml entry for a single field.

    Returns (api_name, context_dict) or None if the field should be skipped
    entirely (id, uri, or skip=true).
    """
    rules = knowledge["global_rules"]
    overrides = knowledge.get("resource_overrides", {}).get(resource_name, {})
    field_overrides = (overrides.get("fields") or {}).get(api_name, {})
    timestamp_fields = set(knowledge.get("timestamp_fields", []))
    type_corrections = knowledge.get("type_corrections", {})
    is_prefix = knowledge.get("is_prefix_renames", {})
    enums = knowledge.get("enums", {})

    # Skip 'id' — handled as PRIMARY KEY automatically by generate_schema.py
    if api_name == "id":
        return None

    # Skip 'uri' — generate_schema.py also hardcodes this, but be explicit
    if api_name in rules.get("always_skip", []):
        return None

    # Check if field override says skip
    if field_overrides.get("skip"):
        return (api_name, {"skip": True})

    # Check global always_skip_fields
    if api_name in rules.get("always_skip_fields", []):
        return (api_name, {"skip": True})

    ctx = {}

    # ── Apply field override first (highest priority) ──
    # If override provides everything, just use it
    if field_overrides:
        # Copy all override keys except skip_fk_extract (internal flag)
        for k, v in field_overrides.items():
            if k != "skip_fk_extract":
                ctx[k] = v

        # If override has skip: true, we already returned None above
        # If override has explicit db_column/db_type/extract_key, done
        if "extract_key" in ctx or "skip" in ctx:
            _apply_enum(ctx, api_name, resource_name, enums)
            return (api_name, ctx) if ctx else None

    api_type = field_info.get("api_type", "unknown")
    skip_fk = field_overrides.get("skip_fk_extract", False)

    # ── Global field renames (created, updated, phoneNumber, externalIds) ──
    field_renames = rules.get("field_renames", {})
    if api_name in field_renames and "db_column" not in ctx:
        for k, v in field_renames[api_name].items():
            if k not in ctx:
                ctx[k] = v

    # ── Timestamp fields ──
    if api_name in timestamp_fields and "db_type" not in ctx:
        ctx["db_type"] = "timestamp"
        # Also apply camelCase rename if not already set
        snake = camel_to_snake(api_name)
        if snake != api_name and "db_column" not in ctx:
            ctx["db_column"] = snake

    # ── Type corrections (global) ──
    if api_name in type_corrections and "db_type" not in ctx:
        ctx["db_type"] = type_corrections[api_name]
        # Also apply camelCase rename if not already set
        snake = camel_to_snake(api_name)
        if snake != api_name and "db_column" not in ctx:
            ctx["db_column"] = snake

    # ── Address flatten ──
    if api_name == "address" and api_type == "object" and "flatten" not in ctx:
        flatten_map = rules.get("address_flatten", {})
        if flatten_map:
            ctx["flatten"] = dict(flatten_map)
            return (api_name, ctx)

    # ── FK object extraction ──
    if (
        rules.get("fk_object_extract")
        and is_fk_object(field_info)
        and not skip_fk
        and "extract_key" not in ctx
        and "skip" not in ctx
        and "flatten" not in ctx
    ):
        ctx["extract_key"] = "id"
        ctx["db_type"] = "integer"
        snake = camel_to_snake(api_name)
        if not snake.endswith("_id"):
            snake = snake + "_id"
        if "db_column" not in ctx:
            ctx["db_column"] = snake

    # ── Array of objects → skip ──
    if (
        rules.get("array_of_objects_skip")
        and is_array_of_objects(field_info)
        and "skip" not in ctx
        and "extract_key" not in ctx
    ):
        ctx["skip"] = True
        return (api_name, ctx) if ctx else None

    # ── Boolean → integer ──
    if rules.get("boolean_to_integer") and api_type == "boolean":
        if "db_type" not in ctx:
            ctx["db_type"] = "integer"
        # Check is_ prefix renames
        if api_name in is_prefix and "db_column" not in ctx:
            ctx["db_column"] = is_prefix[api_name]
        elif "db_column" not in ctx:
            # Still apply camelCase→snake_case
            snake = camel_to_snake(api_name)
            if snake != api_name:
                ctx["db_column"] = snake

    # ── Arrays of primitives → text ──
    if api_type == "array" and not is_array_of_objects(field_info):
        if "db_type" not in ctx and "skip" not in ctx:
            ctx["db_type"] = "text"
        if "db_column" not in ctx:
            snake = camel_to_snake(api_name)
            if snake != api_name:
                ctx["db_column"] = snake

    # ── Objects without special handling → text ──
    if (
        api_type == "object"
        and "extract_key" not in ctx
        and "flatten" not in ctx
        and "skip" not in ctx
    ):
        if "db_type" not in ctx:
            ctx["db_type"] = "text"
        if "db_column" not in ctx:
            snake = camel_to_snake(api_name)
            if snake != api_name:
                ctx["db_column"] = snake

    # ── camelCase → snake_case (catch-all) ──
    if rules.get("camel_to_snake") and "db_column" not in ctx:
        snake = camel_to_snake(api_name)
        if snake != api_name:
            ctx["db_column"] = snake

    # ── Enum prompt_comments ──
    _apply_enum(ctx, api_name, resource_name, enums)

    # Return None for empty context (field passes through unchanged)
    # But we still need an entry if {} to acknowledge the field exists
    return (api_name, ctx)


def _apply_enum(ctx, api_name, resource_name, enums):
    """Apply enum prompt_comment if one exists and isn't already set."""
    if "prompt_comment" in ctx:
        return
    # Try field.resource key first, then field alone
    key = f"{api_name}.{resource_name}"
    if key in enums:
        ctx["prompt_comment"] = enums[key]


def build_resource_context(resource_name, mapping, knowledge):
    """Build the full context.yml entry for one resource."""
    overrides = knowledge.get("resource_overrides", {}).get(resource_name, {})
    result = {}

    # Description
    desc = overrides.get("description", "")
    if desc:
        result["description"] = desc

    # Fields
    fields = {}
    mapping_fields = mapping.get("fields", {})

    # Process fields from mappings
    for api_name, field_info in mapping_fields.items():
        entry = build_field_context(api_name, field_info, resource_name, knowledge)
        if entry:
            name, ctx = entry
            if ctx.get("skip"):
                fields[name] = {"skip": True}
            elif ctx:
                fields[name] = ctx
            else:
                fields[name] = {}

    # Add any override fields not in mappings (e.g. unknown-type FK fields)
    override_fields = overrides.get("fields") or {}
    for api_name, override in override_fields.items():
        if api_name not in fields and api_name not in mapping_fields:
            if override.get("skip"):
                fields[api_name] = {"skip": True}
            else:
                fields[api_name] = {
                    k: v for k, v in override.items() if k != "skip_fk_extract"
                }

    result["fields"] = fields
    return result


def main():
    mappings_path, knowledge_path, output_path = find_files()

    try:
        with open(mappings_path) as f:
            mappings = yaml.safe_load(f)
    except (OSError, yaml.YAMLError) as e:
        logger.exception(f"Failed to load {mappings_path}: {e}")
        sys.exit(1)

    try:
        with open(knowledge_path) as f:
            knowledge = yaml.safe_load(f)
    except (OSError, yaml.YAMLError) as e:
        logger.exception(f"Failed to load {knowledge_path}: {e}")
        sys.exit(1)

    resources = mappings.get("resources", {})
    output = {"resources": {}}

    # Header comment
    header = (
        "# context.yml — Business context for schema generation\n"
        "# AUTO-GENERATED by system/rebuild_context.py\n"
        "# Source: schema/mappings.yml + system/api_knowledge.yml\n"
        "#\n"
        "# prompt_comment: terse inline SQL comment for Claude's system prompt.\n"
        "#   Only add where column name alone isn't enough (enums, non-obvious semantics).\n"
        "#   Omit for self-explanatory columns — saves tokens in system prompt.\n"
        "\n"
    )

    skipped_resources = []
    for resource_name, mapping in resources.items():
        # Check for skip_resource in overrides
        overrides = knowledge.get("resource_overrides", {}).get(resource_name, {})
        if overrides.get("skip_resource"):
            skipped_resources.append(resource_name)
            continue
        ctx = build_resource_context(resource_name, mapping, knowledge)
        output["resources"][resource_name] = ctx

    # Write output
    try:
        with open(output_path, "w") as f:
            f.write(header)
            yaml.dump(
                output,
                f,
                default_flow_style=False,
                sort_keys=False,
                allow_unicode=True,
                width=120,
            )
    except OSError as e:
        logger.exception(f"Failed to write {output_path}: {e}")
        sys.exit(1)

    # Stats
    total_fields = 0
    skipped = 0
    for res in output["resources"].values():
        for field_ctx in res.get("fields", {}).values():
            total_fields += 1
            if isinstance(field_ctx, dict) and field_ctx.get("skip"):
                skipped += 1

    logger.info(f"Generated {output_path}")
    logger.info(f"  Resources: {len(output['resources'])}")
    logger.info(f"  Fields: {total_fields} ({skipped} skipped)")
    if skipped_resources:
        logger.info(f"  Skipped resources: {', '.join(skipped_resources)}")

    # ── Validation warnings ──────────────────────────────────────
    warnings = validate(resources, knowledge, output)
    for w in warnings:
        logger.warning(f"Schema validation: {w}")


def validate(mappings_resources, knowledge, output):
    """Cross-reference mappings against api_knowledge for potential issues."""
    warnings = []
    overrides = knowledge.get("resource_overrides", {})
    timestamp_fields = set(knowledge.get("timestamp_fields", []))
    type_corrections = knowledge.get("type_corrections", {})
    global_renames = knowledge.get("global_rules", {}).get("field_renames", {})
    always_skip = set(knowledge.get("global_rules", {}).get("always_skip_fields", []))

    for resource_name, mapping in mappings_resources.items():
        # Skip resources marked as skip_resource
        res_override = overrides.get(resource_name, {})
        if res_override.get("skip_resource"):
            continue

        # Warn if resource has no description in api_knowledge
        if not res_override.get("description"):
            warnings.append(
                f"{resource_name}: no description in api_knowledge.yml"
            )

        # Check each field
        mapping_fields = mapping.get("fields", {})
        field_overrides = (res_override.get("fields") or {})

        for field_name, field_info in mapping_fields.items():
            if field_name in ("id", "uri"):
                continue

            api_type = field_info.get("api_type", "unknown")
            override = field_overrides.get(field_name, {})

            # Warn about unknown-type fields with no override
            # (skip fields handled by global rules: timestamps, renames, always_skip)
            handled_globally = (
                field_name in timestamp_fields
                or field_name in type_corrections
                or field_name in global_renames
                or field_name in always_skip
            )
            if api_type == "unknown" and not override and not handled_globally:
                warnings.append(
                    f"{resource_name}.{field_name}: api_type is unknown, "
                    f"may need override in api_knowledge.yml"
                )
            # Warn about unknown-type fields that have override but no
            # extract_key or db_type (might be an FK object)
            elif (
                api_type == "unknown"
                and override
                and "extract_key" not in override
                and "db_type" not in override
                and not override.get("skip")
            ):
                warnings.append(
                    f"{resource_name}.{field_name}: api_type is unknown, "
                    f"override exists but has no db_type or extract_key"
                )

    return warnings


if __name__ == "__main__":
    main()
