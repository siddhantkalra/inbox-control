from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ENGINE_DIR = Path(__file__).resolve().parent
STATE_DIR = ENGINE_DIR / ".state"
RUNS_PATH = STATE_DIR / "suppress_runs.jsonl"


@dataclass
class SuppressRun:
    ts_utc: str
    target: str
    mode: str
    label_name: str
    label_id: str
    filter_id: str
    filter_query: str
    message_ids: List[str]

    @staticmethod
    def now_ts() -> str:
        return datetime.now(timezone.utc).isoformat()

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "SuppressRun":
        return SuppressRun(
            ts_utc=d["ts_utc"],
            target=d["target"],
            mode=d["mode"],
            label_name=d["label_name"],
            label_id=d["label_id"],
            filter_id=d["filter_id"],
            filter_query=d.get("filter_query", ""),
            message_ids=list(d.get("message_ids", [])),
        )


def ensure_state_dir() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)


def append_run(run: SuppressRun) -> None:
    ensure_state_dir()
    with open(RUNS_PATH, "a", encoding="utf-8") as f:
        f.write(run.to_json() + "\n")


def load_runs() -> List[SuppressRun]:
    if not RUNS_PATH.exists():
        return []
    runs: List[SuppressRun] = []
    with open(RUNS_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            runs.append(SuppressRun.from_dict(json.loads(line)))
    return runs


def latest_run_for_target(target: str) -> Optional[SuppressRun]:
    t = target.strip().lower()
    runs = [r for r in load_runs() if r.target.lower() == t]
    if not runs:
        return None
    return runs[-1]