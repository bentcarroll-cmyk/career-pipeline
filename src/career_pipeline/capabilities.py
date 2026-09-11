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
