from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class RunStore:
    def __init__(self, review_id: str, output_dir: Path) -> None:
        self.run_dir: Path = output_dir / review_id
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self._fh = (self.run_dir / "events.jsonl").open("a", encoding="utf-8")
        self._lock = threading.Lock()

    def emit(self, event_type: str, payload: dict) -> None:
        try:
            record = {"ts": datetime.now(timezone.utc).isoformat(), "type": event_type, **payload}
            line = json.dumps(record) + "\n"
            with self._lock:
                self._fh.write(line)
                self._fh.flush()
        except Exception as exc:  # noqa: BLE001
            logging.warning("RunStore.emit failed: %s", exc)

    def write_parquet(self, name: str, rows: list[dict]) -> None:
        dest = self.run_dir / f"{name}.parquet"
        try:
            import pandas as pd  # type: ignore[import]
            pd.DataFrame(rows).to_parquet(dest, index=False)
        except ImportError:
            logging.warning("pandas/pyarrow not available; writing %s as JSON", dest)
            (self.run_dir / f"{name}.json").write_text(
                json.dumps(rows, indent=2), encoding="utf-8"
            )
        except Exception as exc:  # noqa: BLE001
            logging.warning("RunStore.write_parquet failed for %s: %s", name, exc)

    def write_run_stats(self, stats: dict) -> None:
        (self.run_dir / "run_stats.json").write_text(
            json.dumps(stats, indent=2), encoding="utf-8"
        )

    def close(self) -> None:
        self._fh.close()
