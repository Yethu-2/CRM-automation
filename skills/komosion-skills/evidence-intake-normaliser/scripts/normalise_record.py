#!/usr/bin/env python3
"""Deterministic normalisation of one inbound record into a canonical evidence record.
Input JSON: {source, source_id, thread_id?, received_at, sender:{name,email,phone}, subject, body, raw_ref?, language?}
Never guesses: unparseable values become null plus a warning.
"""
import argparse, json, re, hashlib, datetime
from email.utils import parsedate_to_datetime

FREE_MAIL = {"gmail.com", "googlemail.com", "yahoo.com", "outlook.com", "hotmail.com", "live.com",
             "icloud.com", "me.com", "proton.me", "protonmail.com", "aol.com", "qq.com", "163.com"}
EMAIL_RE = re.compile(r"^[a-z0-9._%+\-]+@[a-z0-9\-]+(\.[a-z0-9\-]+)+$")

def norm_email(e):
    e = (e or "").strip().lower()
    return e if EMAIL_RE.match(e) else None

def norm_phone(p, cc):
    if not p:
        return None
    digits = re.sub(r"\D", "", p)
    if not digits:
        return None
    s = p.strip()
    if s.startswith("+"):
        return "+" + digits
    if s.startswith("00"):
        return "+" + digits[2:]
    if digits.startswith("0") and cc:
        return "+" + cc + digits[1:]
    return None

def norm_ts(s):
    if not s:
        return None, "missing timestamp"
    try:
        d = datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        try:
            d = parsedate_to_datetime(s)
        except (TypeError, ValueError):
            return None, "unparseable timestamp"
    if d.tzinfo is None:
        return None, "timestamp has no timezone; not assumed"
    return d.astimezone(datetime.timezone.utc).isoformat(), None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--default-country-code", default="")
    a = ap.parse_args()
    r = json.load(open(a.path))
    warns = []
    sender = r.get("sender", {})
    email = norm_email(sender.get("email"))
    if sender.get("email") and not email:
        warns.append("sender email invalid")
    phone = norm_phone(sender.get("phone"), a.default_country_code)
    if sender.get("phone") and not phone:
        warns.append("sender phone could not be normalised")
    ts, w = norm_ts(r.get("received_at"))
    if w:
        warns.append(w)
    domain = email.split("@")[1] if email else None
    free = bool(domain and domain in FREE_MAIL)
    body = r.get("body") or ""
    key = f"{r.get('source','')}|{r.get('source_id','')}"
    out = {
        "evidence_id": "EV-" + hashlib.sha256(key.encode()).hexdigest()[:10],
        "source": r.get("source"), "source_id": r.get("source_id"),
        "thread_id": r.get("thread_id"), "received_at_utc": ts,
        "sender": {"name": (sender.get("name") or "").strip() or None, "email": email, "phone": phone},
        "org_domain": None if free else domain, "is_free_mail": free,
        "subject": re.sub(r"\s+", " ", r.get("subject") or "").strip(),
        "language": r.get("language"), "raw_ref": r.get("raw_ref"),
        "raw_sha256": hashlib.sha256(body.encode()).hexdigest(), "warnings": warns,
    }
    print(json.dumps(out, indent=2))

if __name__ == "__main__":
    main()
