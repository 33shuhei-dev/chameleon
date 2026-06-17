"""
schema_manager.py - JSON schema lifecycle manager
Enforces:
  - Immutability: ARTIFACT types cannot be overwritten (append-only)
  - Validation: all reads/writes checked against json_registry schemas
  - Integrity: cross-schema constraints via check_integrity()
  - Registry status: real-time health of all registered JSON files
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from json_registry import JSON_REGISTRY, JsonCategory, get_schema

logger = logging.getLogger(__name__)


class SchemaManager:
    def __init__(self):
        self._violation_count = 0
        self._violations: list[dict] = []

    # ── Validation ────────────────────────────────────────────────────────────

    def validate(self, json_type: str, data: dict) -> tuple[bool, list[str]]:
        """Validate data against the registered schema. Returns (valid, errors)."""
        schema = get_schema(json_type)
        if not schema:
            return True, []

        errors: list[str] = []

        # Required fields
        for f in schema.required_fields:
            if f == "schema_version":
                continue
            if f not in data:
                errors.append(f"Missing required field: '{f}'")

        # Type checks
        for f, expected in schema.field_types.items():
            if f in data and data[f] is not None:
                if not isinstance(data[f], expected):
                    errors.append(
                        f"Field '{f}': expected {expected.__name__}, "
                        f"got {type(data[f]).__name__}"
                    )

        # Constraint checks
        for f, constraints in schema.field_constraints.items():
            if f not in data or data[f] is None:
                continue
            val = data[f]

            if "min" in constraints and isinstance(val, (int, float)):
                if val < constraints["min"]:
                    errors.append(f"Field '{f}': {val} < min {constraints['min']}")

            if "max" in constraints and isinstance(val, (int, float)):
                if val > constraints["max"]:
                    errors.append(f"Field '{f}': {val} > max {constraints['max']}")

            if "min_length" in constraints and isinstance(val, str):
                if len(val) < constraints["min_length"]:
                    errors.append(
                        f"Field '{f}': length {len(val)} < min_length {constraints['min_length']}"
                    )

            if "enum" in constraints and val not in constraints["enum"]:
                errors.append(
                    f"Field '{f}': '{val}' not in {constraints['enum']}"
                )

        if errors:
            self._violation_count += 1
            self._violations.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "json_type": json_type,
                "errors":    errors,
            })
            for err in errors:
                logger.warning("[SchemaManager] %s validation: %s", json_type, err)

        return len(errors) == 0, errors

    # ── Read ──────────────────────────────────────────────────────────────────

    def read_json(self, json_type: str, path: Path) -> dict | None:
        """Read a JSON file and validate against schema."""
        if not path.exists():
            return None
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            valid, errors = self.validate(json_type, data)
            if not valid:
                logger.warning(
                    "[SchemaManager] read_json %s: %d validation errors", json_type, len(errors)
                )
            return data
        except Exception as exc:
            logger.error("[SchemaManager] read_json(%s, %s) failed: %s", json_type, path, exc)
            return None

    # ── Write ─────────────────────────────────────────────────────────────────

    def write_json(self, json_type: str, path: Path, data: dict, indent: int = 2) -> bool:
        """Write a JSON file. ARTIFACT types are rejected (use append_jsonl instead)."""
        schema = get_schema(json_type)
        if schema and schema.category == JsonCategory.ARTIFACT:
            logger.error(
                "[SchemaManager] Cannot overwrite ARTIFACT %s at %s — use append_jsonl()",
                json_type, path,
            )
            return False

        valid, _ = self.validate(json_type, data)
        if not valid:
            logger.warning(
                "[SchemaManager] write_json %s: writing with validation errors", json_type
            )

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=indent, ensure_ascii=False)
            return True
        except Exception as exc:
            logger.error("[SchemaManager] write_json(%s, %s) failed: %s", json_type, path, exc)
            return False

    def append_jsonl(self, json_type: str, path: Path, record: dict) -> bool:
        """Append a record to a JSONL file — the safe ARTIFACT write operation."""
        valid, _ = self.validate(json_type, record)
        if not valid:
            logger.warning(
                "[SchemaManager] append_jsonl %s: writing with validation errors", json_type
            )

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            return True
        except Exception as exc:
            logger.error("[SchemaManager] append_jsonl(%s, %s) failed: %s", json_type, path, exc)
            return False

    # ── Integrity ─────────────────────────────────────────────────────────────

    def check_integrity(self, universe_data: dict | None = None) -> list[dict]:
        """Run integrity constraints. Returns list of violations."""
        violations: list[dict] = []

        if universe_data:
            wl  = set(universe_data.get("watchlist", {}).keys())
            bl  = set(universe_data.get("blacklist", []))
            overlap = wl & bl
            if overlap:
                violations.append({
                    "constraint": "IC-001",
                    "severity":   "ERROR",
                    "detail":     f"Tokens in both watchlist and blacklist: {overlap}",
                })

        return violations

    # ── Status ────────────────────────────────────────────────────────────────

    def get_registry_status(self) -> dict:
        """Return current health of all registered JSON files."""
        status: dict[str, dict] = {}
        for json_type, schema in JSON_REGISTRY.items():
            p_str = schema.path_pattern
            if "(in-memory" in p_str:
                exists = size = None
            else:
                p      = Path(p_str)
                exists = p.exists()
                size   = p.stat().st_size if exists else 0

            status[json_type] = {
                "category":    schema.category.value,
                "version":     schema.version,
                "path":        p_str,
                "exists":      exists,
                "size_bytes":  size,
                "description": schema.description,
                "immutable":   schema.category == JsonCategory.ARTIFACT,
            }
        return status

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def violation_count(self) -> int:
        return self._violation_count

    @property
    def violations(self) -> list[dict]:
        return list(self._violations)


# Module-level singleton so all callers share the same violation counter
_manager = SchemaManager()


def get_manager() -> SchemaManager:
    return _manager
