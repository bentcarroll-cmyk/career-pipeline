"""Public board requests with fixed provider hosts and no credentials."""
from __future__ import annotations

import json
import re
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .source_pages import _page_parameters


_HOSTS = {"boards-api.greenhouse.io", "api.ashbyhq.com", "api.lever.co", "api.eu.lever.co"}


def _safe_url(url: str, *, expected_host: str | None = None) -> None:
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname not in _HOSTS
            or parsed.username is not None or parsed.password is not None
            or parsed.port not in (None, 443) or parsed.fragment
            or (expected_host is not None and parsed.hostname != expected_host)):
        raise ValueError("unsafe_provider_url")


class _SafeRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _safe_url(newurl, expected_host=urlsplit(req.full_url).hostname)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _fetch_json(url: str) -> object:
    _safe_url(url)
    # Ignore ambient proxies; their URLs may contain credentials. This opener
    # includes neither authentication nor cookie handlers.
    opener = build_opener(ProxyHandler({}), _SafeRedirectHandler())
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "Career-Pipeline/board-collector"})
    with opener.open(request, timeout=30) as response:
        _safe_url(response.geturl(), expected_host=urlsplit(url).hostname)
        if response.status != 200:
            raise ValueError("unsuccessful_provider_response")
        return json.loads(response.read())


def validate_board_query(provider: str, query: dict) -> None:
    """Validate the implemented whole-board scope; no search filters exist.

    Registration and capture callers may use this without making a request.
    Lever's page size and region select pagination/API host, not eligibility.
    """
    if provider not in {"greenhouse", "ashby", "lever"}:
        raise ValueError("unsupported_board_provider")
    if not isinstance(query, dict):
        raise ValueError("invalid_board_query")
    supported = {"board", "employer"}
    if provider == "lever":
        supported.update({"page_size", "region"})
    if set(query) - supported:
        raise ValueError("unsupported_board_query_fields")
    _page_parameters(provider, query, None)
    board = query["board"]
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", board):
        raise ValueError("invalid_board_token")
    region = query.get("region", "us")
    if not isinstance(region, str) or region not in {"us", "eu"}:
        raise ValueError("invalid_provider_region")


def fetch_board_page(provider: str, *, query: dict, cursor: str | None = None, fetch_json=None) -> object:
    """Fetch one entire public page. Caller owns immediate durable capture."""
    validate_board_query(provider, query)
    size, offset = _page_parameters(provider, query, cursor)
    token = quote(query["board"], safe="")
    region = query.get("region", "us")
    if provider == "greenhouse":
        url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?" + urlencode({"content": "true"})
    elif provider == "ashby":
        url = f"https://api.ashbyhq.com/posting-api/job-board/{token}?" + urlencode({"includeCompensation": "true"})
    else:
        host = "api.eu.lever.co" if region == "eu" else "api.lever.co"
        url = f"https://{host}/v0/postings/{token}?" + urlencode({"mode": "json", "skip": offset, "limit": size})
    _safe_url(url)
    return (fetch_json or _fetch_json)(url)
