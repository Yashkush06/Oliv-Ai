"""
File system tools — read, write, search, and manage files.
These unlock: drafting documents, editing configs, searching notes,
reading emails saved locally, managing downloads.
"""
import logging
import os
import shutil
from pathlib import Path
from typing import Optional

from tools.registry import tool

logger = logging.getLogger(__name__)


@tool(
    name="read_file",
    description="Read the contents of a text file.",
    parameters={
        "path": {"type": "string", "description": "Full path to the file"},
        "max_chars": {"type": "integer", "description": "Max characters to return (default 4000)", "default": 4000},
    },
    risk_level="safe",
)
def read_file(path: str, max_chars: int = 4000) -> dict:
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
        truncated = len(text) > max_chars
        return {
            "success": True,
            "text": text[:max_chars],
            "truncated": truncated,
            "total_chars": len(text),
            "path": path,
        }
    except FileNotFoundError:
        return {"success": False, "error": f"File not found: {path}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool(
    name="write_file",
    description="Write or overwrite a text file with given content.",
    parameters={
        "path":    {"type": "string", "description": "Full path to the file"},
        "content": {"type": "string", "description": "Text content to write"},
        "append":  {"type": "boolean", "description": "Append instead of overwrite (default false)", "default": False},
    },
    risk_level="moderate",
)
def write_file(path: str, content: str, append: bool = False) -> dict:
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if append else "w"
        p.write_text(content, encoding="utf-8") if not append else \
            p.open("a", encoding="utf-8").write(content)
        return {"success": True, "path": path, "bytes_written": len(content.encode())}
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool(
    name="list_files",
    description="List files and folders in a directory.",
    parameters={
        "path":    {"type": "string", "description": "Directory path to list"},
        "pattern": {"type": "string", "description": "Glob pattern filter e.g. '*.pdf' (default: *)", "default": "*"},
    },
    risk_level="safe",
)
def list_files(path: str, pattern: str = "*") -> dict:
    try:
        p = Path(path)
        entries = []
        for item in sorted(p.glob(pattern))[:100]:
            entries.append({
                "name": item.name,
                "type": "dir" if item.is_dir() else "file",
                "size": item.stat().st_size if item.is_file() else None,
            })
        return {"success": True, "path": path, "entries": entries, "count": len(entries)}
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool(
    name="search_files",
    description="Search for files by name or content within a directory.",
    parameters={
        "directory": {"type": "string", "description": "Root directory to search in"},
        "query":     {"type": "string", "description": "Filename keyword or text content to search for"},
        "search_content": {"type": "boolean", "description": "Also search inside file content", "default": False},
    },
    risk_level="safe",
)
def search_files(directory: str, query: str, search_content: bool = False) -> dict:
    try:
        root = Path(directory)
        query_lower = query.lower()
        matches = []

        for item in root.rglob("*"):
            if not item.is_file():
                continue
            # Filename match
            if query_lower in item.name.lower():
                matches.append({"path": str(item), "match": "filename"})
                continue
            # Content match
            if search_content and item.suffix in (".txt", ".md", ".py", ".json", ".csv", ".log"):
                try:
                    text = item.read_text(encoding="utf-8", errors="replace")
                    if query_lower in text.lower():
                        matches.append({"path": str(item), "match": "content"})
                except Exception:
                    pass
            if len(matches) >= 30:
                break

        return {"success": True, "query": query, "matches": matches, "count": len(matches)}
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool(
    name="delete_file",
    description="Delete a file or empty directory.",
    parameters={"path": {"type": "string", "description": "Full path to delete"}},
    risk_level="dangerous",
)
def delete_file(path: str) -> dict:
    try:
        p = Path(path)
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink()
        return {"success": True, "deleted": path}
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool(
    name="open_file",
    description="Open a file with its default Windows application (like double-clicking it).",
    parameters={"path": {"type": "string", "description": "Full path to the file to open"}},
    risk_level="moderate",
)
def open_file(path: str) -> dict:
    try:
        os.startfile(path)
        return {"success": True, "path": path}
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool(
    name="get_desktop_path",
    description="Get the path to the user's Desktop, Downloads, or Documents folder.",
    parameters={
        "folder": {"type": "string", "description": "'desktop', 'downloads', 'documents', 'home'"}
    },
    risk_level="safe",
)
def get_desktop_path(folder: str = "desktop") -> dict:
    home = Path.home()
    paths = {
        "desktop":   home / "Desktop",
        "downloads": home / "Downloads",
        "documents": home / "Documents",
        "home":      home,
    }
    p = paths.get(folder.lower(), home / "Desktop")
    return {"success": True, "path": str(p), "exists": p.exists()}
