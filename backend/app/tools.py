"""The tools DeepSeek can call: load_skill plus read-only Pipedrive lookups. No tool can write anywhere."""
from __future__ import annotations

import json
from typing import Any

from . import config, skills
from .pipedrive import ENTITIES, Pipedrive

_ENTITY = {"type": "string", "enum": list(ENTITIES)}
_ID = {"type": "integer"}

SCHEMAS = [
    {"type": "function", "function": {
        "name": "load_skill",
        "description": "Load the full instructions of a Komosion skill from the catalog in the system prompt, or one of its "
                       "reference files. Load a skill before doing the kind of work it describes.",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string", "description": "Skill name exactly as in the catalog"},
            "reference": {"type": "string", "description": "Optional reference file name listed for that skill"}},
            "required": ["name"]}}},
    {"type": "function", "function": {
        "name": "pipedrive_search",
        "description": "Search Pipedrive deals, persons or organizations by name, email or other text. Read-only.",
        "parameters": {"type": "object", "properties": {
            "entity": _ENTITY, "term": {"type": "string", "description": "At least 2 characters"},
            "limit": {"type": "integer", "description": "1-50, default 10"}}, "required": ["entity", "term"]}}},
    {"type": "function", "function": {
        "name": "pipedrive_get",
        "description": "Get one Pipedrive deal, person or organization by ID, with all its fields. Read-only.",
        "parameters": {"type": "object", "properties": {"entity": _ENTITY, "id": _ID}, "required": ["entity", "id"]}}},
    {"type": "function", "function": {
        "name": "pipedrive_activities",
        "description": "List activities (calls, meetings, tasks) for a deal, person or organization. Read-only.",
        "parameters": {"type": "object", "properties": {"deal_id": _ID, "person_id": _ID, "org_id": _ID}}}},
    {"type": "function", "function": {
        "name": "pipedrive_notes",
        "description": "List notes attached to a deal, person or organization. Read-only.",
        "parameters": {"type": "object", "properties": {"deal_id": _ID, "person_id": _ID, "org_id": _ID}}}},
]


class Toolbox:
    def __init__(self, skill_set: dict[str, skills.Skill], pipedrive: Pipedrive):
        self.skills = skill_set
        self.pipedrive = pipedrive

    def schemas(self) -> list[dict]:
        return SCHEMAS if self.pipedrive.configured else SCHEMAS[:1]

    async def call(self, name: str, raw_args: str) -> tuple[str, bool]:
        """Returns (result text for the model, ok). Errors come back as text so the model can recover."""
        try:
            args: dict[str, Any] = json.loads(raw_args or "{}")
            if not isinstance(args, dict):
                raise ValueError("arguments must be a JSON object")
            result = await self._dispatch(name, args)
            text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, separators=(",", ":"))
            if len(text) > config.TOOL_RESULT_CHARS:
                text = text[: config.TOOL_RESULT_CHARS] + f"\n…[truncated at {config.TOOL_RESULT_CHARS} characters]"
            return text, True
        except Exception as e:  # noqa: BLE001 - every failure becomes a tool error the model can see
            return json.dumps({"error": f"{type(e).__name__}: {e}"}), False

    async def _dispatch(self, name: str, a: dict[str, Any]) -> Any:
        if name == "load_skill":
            return skills.load(self.skills, a["name"], a.get("reference"))
        if name == "pipedrive_search":
            if len(str(a.get("term", "")).strip()) < 2:
                raise ValueError("term must be at least 2 characters")
            return await self.pipedrive.search(a["entity"], a["term"], int(a.get("limit", 10)))
        if name == "pipedrive_get":
            return await self.pipedrive.get_one(a["entity"], a["id"])
        if name in ("pipedrive_activities", "pipedrive_notes"):
            ids = {k: a.get(k) for k in ("deal_id", "person_id", "org_id")}
            if not any(ids.values()):
                raise ValueError("give one of deal_id, person_id or org_id")
            fn = self.pipedrive.activities if name == "pipedrive_activities" else self.pipedrive.notes
            return await fn(**ids)
        raise ValueError(f"unknown tool {name!r}")
