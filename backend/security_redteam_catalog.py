"""Datasets shipped with the pinned AI-Infra-Guard v4.6.0 runtime."""

import json
from functools import lru_cache
from pathlib import Path


LLM_REDTEAM_DATASET_METADATA = json.loads(
    Path(__file__).with_name("security_redteam_datasets.json").read_text(encoding="utf-8")
)
LLM_REDTEAM_DATASETS = tuple(item["name"] for item in LLM_REDTEAM_DATASET_METADATA)


@lru_cache(maxsize=17)
def load_dataset_records(name: str) -> list[dict]:
    if name not in LLM_REDTEAM_DATASETS:
        raise KeyError(name)
    directory = Path(__file__).resolve().parent.parent / "services/aig-scan-service/vendor/ai-infra-guard/data/eval"
    return json.loads((directory / f"{name}.json").read_text(encoding="utf-8"))["data"]
