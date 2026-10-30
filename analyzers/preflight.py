"""Deterministic, source-only preflight checks for C submissions."""

import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RULES_PATH = PROJECT_ROOT / "rules" / "preflight.json"


def load_rules(path: str | Path = DEFAULT_RULES_PATH) -> dict[str, Any]:
    """Load and validate the source limits from preflight configuration."""
    rules_path = Path(path)

    with rules_path.open("r", encoding="utf-8") as handle:
        rules = json.load(handle)

    source_limits = rules.get("source_limits")
    if not isinstance(source_limits, dict):
        raise ValueError("Missing or invalid rules section: source_limits")

    value = source_limits.get("max_source_bytes")
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError("Invalid source limit: max_source_bytes")

    return rules


def preflight(
    source: str,
    rules_path: str | Path = DEFAULT_RULES_PATH,
) -> dict[str, Any]:
    """Validate submitted source without compiling or executing it."""
    rules = load_rules(rules_path)

    if not isinstance(source, str) or not source.strip():
        return {
            "decision": "reject",
            "stage": "source_validation",
            "status": "invalid_request",
            "reasons": ["C source must be a non-empty string."],
            "source_bytes": 0,
        }

    source_bytes = len(source.encode("utf-8"))
    max_source_bytes = rules["source_limits"]["max_source_bytes"]

    if source_bytes > max_source_bytes:
        return {
            "decision": "reject",
            "stage": "source_validation",
            "status": "source_too_large",
            "reasons": ["Source exceeds the configured byte limit."],
            "source_bytes": source_bytes,
        }

    return {
        "decision": "continue",
        "stage": "source_validation",
        "status": "source_validated",
        "reasons": [],
        "source_bytes": source_bytes,
    }
