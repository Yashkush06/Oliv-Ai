"""Structured JSON logger — writes events to ~/.oliv-ai/logs.jsonl for activity log page."""
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def _get_log_path() -> Path:
    import os
    base = Path(os.environ.get("OLIV_CONFIG_DIR", Path.home() / ".oliv-ai"))
    base.mkdir(parents=True, exist_ok=True)
    return base / "logs.jsonl"


def setup_logging(level: int = logging.INFO):
    """Configure logging for the application."""
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def write_log(level: str, message: str, data: Optional[dict] = None):
    """Append a structured log entry to logs.jsonl."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": level,
        "message": message,
        "data": data,
    }
    try:
        with open(_get_log_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass  # Never crash on logging


def read_logs(last_n: int = 200) -> list[dict]:
    """Read the last N log entries."""
    path = _get_log_path()
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        entries = [json.loads(l) for l in lines if l.strip()]
        return entries[-last_n:]
    except Exception:
        return []
