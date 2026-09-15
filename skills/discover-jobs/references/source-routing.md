# Source routing

Treat configured capabilities as the source of truth. An installed connector with a missing action does not provide that coverage.

1. Register the full currently known enabled query/board plan using [accounted source retrieval](retrieval.md) before the first request. Register later-discovered queries before executing them. Indeed is supplementary: its current connector cannot establish exhaustive coverage. Public web search identifies sources and postings but is not a substitute for complete provider-board retrieval.
2. Rotate through user-prioritized employer boards using the saved per-source cursor.
3. Use `discovery_retrieval.py collect` for public Greenhouse, Lever, and Ashby boards when the posting identifies one of those systems; follow supported pagination with each raw page persisted before the next request.
4. Use Firecrawl only when enabled for search or page extraction.
5. Use a user-controlled browser only when enabled and needed for authenticated or JavaScript-heavy pages.
6. Use USAJOBS only when enabled and its user-managed credential is available through the connector environment.

Do not claim LinkedIn jobs were searched when only people or company actions are available. Do not silently substitute one source's result for another. A failed or partial lane retains its prior last-successful timestamp, seen-record set, and rotation cursor.

Resume actionable pending pages and retrieve missing-description pointers even when the whole board is not yet available. Never discard already returned listings because another query or board failed. Once returned rows and actionable work are handled, a permanent provider limitation does not prevent related query refinement or independent complete board scopes. Preserve the limited scope; narrower queries do not establish exhaustion of an earlier capped search.

Record an observed failed fetch for a known missing-description pointer with `discovery_retrieval.py fail --source-record-id <original pointer ID>`; the ID is required to distinguish it from an independent page failure. Plain `fail` without a source record ID is for board-page or native-query network failures. Successfully resolving a pointer clears its targeted failure while any permanent provider limitation remains incomplete.

For enabled web, Firecrawl, browser, USAJOBS, or other sources without a supported parser, register `provider: unstructured` with the configured source name and exact request arguments. Capture the full native response first, then capture an extraction envelope retaining `raw_response` plus every identified `extracted_listings` record. Complete records enter review; missing fields remain durable pointers. Unstructured coverage always remains incomplete, including when all extracted records have been reviewed.

For every candidate, retain source, source-local ID, ATS/requisition identity when present, exact URLs, actual retrieval/verification time, and raw-field hash. Preserve native provider responses in the private retrieval snapshots before normalization or selection.
