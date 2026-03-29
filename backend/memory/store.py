"""Memory store — persists task history, habits, and user corrections."""
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _get_memory_path() -> Path:
    base = Path(os.environ.get("OLIV_CONFIG_DIR", Path.home() / ".oliv-ai"))
    base.mkdir(parents=True, exist_ok=True)
    return base / "memory.json"


def _load() -> list[dict]:
    path = _get_memory_path()
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(entries: list[dict]):
    path = _get_memory_path()
    path.write_text(json.dumps(entries, indent=2), encoding="utf-8")


def add_memory(entry: dict) -> None:
    """Append a memory entry with a timestamp."""
    entries = _load()
    entry["saved_at"] = datetime.now(timezone.utc).isoformat()
    entries.append(entry)
    # Keep last 500 entries
    if len(entries) > 500:
        entries = entries[-500:]
    _save(entries)
    logger.debug(f"Memory saved: {entry.get('type', 'unknown')}")


def get_recent(n: int = 10, memory_type: Optional[str] = None) -> list[dict]:
    """Return the N most recent entries, optionally filtered by type."""
    entries = _load()
    if memory_type:
        entries = [e for e in entries if e.get("type") == memory_type]
    return entries[-n:]


def search_memories(query: str, memory_type: Optional[str] = None) -> list[dict]:
    """Simple keyword search across memory entries."""
    entries = _load()
    query_lower = query.lower()
    results = []
    for e in entries:
        if memory_type and e.get("type") != memory_type:
            continue
        if query_lower in json.dumps(e).lower():
            results.append(e)
    return results[-20:]


def get_all() -> list[dict]:
    return _load()


def update_memory_feedback(task_id: str, feedback: str) -> bool:
    """
    Attach a feedback signal ('thumbs_up' | 'thumbs_down') to a stored task
    so the planner can use successful tasks as few-shot examples.

    Returns True if the entry was found and updated, False otherwise.
    """
    entries = _load()
    updated = False
    for entry in entries:
        if entry.get("task_id") == task_id and entry.get("type") == "task":
            entry["feedback"] = feedback
            updated = True
            break
    if updated:
        _save(entries)
        logger.debug(f"Memory feedback '{feedback}' applied to task {task_id}")
    return updated


def clear_memory() -> None:
    _save([])
    logger.info("Memory cleared.")
