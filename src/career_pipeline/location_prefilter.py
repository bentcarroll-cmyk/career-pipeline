"""Conservative, explicitly approved geographic intake filtering.

Raw board inventory remains intact. A result is an auditable exclusion, never an
eligibility assertion. Missing or contradictory data always stays for review.
"""
from __future__ import annotations

import hashlib
import json
import re

from .criteria import DiscoveryLocationScope, validate_location_scope

MATCHER_VERSION = 2

def _normalize(value: str) -> str:
    # D.C. and DC are the same label; punctuation otherwise separates tokens.
    value = re.sub(r"\b([A-Za-z])\.([A-Za-z])\b\.?", r"\1\2", value)
    return " ".join(re.sub(r"[^\w]+", " ", value.casefold()).split())


def _contains(text: str, label: str) -> bool:
    return f" {_normalize(label)} " in f" {_normalize(text)} "


def _only_broad_labels(value: str, broad: set[str]) -> bool:
    """Match complete combinations of approved labels, preserving city words."""
    words = _normalize(value).split()
    labels = [label.split() for label in broad if label]
    ends = {0}
    for start in range(len(words)):
        if start not in ends:
            continue
        # A conjunction only joins two approved labels; it must not erase an
        # unexplained city word on either side or stand alone at the end.
        starts = (start, start + 1) if start and words[start] in {"and", "or"} else (start,)
        for offset in starts:
            for label in labels:
                if words[offset:offset + len(label)] == label:
                    ends.add(offset + len(label))
    return bool(words) and len(words) in ends


_REMOTE = re.compile(r"\bremote(?:ly)?\b|\bwork(?:ing)? from home\b|\bhome[- ]based\b|"
                     r"\bwork(?:ing)? from anywhere\b|\bwfh\b|"
                     r"\bdistributed (?:team|workforce|company)\b|\btelecommut\w*", re.I)
_UNKNOWN = re.compile(r"\bunknown\b|\bunspecified\b|\btbd\b|\btba\b|\bvarious\b|"
                      r"\bmultiple\b|\bto be determined\b|\banywhere\b|\bflexible\b|"
                      r"\bnegotiable\b|\bnation(?:al|wide)\b|\bnot (?:stated|specified|available)\b|^n[ /]?a$|^other$", re.I)
_OMISSION = re.compile(r"\[(?:CONTENT_FILTERED|TRUNCATED|REDACTED)\]|content (?:omitted|truncated)", re.I)


def _locations(record: dict) -> list[str] | None:
    raw = record.get("raw")
    if not isinstance(raw, dict):
        return None
    values = [record.get("location")]
    # Consider every documented alternative, not merely the displayed first one.
    for key in ("secondaryLocations", "offices"):
        items = raw.get(key)
        if items is None:
            items = []
        if not isinstance(items, list):
            return None
        for item in items:
            if not isinstance(item, dict):
                return None
            values.append(item.get("location") or item.get("name"))
    categories = raw.get("categories")
    if categories is None:
        categories = {}
    if not isinstance(categories, dict):
        return None
    alternatives = categories.get("allLocations")
    if alternatives is None:
        alternatives = []
    if not isinstance(alternatives, list):
        return None
    values.extend(alternatives)
    if categories.get("location"):
        values.append(categories["location"])
    location = raw.get("location")
    if isinstance(location, dict):
        values.append(location.get("name"))
    elif location:
        values.append(location)
    if any(not isinstance(v, str) or not v.strip() for v in values):
        return None
    return list(dict.fromkeys(v.strip() for v in values))


def exclusion_decision(record: dict, scope: DiscoveryLocationScope) -> dict | None:
    """Assess all published location options and the full captured description."""
    validate_location_scope(scope)
    locations = _locations(record)
    raw = record.get("raw") or {}
    body = raw.get("description")
    if (not locations or not isinstance(body, str) or not body.strip() or _OMISSION.search(body)
            or any(_UNKNOWN.search(value) for value in locations)):
        return None
    if "isRemote" in raw and raw["isRemote"] is not None and type(raw["isRemote"]) is not bool:
        return None
    if raw.get("isRemote") is True:
        return None
    for key in ("workplaceType", "workplace_model"):
        if raw.get(key) is not None and not isinstance(raw[key], str):
            return None
    workplace = " ".join(raw.get(key) or "" for key in ("workplaceType", "workplace_model"))
    text = "\n".join([*locations, workplace, body])
    if _REMOTE.search(" ".join(text.split())):
        return None
    if any(_contains(text, label) for label in (*scope.local_labels, *scope.exception_labels)):
        return None
    broad = {_normalize(label) for label in scope.broad_labels}
    if "united states" in broad:
        broad.add("united states of america")
    for value in locations:
        # A country-wide label is uncertain; a city within that country is not.
        if any(_only_broad_labels(part, broad) for part in re.split(r"[;|/]", value)):
            return None
    description_hash = hashlib.sha256(body.encode()).hexdigest()
    policy_hash = hashlib.sha256(json.dumps({
        "policy": scope.policy, "local_labels": scope.local_labels,
        "exception_labels": scope.exception_labels, "broad_labels": scope.broad_labels,
        "user_confirmed": scope.user_confirmed,
    }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {
        "status": "excluded", "reason_code": "nonlocal_without_remote_option",
        "rationale": "Approved geographic search scope: published locations are nonlocal ("
            + "; ".join(locations) + "). No remote option or approved local alternative appears in the complete captured description or location metadata.",
        "evidence": [record["posting_url"]],
        "prefilter": {"policy": scope.policy, "policy_hash": policy_hash, "matcher_version": MATCHER_VERSION,
            "published_locations": locations, "description_sha256": description_hash},
    }
