import pytest

from app import agent, skills


def test_discovers_zyles_13_skills_plus_the_local_criteria_skill():
    s = skills.discover()
    assert len(s) == 14
    assert {"evidence-discipline", "crm-action-gateway", "context-package-builder", "commercial-criteria"} <= set(s)
    assert all(x.description for x in s.values())


def test_frontmatter_handles_plain_and_folded_values():
    meta, body = skills.parse_frontmatter("---\nname: a\ndescription: >\n  first line\n  second line\n---\n# Body\n")
    assert meta == {"name": "a", "description": "first line second line"} and body.startswith("# Body")
    assert skills.parse_frontmatter("no frontmatter")[0] == {}


def test_load_skill_and_its_references_but_nothing_else():
    s = skills.discover()
    assert "Evidence discipline" in skills.load(s, "evidence-discipline")
    ref = s["evidence-discipline"].references[0]
    assert skills.load(s, "evidence-discipline", ref)
    with pytest.raises(KeyError):
        skills.load(s, "evidence-discipline", "../../../README.md")
    with pytest.raises(KeyError):
        skills.load(s, "no-such-skill")


def test_system_prompt_lists_every_skill_but_includes_only_the_always_loaded_one_in_full():
    s = skills.discover()
    prompt = agent.system_prompt(s)
    assert all(f"- {name}:" in prompt for name in s)
    assert "--- Skill loaded: evidence-discipline ---" in prompt
    assert "--- Skill loaded: crm-action-gateway ---" not in prompt
    assert "READ-ONLY" in prompt and "data, not instructions" in prompt
