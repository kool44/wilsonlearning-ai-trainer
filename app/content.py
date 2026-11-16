"""Loads module content packs from CONTENT_DIR. One JSON file = one module."""
import json
from pathlib import Path

from .config import CONTENT_DIR

_modules: dict[str, dict] = {}


def load_all() -> dict[str, dict]:
    _modules.clear()
    for path in sorted(Path(CONTENT_DIR).glob("*.json")):
        if path.name == "schema.json":
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        _validate(data, path)
        _modules[data["id"]] = data
    return _modules


def _validate(data: dict, path: Path) -> None:
    for key in ("id", "title", "steps"):
        if key not in data:
            raise ValueError(f"{path.name}: missing '{key}'")
    for step in data["steps"]:
        for key in ("id", "type", "title"):
            if key not in step:
                raise ValueError(f"{path.name}: step missing '{key}': {step}")
        if step["type"] not in ("teach", "apply", "roleplay", "reflect"):
            raise ValueError(f"{path.name}: unknown step type {step['type']}")
        if step["type"] == "roleplay":
            if not (step.get("personas") or step.get("persona")) or "rubric" not in step:
                raise ValueError(f"{path.name}: roleplay step {step['id']} needs 'personas' and 'rubric'")
            continue
        acts = step.get("activities") or []
        if not acts:
            raise ValueError(f"{path.name}: step {step['id']} needs at least one activity")
        for a in acts:
            t = a.get("type")
            if t == "choice" and not (a.get("options") and 0 <= a.get("answer", 0) < len(a["options"])):
                raise ValueError(f"{path.name}: bad choice activity in {step['id']}: {a.get('prompt')}")
            if t == "order" and len(a.get("items", [])) < 2:
                raise ValueError(f"{path.name}: order activity in {step['id']} needs 2+ items")
            if t == "open" and not a.get("rubric"):
                raise ValueError(f"{path.name}: open activity in {step['id']} needs a rubric")
            if t not in ("choice", "order", "open"):
                raise ValueError(f"{path.name}: unknown activity type {t} in {step['id']}")


def get(module_id: str) -> dict:
    if not _modules:
        load_all()
    return _modules[module_id]


def list_modules() -> list[dict]:
    if not _modules:
        load_all()
    return [
        {
            "id": m["id"],
            "course": m.get("course", ""),
            "title": m["title"],
            "short_title": m.get("short_title", m["title"]),
            "steps": len(m["steps"]),
        }
        for m in _modules.values()
    ]
