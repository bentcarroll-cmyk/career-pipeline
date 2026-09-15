from __future__ import annotations

import copy
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from career_pipeline import criteria
from tests.unit.test_review_queue import record


def location_scope():
    return criteria.DiscoveryLocationScope(
        policy="exclude_nonlocal_without_remote_option", user_confirmed=True,
        local_labels=("Maryland", "MD", "Washington DC", "District of Columbia"),
        exception_labels=("Arlington VA", "Reston VA", "Chantilly VA"),
        broad_labels=("United States", "USA", "US", "North America", "Global", "Worldwide"),
    )


class LocationPrefilterTests(unittest.TestCase):
    def classify(self, location="Costa Mesa, California, United States", **raw):
        from career_pipeline.location_prefilter import exclusion_decision
        item = record(location=location, raw={"description": "Lead operations and improve workflows.", **raw})
        original = copy.deepcopy(item)
        result = exclusion_decision(item, location_scope())
        self.assertEqual(item, original)
        return result

    def test_explicit_nonlocal_without_remote_option_is_auditable_exclusion(self):
        result = self.classify()
        self.assertEqual(result["status"], "excluded")
        self.assertEqual(result["reason_code"], "nonlocal_without_remote_option")
        self.assertIn("Costa Mesa", result["rationale"])
        self.assertEqual(result["evidence"], [record()["posting_url"]])
        self.assertEqual(result["prefilter"]["policy"], location_scope().policy)

    def test_missing_ambiguous_country_only_and_allowed_locations_remain(self):
        for value in ("", "Unknown", "TBD", "Various locations", "Multiple locations", "United States", "North America",
                      "Remote US", "Washington, D.C.", "Washington D.C", "Bethesda, MD", "Reston, VA", "Chantilly, VA",
                      "United States of America", "US National", "USA nationwide", "Nationwide",
                      "New York; Washington DC", "Seattle / Maryland", "Location to be determined"):
            with self.subTest(value=value):
                self.assertIsNone(self.classify(value))

    def test_country_only_compounds_and_abbreviations_remain_uncertain(self):
        for value in ("United States (US)", "USA, United States", "US (United States)",
                      "United States [USA]", "USA - United States", "United States & US",
                      "United States of America (U.S.A.)", "U.S.A.", "U.S.A",
                      "North America (United States)", "United States and USA", "United States or US"):
            with self.subTest(value=value):
                self.assertIsNone(self.classify(value))

    def test_country_suffixes_do_not_hide_concrete_nonlocal_cities(self):
        for value in ("Seattle, US", "Seattle (United States)", "Seattle, USA, United States",
                      "Costa Mesa, United States (US)", "Richmond, VA, U.S.A.",
                      "London, United Kingdom", "United States, Seattle",
                      "Seattle and United States", "United States or Seattle"):
            with self.subTest(value=value):
                self.assertIsNotNone(self.classify(value))

    def test_alternative_location_or_remote_anywhere_vetoes_exclusion(self):
        cases = (
            {"secondaryLocations": [{"location": "Washington, DC"}]},
            {"categories": {"allLocations": ["Arlington, VA"]}},
            {"offices": [{"name": "Maryland"}]},
            {"workplaceType": "Remote"}, {"isRemote": True},
            {"workplaceType": "OnSite", "workplace_model": "Remote"},
            {"description": "This role may work remotely. Lead operations."},
            {"description": "Work from home is available. Lead operations."},
            {"description": "You can work\nfrom home. Lead operations."},
            {"description": "You may work from anywhere in the United States."},
            {"description": "This is a WFH position."},
            {"description": "Our distributed team can work across the country."},
            {"description": "Locations include Washington, D.C. and Seattle."},
            {"description": "Lead operations. [CONTENT_FILTERED] More requirements."},
            {"secondaryLocations": [{"location": None}]},
            {"location": {"name": "Remote US"}},
        )
        for raw in cases:
            with self.subTest(raw=raw):
                self.assertIsNone(self.classify(**raw))

    def test_location_words_use_boundaries_and_do_not_match_country_substrings(self):
        for value in ("Costa Mesa, United States", "Seattle, Washington", "Richmond, VA", "London, United Kingdom"):
            with self.subTest(value=value):
                self.assertIsNotNone(self.classify(value))

    def test_unapproved_policy_and_malformed_data_fail_open_for_review(self):
        from career_pipeline.location_prefilter import exclusion_decision
        with self.assertRaises(ValueError):
            exclusion_decision(record(), replace(location_scope(), user_confirmed=False))
        for raw in ({"description": ""}, {"description": "Known duties.", "secondaryLocations": "Remote US"},
                    {"description": "Known duties.", "isRemote": "true"},
                    {"secondaryLocations": {}}, {"offices": ""}, {"categories": []},
                    {"categories": {"allLocations": False}}, {"workplaceType": []}):
            self.assertIsNone(self.classify(**raw))


class LocationScopeCriteriaTests(unittest.TestCase):
    def test_approval_can_share_the_atomic_workspace_repair_lock(self):
        from career_pipeline.workspace import create_workspace
        from career_pipeline.job_store import workspace_lock
        from tests.integration.test_discovery_delivery import install_criteria
        with tempfile.TemporaryDirectory() as directory:
            workspace = create_workspace(Path(directory))
            approved = install_criteria(workspace)
            with workspace_lock(workspace):
                criteria.approve_workspace_criteria(workspace,
                    expected_readable_sha256=approved.readable_criteria_sha256,
                    expected_structured_sha256=approved.structured_sha256)
                self.assertEqual(criteria.resolve_workspace_criteria(workspace), approved)

    def test_optional_scope_is_hash_bound_and_legacy_mapping_is_unchanged(self):
        base = criteria.SearchCriteria("Profile/Search_Criteria.md", "b" * 64, ())
        self.assertNotIn("discovery_location_scope", criteria.criteria_to_mapping(base))
        scoped = replace(base, discovery_location_scope=location_scope())
        self.assertNotEqual(scoped.structured_sha256, base.structured_sha256)
        self.assertEqual(criteria.criteria_to_mapping(scoped)["discovery_location_scope"]["local_labels"], list(location_scope().local_labels))

    def test_policy_requires_explicit_confirmation_and_local_labels(self):
        base = criteria.SearchCriteria("Profile/Search_Criteria.md", "b" * 64, ())
        for scope in (replace(location_scope(), user_confirmed=False), replace(location_scope(), local_labels=()),
                      replace(location_scope(), policy="discard_unknown")):
            with self.subTest(scope=scope), self.assertRaises(criteria.CriteriaError):
                criteria.validate_search_criteria(replace(base, discovery_location_scope=scope))
