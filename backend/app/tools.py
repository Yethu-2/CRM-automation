"""The tools DeepSeek can call: load_skill, plus the user's read-only Pipedrive MCP tools when they've connected."""
from __future__ import annotations

import json
from typing import Any

from . import config, skills
from .pipedrive_mcp import PipedriveMCP

LOAD_SKILL = {"type": "function", "function": {
    "name": "load_skill",
    "description": "Load the full instructions of a Komosion skill from the catalog in the system prompt, or one of its "
                   "reference files. Load a skill before doing the kind of work it describes.",
    "parameters": {"type": "object", "properties": {
        "name": {"type": "string", "description": "Skill name exactly as in the catalog"},
        "reference": {"type": "string", "description": "Optional reference file name listed for that skill"}},
        "required": ["name"]}}}


class Toolbox:
    def __init__(self, skill_set: dict[str, skills.Skill], pipedrive: PipedriveMCP | None = None):
        self.skills = skill_set
        self.pipedrive = pipedrive

    def schemas(self) -> list[dict]:
        return [LOAD_SKILL, *(self.pipedrive.schemas() if self.pipedrive else [])]

    async def call(self, name: str, raw_args: str) -> tuple[str, bool]:
        """Returns (result text for the model, ok). Errors come back as text so the model can recover."""
        try:
            args: dict[str, Any] = json.loads(raw_args or "{}")
            if not isinstance(args, dict):
                raise ValueError("arguments must be a JSON object")
            if name == "load_skill":
                text, ok = skills.load(self.skills, args["name"], args.get("reference")), True
            elif self.pipedrive and self.pipedrive.handles(name):
                text, ok = await self.pipedrive.call(name, args)
            else:
                raise ValueError(f"unknown tool {name!r}")
        except Exception as e:  # noqa: BLE001 - every failure becomes a tool error the model can see
            return json.dumps({"error": f"{type(e).__name__}: {e}"}), False
        if len(text) > config.TOOL_RESULT_CHARS:
            text = text[: config.TOOL_RESULT_CHARS] + f"\n…[truncated at {config.TOOL_RESULT_CHARS} characters]"
        return text, ok
