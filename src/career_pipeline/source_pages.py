"""Strict full-page adapters; pagination evidence is a provider contract.

Raw responses must be persisted by the caller before parsing. Incomplete jobs
remain records so their missing review fields can be resolved as durable work.
"""
from __future__ import annotations

import copy
import re
from functools import partial
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urlsplit


_PROVIDERS = {"greenhouse", "ashby", "lever", "indeed", "unstructured"}
NORMALIZATION_VERSION = 2


def _page_parameters(provider: str, query: dict, cursor: str | None) -> tuple[int, int]:
    if provider not in _PROVIDERS or not isinstance(query, dict):
        raise ValueError("invalid_provider_or_query")
    if provider in {"greenhouse", "ashby", "lever"}:
        for name in ("board", "employer"):
            if not isinstance(query.get(name), str) or not query[name].strip():
                raise ValueError(f"{name}_context_required")
    size = query.get("page_size", 100)
    if provider == "lever":
        if type(size) is not int or not 1 <= size <= 100:
            raise ValueError("invalid_page_size")
        if cursor is not None and (not isinstance(cursor, str) or not re.fullmatch(r"0|[1-9][0-9]*", cursor)):
            raise ValueError("invalid_cursor")
        return size, int(cursor or "0")
    if cursor is not None:
        raise ValueError("provider_has_no_cursor")
    return 100, 0


class _DescriptionText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        if tag in {"p", "br", "div", "li", "h1", "h2", "h3", "h4", "section", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
        if tag in {"p", "div", "li", "h1", "h2", "h3", "h4", "section", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def _text(value: object, *, html: bool = False, normalization_version: int = NORMALIZATION_VERSION) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError("malformed_text_field")
    if html:
        # Greenhouse can encode its HTML tags more than once. Decode only
        # while markup remains encoded, preserving literal text entities.
        while "<" not in value and re.search(r"&(?:amp;)*lt;/?[a-zA-Z]", value):
            value = unescape(value)
        parser = _DescriptionText()
        parser.feed(value)
        if normalization_version >= 2:
            parser.close()  # Flush text buffered behind a trailing ampersand or '<'.
        value = "".join(parser.parts)
    return "\n".join(line.strip() for line in value.splitlines() if line.strip())


def _count(value: object) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("invalid_reported_count")
    return value


def _record(provider: str, row: dict, query: dict, normalization_version: int) -> dict:
    html_text = partial(_text, html=True, normalization_version=normalization_version)
    id_key = "jrtk" if provider == "indeed" else "id"
    identity = row.get(id_key)
    if provider == "ashby" and "id" not in row:
        url = row.get("jobUrl")
        if not isinstance(url, str):
            raise ValueError("source_record_id_required")
        parsed = urlsplit(url)
        parts = parsed.path.strip("/").split("/")
        if (parsed.scheme != "https" or parsed.hostname != "jobs.ashbyhq.com"
                or parsed.username is not None or parsed.password is not None
                or parsed.port not in (None, 443) or len(parts) != 2
                or parts[0] != query["board"] or not re.fullmatch(r"[A-Za-z0-9_-]+", parts[1])):
            raise ValueError("invalid_ashby_posting_identity")
        identity = parts[1]
    if (type(identity) not in (str, int) or (isinstance(identity, str) and not identity.strip())
            or (type(identity) is int and identity < 0)):
        raise ValueError("source_record_id_required")
    raw = copy.deepcopy(row)
    title = row.get("text" if provider == "lever" else "title")
    employer = row.get("company") if provider == "indeed" else query["employer"]
    location = row.get("location")
    if provider == "greenhouse":
        if location is not None and not isinstance(location, dict):
            raise ValueError("malformed_location")
        location = (location or {}).get("name")
        description = html_text(row.get("content"))
        url = row.get("absolute_url")
        requisition = row.get("requisition_id")
    elif provider == "ashby":
        if "isListed" in row and type(row["isListed"]) is not bool:
            raise ValueError("invalid_is_listed")
        description = _text(row.get("descriptionPlain")) or html_text(row.get("descriptionHtml"))
        url, requisition = row.get("jobUrl"), row.get("requisitionId")
    elif provider == "lever":
        categories = row.get("categories", {})
        if not isinstance(categories, dict):
            raise ValueError("malformed_categories")
        location = categories.get("location")
        combined = _text(row.get("descriptionPlain")) or html_text(row.get("description"))
        sections = [combined] if combined else [
            _text(row.get("openingPlain")) or html_text(row.get("opening")),
            _text(row.get("descriptionBodyPlain")) or html_text(row.get("descriptionBody")),
        ]
        lists = row.get("lists", [])
        if not isinstance(lists, list):
            raise ValueError("malformed_description_sections")
        for section in lists:
            if not isinstance(section, dict):
                raise ValueError("malformed_description_section")
            sections.extend((_text(section.get("text")), html_text(section.get("content"))))
        sections.append(_text(row.get("additionalPlain")) or html_text(row.get("additional")))
        sections.append(_text(row.get("salaryDescriptionPlain")) or html_text(row.get("salaryDescription")))
        description = "\n".join(section for section in sections if section)
        url, requisition = row.get("hostedUrl"), row.get("requisition")
    else:
        description = html_text(row.get("description"))
        url, requisition = row.get("url"), row.get("requisition_id")
    if "description" in row:
        # Retain the original HTML when the provider uses our normalized key.
        raw["provider_description"] = copy.deepcopy(row["description"])
    raw["description"] = description
    record = dict(source=provider, source_record_id=str(identity), employer=_text(employer), title=_text(title),
                  location=_text(location), posting_url=_text(url),
                  requisition_id=None if requisition is None else _text(requisition), raw=raw)
    if provider == "ashby" and "isListed" in row:
        record["is_listed"] = row["isListed"]
    return record


def _unstructured_record(row: object) -> dict:
    if not isinstance(row, dict) or not isinstance(row.get("raw"), dict):
        raise ValueError("malformed_extracted_listing")
    record = copy.deepcopy(row)
    url = row.get("posting_url", "")
    if url is None:
        url = ""
    if not isinstance(url, str):
        raise ValueError("malformed_posting_url")
    if url:
        parsed = urlsplit(url)
        if (parsed.scheme not in {"https", "http"} or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or any(character.isspace() or ord(character) < 32 for character in url)):
            raise ValueError("invalid_posting_url")
        # Accessing the parsed port rejects malformed authorities.
        parsed.port
    identity = row.get("source_record_id")
    if identity in (None, ""):
        identity = url
    if not isinstance(identity, str) or not identity.strip():
        raise ValueError("source_record_id_required")
    record.update(source="unstructured", source_record_id=identity, posting_url=url)
    for field in ("employer", "title", "location"):
        record[field] = _text(row.get(field))
    requisition = row.get("requisition_id")
    record["requisition_id"] = None if requisition is None else _text(requisition)
    _text(record["raw"].get("description"))  # Validate optional canonical text; retain it verbatim.
    return record


def _unstructured_page(response: object) -> dict:
    records, seen = [], set()
    if isinstance(response, dict) and "extracted_listings" in response:
        if "raw_response" not in response or not isinstance(response["extracted_listings"], list):
            raise ValueError("original_response_and_extracted_listings_required")
        for row in response["extracted_listings"]:
            record = _unstructured_record(row)
            if record["source_record_id"] in seen:
                raise ValueError("duplicate_source_record_id")
            seen.add(record["source_record_id"])
            records.append(record)
    # A recognized subset is never a count of the native response's inventory.
    # The caller snapshots the full response (including raw_response) first.
    return dict(records=records, reported_total=None, exhausted=False, next_cursor=None,
                limitations=["unstructured_source_not_enumerable"])


def parse_page(provider: str, response: object, *, query: dict, cursor: str | None = None,
               normalization_version: int = NORMALIZATION_VERSION) -> dict:
    """Account for every valid row and derive exhaustion from provider semantics."""
    # Version 1 intentionally preserves pre-EOF normalization for old receipts.
    if type(normalization_version) is not int or normalization_version not in (1, NORMALIZATION_VERSION):
        raise ValueError("invalid_normalization_version")
    size, offset = _page_parameters(provider, query, cursor)
    if provider == "unstructured":
        return _unstructured_page(response)
    payload = response
    if provider == "indeed" and isinstance(payload, dict):
        if payload.get("isError"):
            raise ValueError("provider_error_response")
        if "structuredContent" in payload:
            payload = payload["structuredContent"]
    total = None
    if provider == "lever":
        rows = payload
    else:
        if not isinstance(payload, dict) or "jobs" not in payload:
            raise ValueError("provider_jobs_required")
        rows = payload["jobs"]
        if provider == "greenhouse" and "meta" in payload:
            if not isinstance(payload["meta"], dict) or "total" not in payload["meta"]:
                raise ValueError("malformed_meta_total")
            total = _count(payload["meta"]["total"])
        if provider == "indeed":
            counts = [_count(payload[key]) for key in ("totalAvailable", "total_results", "totalResults") if key in payload]
            if len(set(counts)) > 1:
                raise ValueError("conflicting_reported_totals")
            total = counts[0] if counts else None
    if not isinstance(rows, list):
        raise ValueError("provider_jobs_list_required")
    if total is not None and (len(rows) > total or (provider == "greenhouse" and len(rows) != total)):
        raise ValueError("reported_total_mismatch")
    if provider == "indeed" and "resultsShown" in payload and _count(payload["resultsShown"]) != len(rows):
        raise ValueError("reported_results_shown_mismatch")
    if provider == "lever" and len(rows) > size:
        raise ValueError("page_size_exceeded")
    records, seen = [], set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("malformed_job_row")
        record = _record(provider, row, query, normalization_version)
        if record["source_record_id"] in seen:
            raise ValueError("duplicate_source_record_id")
        seen.add(record["source_record_id"])
        records.append(record)
    exhausted = provider != "indeed" and (provider != "lever" or len(rows) < size)
    return dict(records=records, reported_total=total, exhausted=exhausted,
                next_cursor=str(offset + size) if provider == "lever" and not exhausted else None,
                limitations=["provider_has_no_pagination"] if provider == "indeed" else [])
