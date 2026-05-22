"""Load a previously saved JSON report for run-over-run comparison.

`artie check --output json > previous.json` produces a report; passing it
back via `--baseline previous.json` on a later run lets the reporters show
per-check score deltas, which is what turns artie into a regression gate.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class BaselineError(Exception):
    """Raised when a baseline report cannot be loaded or understood."""


@dataclass
class Baseline:
    """Scores from a prior run, keyed by check name."""

    scores: dict[str, int | None] = field(default_factory=dict)
    scoring_version: str | None = None
    source: str | None = None
    path: Path | None = None

    def score_for(self, check_name: str) -> int | None:
        """Prior score for a check, or None if absent or unscored."""
        return self.scores.get(check_name)

    def delta_for(self, check_name: str, current: int | None) -> int | None:
        """Signed change from the prior run, or None if not comparable."""
        prior = self.scores.get(check_name)
        if prior is None or current is None:
            return None
        return current - prior


def load_baseline(path: str | Path) -> Baseline:
    """Load a saved artie JSON report as a Baseline."""
    path = Path(path)
    if not path.is_file():
        raise BaselineError(f"Baseline file not found: {path}")

    try:
        data: Any = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BaselineError(f"Baseline {path} is not valid JSON: {exc}") from exc
    except OSError as exc:
        raise BaselineError(f"Could not read baseline {path}: {exc}") from exc

    if not isinstance(data, dict) or not isinstance(data.get("checks"), list):
        raise BaselineError(
            f"Baseline {path} is not an artie JSON report "
            f"(expected a top-level `checks` array)."
        )

    scores: dict[str, int | None] = {}
    for check in data["checks"]:
        if isinstance(check, dict) and isinstance(check.get("name"), str):
            score = check.get("score")
            scores[check["name"]] = score if isinstance(score, int) else None

    return Baseline(
        scores=scores,
        scoring_version=data.get("scoring_version"),
        source=data.get("source"),
        path=path,
    )
