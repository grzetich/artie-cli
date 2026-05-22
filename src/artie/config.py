"""Per-project configuration loaded from a .artie.toml file.

A .artie.toml lets a repo pin artie's behavior — per-check pass/fail
thresholds, checks to exclude from the gate, and default CLI flags — so CI
runs are reproducible without a long command line. Command-line flags always
override the config file.

Schema (every section is optional):

    # .artie.toml
    ignore = ["Schema Complexity"]      # checks excluded from the fail gate

    [defaults]                          # default CLI flags
    with_generation = false
    differential = false
    model = "claude-sonnet-4-6"
    fail_under = 7                      # global gate threshold

    [thresholds]                        # per-check gate thresholds (0-10)
    "Format Efficiency" = 9
    "Endpoint Completeness" = 7

See docs/scoring.md for what the thresholds mean.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on Python 3.10
    import tomli as tomllib

CONFIG_FILENAME = ".artie.toml"

# Canonical check names, used to flag typos in a config file. Kept as a
# literal list rather than imported from artie.checks so loading config
# never drags in tiktoken and the rest of the check machinery.
KNOWN_CHECK_NAMES = frozenset(
    {
        "Format Efficiency",
        "Endpoint Completeness",
        "Example Coverage",
        "Error Documentation",
        "Auth Clarity",
        "Parameter Naming",
        "Schema Complexity",
        "Sample Generation",
    }
)


class ConfigError(Exception):
    """Raised when a .artie.toml file is present but cannot be used."""


@dataclass
class ArtieConfig:
    """Resolved configuration. All fields have safe defaults when no file exists."""

    thresholds: dict[str, int] = field(default_factory=dict)
    ignore: list[str] = field(default_factory=list)
    fail_under: int | None = None
    with_generation: bool = False
    differential: bool = False
    model: str | None = None
    source_path: Path | None = None
    # Non-fatal problems (unknown check names, etc.) for the CLI to surface.
    warnings: list[str] = field(default_factory=list)

    def threshold_for(self, check_name: str) -> int | None:
        """Return the gate threshold for a check: per-check, else global."""
        return self.thresholds.get(check_name, self.fail_under)


def find_config(start: Path | None = None) -> Path | None:
    """Walk up from `start` (default: cwd) looking for a .artie.toml file."""
    directory = (start or Path.cwd()).resolve()
    for candidate_dir in (directory, *directory.parents):
        candidate = candidate_dir / CONFIG_FILENAME
        if candidate.is_file():
            return candidate
    return None


def load_config(
    explicit: Path | None = None, start: Path | None = None
) -> ArtieConfig:
    """Load configuration.

    If `explicit` is given, that exact file is loaded (and missing is an
    error). Otherwise a .artie.toml is searched for from `start` upward; if
    none is found, a default ArtieConfig is returned.
    """
    if explicit is not None:
        path = Path(explicit)
        if not path.is_file():
            raise ConfigError(f"Config file not found: {path}")
    else:
        found = find_config(start)
        if found is None:
            return ArtieConfig()
        path = found

    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Invalid TOML in {path}: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"Could not read {path}: {exc}") from exc

    return _parse(raw, path)


def _parse(raw: dict[str, Any], path: Path) -> ArtieConfig:
    """Turn a parsed TOML mapping into an ArtieConfig, validating as we go."""
    config = ArtieConfig(source_path=path)

    ignore = raw.get("ignore", [])
    if not isinstance(ignore, list) or not all(isinstance(x, str) for x in ignore):
        raise ConfigError(f"{path}: `ignore` must be a list of check names.")
    config.ignore = ignore

    thresholds = raw.get("thresholds", {})
    if not isinstance(thresholds, dict):
        raise ConfigError(f"{path}: `[thresholds]` must be a table.")
    for name, value in thresholds.items():
        if not isinstance(value, int) or isinstance(value, bool):
            raise ConfigError(
                f"{path}: threshold for '{name}' must be an integer 0-10."
            )
        if not 0 <= value <= 10:
            raise ConfigError(
                f"{path}: threshold for '{name}' is {value}; must be 0-10."
            )
    config.thresholds = dict(thresholds)

    defaults = raw.get("defaults", {})
    if not isinstance(defaults, dict):
        raise ConfigError(f"{path}: `[defaults]` must be a table.")

    config.with_generation = _bool(defaults, "with_generation", path)
    config.differential = _bool(defaults, "differential", path)

    model = defaults.get("model")
    if model is not None and not isinstance(model, str):
        raise ConfigError(f"{path}: `defaults.model` must be a string.")
    config.model = model

    fail_under = defaults.get("fail_under")
    if fail_under is not None:
        if not isinstance(fail_under, int) or isinstance(fail_under, bool):
            raise ConfigError(f"{path}: `defaults.fail_under` must be an integer.")
        if not 0 <= fail_under <= 10:
            raise ConfigError(
                f"{path}: `defaults.fail_under` is {fail_under}; must be 0-10."
            )
    config.fail_under = fail_under

    # Non-fatal: flag check names that don't match any real check, so a typo
    # like "Format Efficency" doesn't silently disable a threshold.
    for name in (*config.thresholds, *config.ignore):
        if name not in KNOWN_CHECK_NAMES:
            config.warnings.append(
                f"{path}: '{name}' is not a known check name and will be "
                f"ignored. Known checks: {', '.join(sorted(KNOWN_CHECK_NAMES))}."
            )

    return config


def _bool(table: dict[str, Any], key: str, path: Path) -> bool:
    value = table.get(key, False)
    if not isinstance(value, bool):
        raise ConfigError(f"{path}: `defaults.{key}` must be true or false.")
    return value
