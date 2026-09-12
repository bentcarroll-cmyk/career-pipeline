"""Semantic connector capabilities without making any connector authoritative."""

LINEAR_EXPORT_ACTIONS = frozenset(
    {
        "create_issue",
        "read_issue",
    }
)

CONNECTORS = (
    "linear",
    "indeed",
    "linkedin",
    "firecrawl",
    "browser",
    "notion",
    "github",
    "gmail",
    "google-calendar",
    "google-drive",
    "usajobs",
)

PUBLIC_DISCOVERY_SOURCES = frozenset(
    {"public_ats", "public-search", "greenhouse", "lever", "ashby"}
)

# Connector actions are only discovery-capable when they can retrieve job
# opportunities. Read, export, and general enrichment actions must not enable
# scheduled discovery.
DISCOVERY_ACTIONS = {
    "indeed": frozenset({"job_search", "search_jobs"}),
    "linkedin": frozenset({"job_search", "search_jobs"}),
    "firecrawl": frozenset({"search", "web_search"}),
    "browser": frozenset({"job_search", "search_jobs", "web_search"}),
    "usajobs": frozenset({"job_search", "search_jobs", "search"}),
}
