from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from jsonschema import Draft7Validator, FormatChecker


class SchemaValidationError(ValueError):
    pass


def _format_error_path(path: Iterable[object]) -> str:
    parts = [str(part) for part in path]
    return ".".join(parts) if parts else "<root>"


class JsonSchemaValidator:
    def __init__(self, schema_path: Path) -> None:
        self._schema_path = schema_path
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self._validator = Draft7Validator(schema, format_checker=FormatChecker())

    def validate(self, payload: dict) -> None:
        errors = sorted(self._validator.iter_errors(payload), key=lambda e: e.path)
        if errors:
            formatted = [
                f"{_format_error_path(error.path)}: {error.message}"
                for error in errors[:5]
            ]
            joined = "; ".join(formatted)
            raise SchemaValidationError(
                f"Schema validation failed for {self._schema_path}: {joined}"
            )
