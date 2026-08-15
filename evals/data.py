"""Golden-dataset loading.

Datasets are JSONL: one JSON object per line. Blank lines and `//` comment
lines are ignored so the files stay easy to annotate by hand.
"""

import json
from pathlib import Path

DATASETS_DIR = Path(__file__).resolve().parent / "datasets"


def load_jsonl(name: str | Path) -> list[dict]:
    """Load a golden set by file name (resolved under `datasets/`) or path."""
    path = name if isinstance(name, Path) else DATASETS_DIR / name
    records: list[dict] = []
    with open(path, encoding="utf-8") as handle:
        for line_no, raw in enumerate(handle, start=1):
            line = raw.strip()
            if not line or line.startswith("//"):
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSON: {exc}") from exc
    return records
