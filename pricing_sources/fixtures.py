"""Provider fixture loading, validation, and secret redaction.

Loads provider fixture JSON files from the local fixtures directory,
validates metadata, redacts secrets, and returns payloads for tests.

This module does NOT make external calls. It only reads local files.

Design: docs/V11_3_FIXTURE_ADAPTER_HARNESS.md
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# Default fixtures root — can be overridden for testing
DEFAULT_FIXTURES_ROOT = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "pricing_sources"

# Patterns that indicate a secret/token in fixture text
_SECRET_PATTERNS = [
    re.compile(r"tcg_[A-Za-z0-9]{20,}"),          # JustTCG-style keys
    re.compile(r"pk_(live|test)_[A-Za-z0-9]{20,}"),  # PokéWallet-style keys
    re.compile(r"[A-Za-z0-9]{32,}"),               # Generic long tokens
]

# Required metadata fields
REQUIRED_METADATA_FIELDS = [
    "provider_code",
    "fixture_name",
    "permission_basis",
    "allowed_for_unit_tests",
]


@dataclass(frozen=True)
class FixtureMetadata:
    """Validated metadata for a provider fixture."""
    provider_code: str
    fixture_name: str
    source_url_or_doc: str = ""
    captured_at: str = ""
    permission_basis: str = ""
    contains_raw_provider_response: bool = False
    allowed_for_unit_tests: bool = False
    notes: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LoadedFixture:
    """A validated and redacted fixture ready for tests."""
    metadata: FixtureMetadata
    payload: Any  # dict or list
    fixture_path: Path
    redaction_count: int


class FixtureError(Exception):
    """Raised when a fixture fails validation."""
    pass


def _redact_secrets(text: str) -> tuple[str, int]:
    """Redact apparent secrets from text. Returns (redacted_text, count)."""
    count = 0
    for pattern in _SECRET_PATTERNS:
        matches = pattern.findall(text)
        count += len(matches)
        text = pattern.sub("[REDACTED]", text)
    return text, count


def _validate_metadata(metadata: dict[str, Any], provider_folder: str) -> FixtureMetadata:
    """Validate and parse fixture metadata."""
    # Check required fields
    for key in REQUIRED_METADATA_FIELDS:
        if key not in metadata:
            raise FixtureError(f"Missing required metadata field: {key}")

    provider_code = str(metadata["provider_code"]).strip()
    fixture_name = str(metadata["fixture_name"]).strip()
    permission_basis = str(metadata.get("permission_basis", "")).strip()
    allowed = bool(metadata.get("allowed_for_unit_tests", False))

    # Validate provider matches folder
    if provider_code != provider_folder:
        raise FixtureError(
            f"Provider code mismatch: metadata says '{provider_code}' "
            f"but folder is '{provider_folder}'"
        )

    # Validate non-empty permission basis
    if not permission_basis:
        raise FixtureError("permission_basis must be non-empty")

    # Validate allowed_for_unit_tests
    if not allowed:
        raise FixtureError(
            "allowed_for_unit_tests must be true for fixtures used in tests"
        )

    return FixtureMetadata(
        provider_code=provider_code,
        fixture_name=fixture_name,
        source_url_or_doc=str(metadata.get("source_url_or_doc", "")),
        captured_at=str(metadata.get("captured_at", "")),
        permission_basis=permission_basis,
        contains_raw_provider_response=bool(metadata.get("contains_raw_provider_response", False)),
        allowed_for_unit_tests=allowed,
        notes=str(metadata.get("notes", "")),
        extra={k: v for k, v in metadata.items() if k not in {
            "provider_code", "fixture_name", "source_url_or_doc", "captured_at",
            "permission_basis", "contains_raw_provider_response",
            "allowed_for_unit_tests", "notes",
        }},
    )


def load_fixture(
    fixture_path: Path,
    *,
    fixtures_root: Path | None = None,
) -> LoadedFixture:
    """Load and validate a single fixture file.

    Args:
        fixture_path: path to the fixture JSON file.
        fixtures_root: optional override for the fixtures root directory.

    Returns:
        LoadedFixture with validated metadata and redacted payload.

    Raises:
        FixtureError: if validation fails.
    """
    fixtures_root = fixtures_root or DEFAULT_FIXTURES_ROOT

    # Determine provider folder name
    provider_folder = fixture_path.parent.name

    # Read raw text
    raw_text = fixture_path.read_text(encoding="utf-8")

    # Parse JSON
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as e:
        raise FixtureError(f"Invalid JSON in {fixture_path}: {e}")

    # Separate metadata from payload
    if isinstance(data, dict) and "_metadata" in data:
        metadata_raw = data["_metadata"]
        payload = data.get("payload", data.get("response", {}))
    elif fixture_path.name == "_metadata.json":
        raise FixtureError("_metadata.json is a metadata file, not a fixture payload")
    else:
        # Look for adjacent metadata file
        meta_path = fixture_path.parent / "_metadata.json"
        if meta_path.exists():
            meta_text = meta_path.read_text(encoding="utf-8")
            try:
                metadata_raw = json.loads(meta_text)
            except json.JSONDecodeError as e:
                raise FixtureError(f"Invalid metadata JSON in {meta_path}: {e}")
        else:
            raise FixtureError(
                f"No metadata found for {fixture_path}. "
                "Include _metadata in the fixture or provide _metadata.json"
            )
        payload = data

    # Validate metadata
    if not isinstance(metadata_raw, dict):
        raise FixtureError("Metadata must be a JSON object")

    metadata = _validate_metadata(metadata_raw, provider_folder)

    # Redact secrets from payload text
    payload_text = json.dumps(payload, ensure_ascii=False)
    redacted_text, redaction_count = _redact_secrets(payload_text)

    if redaction_count > 0:
        payload = json.loads(redacted_text)

    return LoadedFixture(
        metadata=metadata,
        payload=payload,
        fixture_path=fixture_path,
        redaction_count=redaction_count,
    )


def list_fixtures(
    provider_code: str,
    *,
    fixtures_root: Path | None = None,
) -> list[Path]:
    """List fixture files for a provider (excluding metadata files)."""
    fixtures_root = fixtures_root or DEFAULT_FIXTURES_ROOT
    provider_dir = fixtures_root / provider_code
    if not provider_dir.is_dir():
        return []
    return sorted(
        p for p in provider_dir.iterdir()
        if p.is_file() and p.suffix == ".json" and p.name != "_metadata.json"
    )


def load_all_fixtures(
    provider_code: str,
    *,
    fixtures_root: Path | None = None,
) -> list[LoadedFixture]:
    """Load all validated fixtures for a provider."""
    results = []
    for path in list_fixtures(provider_code, fixtures_root=fixtures_root):
        results.append(load_fixture(path, fixtures_root=fixtures_root))
    return results
