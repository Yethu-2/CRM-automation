#!/usr/bin/env python3
"""Conservative person/organisation matching.
Input JSON: {"incoming": {"email","name","phone","org_name"},
             "candidates": {"persons":[{"id","name","emails":[],"phones":[],"org_id"}],
                            "organisations":[{"id","name","domains":[]}]}}
Result per side: match | possible_match | no_match, with reasons. Name-only never yields 'match'.
"""
import json, sys, re
from difflib import SequenceMatcher

FREE_MAIL = {"gmail.com", "googlemail.com", "yahoo.com", "outlook.com", "hotmail.com", "live.com",
             "icloud.com", "me.com", "proton.me", "protonmail.com", "aol.com", "qq.com", "163.com"}

def sim(a, b):
    n = lambda s: re.sub(r"[^a-z0-9 ]", "", (s or "").lower()).strip()
    a, b = n(a), n(b)
    return SequenceMatcher(None, a, b).ratio() if a and b else 0.0

def main():
    data = json.load(open(sys.argv[1]))
    inc = data["incoming"]; cands = data["candidates"]
    email = (inc.get("email") or "").lower(); phone = inc.get("phone")
    domain = email.split("@")[1] if "@" in email else None
    free = domain in FREE_MAIL if domain else False

    persons = []
    for p in cands.get("persons", []):
        reasons, level = [], None
        if email and email in [e.lower() for e in p.get("emails", [])]:
            reasons.append("exact email match"); level = "match"
        ns = sim(inc.get("name"), p.get("name"))
        if phone and phone in p.get("phones", []):
            reasons.append("exact phone match")
            level = "match" if ns >= 0.8 else (level or "possible_match")
        if level is None and ns >= 0.85:
            reasons.append(f"name similarity {ns:.2f} (name only: do not auto-link)")
            level = "possible_match"
        if level:
            persons.append({"id": p["id"], "level": level, "reasons": reasons})

    orgs = []
    for o in cands.get("organisations", []):
        reasons, level = [], None
        if domain and not free and domain in [d.lower() for d in o.get("domains", [])]:
            reasons.append(f"domain {domain} matches"); level = "match"
        ns = sim(inc.get("org_name"), o.get("name"))
        if level is None and ns >= 0.9:
            reasons.append(f"organisation name similarity {ns:.2f}"); level = "possible_match"
        if level:
            orgs.append({"id": o["id"], "level": level, "reasons": reasons})

    def overall(items):
        if any(i["level"] == "match" for i in items):
            return "match"
        return "possible_match" if items else "no_match"
    result = {"person": {"result": overall(persons), "candidates": persons},
              "organisation": {"result": overall(orgs), "candidates": orgs,
                               "note": "free-mail domain ignored" if free else ""}}
    result["creation"] = ("propose_create_for: " + ", ".join(k for k in ("person", "organisation")
                          if result[k]["result"] == "no_match")) \
        if any(result[k]["result"] == "no_match" for k in ("person", "organisation")) else "none"
    result["needs_human_review"] = any(result[k]["result"] == "possible_match" for k in ("person", "organisation"))
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()
