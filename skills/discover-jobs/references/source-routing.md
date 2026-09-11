# Source routing

Treat configured capabilities as the source of truth. An installed connector with a missing action does not provide that coverage.

1. Search enabled broad sources such as Indeed, public web search, and capability-verified LinkedIn job search.
2. Rotate through user-prioritized employer boards using the saved per-source cursor.
3. Prefer public Greenhouse, Lever, and Ashby adapters when the posting identifies one of those systems.
4. Use Firecrawl only when enabled for search or page extraction.
5. Use a user-controlled browser only when enabled and needed for authenticated or JavaScript-heavy pages.
6. Use USAJOBS only when enabled and its user-managed credential is available through the connector environment.

Do not claim LinkedIn jobs were searched when only people or company actions are available. Do not silently substitute one source's result for another. A failed or partial lane retains its prior last-successful timestamp, seen-record set, and rotation cursor.

For every candidate, retain source, source-local ID, ATS/requisition identity when present, exact URLs, retrieval/verification time, and raw-field hash. Store only the source content needed for verification in the run's private working evidence.
