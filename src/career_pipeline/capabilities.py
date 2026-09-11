"""Semantic capability requirements for connector truthfulness."""

LINEAR_REQUIRED_ACTIONS = frozenset(
    {
        "search_issues",
        "create_issue",
        "read_issue",
        "manage_labels",
        "manage_views",
        "comment",
        "attach_file",
    }
)

OPTIONAL_CONNECTORS = (
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
