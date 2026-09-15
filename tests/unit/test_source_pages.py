"""Provider page accounting must fail closed without losing listing pointers."""
import copy
import importlib.util
import unittest


QUERY = {"board": "example", "employer": "Example", "page_size": 2}


def greenhouse_job(number=1, **changes):
    row = {"id": number, "title": "Operations Lead", "absolute_url": f"https://boards.greenhouse.io/example/jobs/{number}",
           "location": {"name": "Remote"}, "content": "&lt;h2&gt;Responsibilities&lt;/h2&gt;&lt;p&gt;Lead &amp;amp; coach.&lt;/p&gt;",
           "metadata": [{"id": 7, "value": "retained"}]}
    row.update(changes)
    return row


def lever_job(number=1, **changes):
    row = {"id": f"posting-{number}", "text": "Operations Lead", "hostedUrl": f"https://jobs.lever.co/example/posting-{number}",
           "categories": {"location": "Remote", "team": "Operations"},
           "description": "<p>Lead the organization.</p>",
           "lists": [{"text": "Requirements", "content": "<ul><li>Build teams.</li><li>Measure results.</li></ul>"}],
           "additional": "<p>Equal opportunity employer.</p>"}
    row.update(changes)
    return row


def indeed_response(description):
    return {
        "content": [], "isError": False,
        "structuredContent": {
            "jobs": [{"jrtk": "JOBSEARCH_synthetic", "title": "Operations Lead",
                      "company": "Example Cooperative", "company_rating": 4.0,
                      "advertiser_name": "Example Cooperative", "sponsored": False,
                      "url": "https://www.indeed.com/viewjob?jk=synthetic",
                      "description": description, "location": "Remote US",
                      "salary": "$160,000 - $200,000", "job_type": "Full-time",
                      "work_settings": ["Remote"], "posted_date": "Today"}],
            "resultsShown": 1, "totalAvailable": 840, "totalApproximate": "800+",
            "search": "operations", "location": "Remote US",
        },
    }


class SourcePageTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec("career_pipeline.source_pages"),
                             "Full provider pages need strict parsing and exhaustion accounting")
        from career_pipeline.source_pages import parse_page
        self.parse = parse_page

    def test_greenhouse_count_and_full_description_with_raw_fields(self):
        response = {"jobs": [greenhouse_job()], "meta": {"total": 1}}
        original = copy.deepcopy(response)
        page = self.parse("greenhouse", response, query=QUERY)
        self.assertTrue(page["exhausted"])
        self.assertEqual(page["reported_total"], 1)
        self.assertIsNone(page["next_cursor"])
        record = page["records"][0]
        self.assertEqual(record["source_record_id"], "1")
        self.assertEqual(record["employer"], "Example")
        self.assertEqual(record["raw"]["metadata"], original["jobs"][0]["metadata"])
        self.assertEqual(record["raw"]["content"], original["jobs"][0]["content"])
        self.assertIn("Responsibilities", record["raw"]["description"])
        self.assertIn("Lead & coach.", record["raw"]["description"])
        self.assertEqual(response, original)

    def test_greenhouse_empty_is_exhausted_and_total_optional(self):
        for response in ({"jobs": [], "meta": {"total": 0}}, {"jobs": []}):
            self.assertTrue(self.parse("greenhouse", response, query=QUERY)["exhausted"])

    def test_missing_review_fields_survive_as_pointers(self):
        for provider, response in (
            ("greenhouse", {"jobs": [greenhouse_job(content=None), {"id": 2}]}),
            ("ashby", {"jobs": [{"id": "1", "title": "Lead", "jobUrl": "https://jobs.ashbyhq.com/example/1"}, {"id": "2"}]}),
            ("lever", [{"id": "1"}, {"id": "2"}]),
        ):
            with self.subTest(provider=provider):
                rows = self.parse(provider, response, query=QUERY)["records"]
                self.assertEqual(len(rows), 2)
                self.assertFalse(rows[0]["raw"]["description"])
                self.assertFalse(rows[1]["title"])

    def test_ashby_nonpublic_is_accounted_and_flagged(self):
        response = {"jobs": [{"id": "a", "title": "Lead", "isListed": False,
                              "jobUrl": "https://jobs.ashbyhq.com/example/a", "descriptionHtml": "<p>Private role.</p>"},
                             {"id": "b", "isListed": True, "descriptionPlain": "Public role.", "compensation": {"salary": 123}}]}
        page = self.parse("ashby", response, query=QUERY)
        self.assertTrue(page["exhausted"])
        self.assertEqual(len(page["records"]), 2)
        self.assertIs(page["records"][0]["raw"]["isListed"], False)
        self.assertEqual(page["records"][0]["raw"]["description"], "Private role.")
        self.assertEqual(page["records"][1]["raw"]["compensation"], {"salary": 123})

    def test_ashby_documented_no_id_shape_uses_posting_identity(self):
        url = "https://jobs.ashbyhq.com/example/12345678-1234-1234-1234-123456789abc?ref=board#details"
        row = {"title": "Lead", "jobUrl": url, "descriptionPlain": "Run operations.", "isListed": True}
        record = self.parse("ashby", {"apiVersion": "1", "jobs": [row]}, query=QUERY)["records"][0]
        self.assertEqual(record["source_record_id"], "12345678-1234-1234-1234-123456789abc")
        self.assertEqual(record["posting_url"], url)
        self.assertEqual(record["raw"]["jobUrl"], url)
        for bad in ("https://evil.test/example/123", "https://jobs.ashbyhq.com/other/123",
                    "http://jobs.ashbyhq.com/example/123", "https://user" + "@jobs.ashbyhq.com/example/123",
                    "https://jobs.ashbyhq.com/example/", "https://jobs.ashbyhq.com/example/../123"):
            with self.subTest(url=bad), self.assertRaises(ValueError):
                self.parse("ashby", {"jobs": [{**row, "jobUrl": bad}]}, query=QUERY)

    def test_lever_full_short_and_empty_pages(self):
        for response, cursor, exhausted, next_cursor in (
            ([lever_job(), lever_job(2)], None, False, "2"),
            ([lever_job(3)], "2", True, None),
            ([], "4", True, None),
        ):
            with self.subTest(cursor=cursor):
                page = self.parse("lever", response, query=QUERY, cursor=cursor)
                self.assertEqual(page["exhausted"], exhausted)
                self.assertEqual(page["next_cursor"], next_cursor)
                self.assertIsNone(page["reported_total"])

    def test_lever_full_sections_and_original_html_retained(self):
        row = lever_job()
        record = self.parse("lever", [row], query=QUERY)["records"][0]
        for section in ("Lead the organization.", "Requirements", "Build teams.", "Measure results.", "Equal opportunity employer."):
            self.assertIn(section, record["raw"]["description"])
        self.assertEqual(record["raw"]["lists"], row["lists"])
        self.assertEqual(record["raw"]["provider_description"], row["description"])

    def test_lever_separate_body_and_salary_sections_are_not_lost(self):
        row = lever_job(description=None, openingPlain="Opening.", descriptionBody="<p>Full body.</p>",
                        salaryDescription="<p>Salary varies by location.</p>")
        description = self.parse("lever", [row], query=QUERY)["records"][0]["raw"]["description"]
        for text in ("Opening.", "Full body.", "Salary varies by location."):
            self.assertIn(text, description)

    def test_greenhouse_double_escaped_html_is_readable(self):
        row = greenhouse_job(content="&amp;lt;h2&amp;gt;Duties&amp;lt;/h2&amp;gt;&amp;lt;p&amp;gt;Lead.&amp;lt;/p&amp;gt;")
        description = self.parse("greenhouse", {"jobs": [row]}, query=QUERY)["records"][0]["raw"]["description"]
        self.assertEqual(description, "Duties\nLead.")

    def test_indeed_native_wrapper_is_always_supplementary(self):
        jobs = [{"jrtk": "opaque-1", "title": "Lead", "company": "Example", "url": "https://www.indeed.com/viewjob?jk=1",
                 "description": "Full duties", "salary": "$160,000", "location": "Remote"}]
        for total in (1, 840):
            page = self.parse("indeed", {"structuredContent": {"jobs": jobs, "resultsShown": 1, "totalAvailable": total,
                                                                 "totalApproximate": "800+", "search": "Lead", "location": "Remote"},
                                        "content": []}, query={"search": "Lead"})
            self.assertEqual(page["reported_total"], total)
            self.assertFalse(page["exhausted"])
            self.assertIsNone(page["next_cursor"])
            self.assertIn("provider_has_no_pagination", page["limitations"])
            self.assertEqual(page["records"][0]["source_record_id"], "opaque-1")
            self.assertEqual(page["records"][0]["raw"]["salary"], "$160,000")

    def test_indeed_plaintext_eof_preserves_full_description_and_native_fields(self):
        description = "Lead the organization.\nBuild measurable customer outcomes.\nOwn the P&L."
        response = indeed_response(description)
        original = copy.deepcopy(response)
        page = self.parse("indeed", response, query={"search": "operations"})
        raw = page["records"][0]["raw"]
        self.assertEqual(raw["description"], description)
        self.assertEqual(raw["provider_description"], description)
        for field, value in original["structuredContent"]["jobs"][0].items():
            self.assertEqual(raw[field], value)
        self.assertEqual(response, original)
        self.assertFalse(page["exhausted"])

    def test_html_description_fields_flush_visible_text_at_eof_for_all_providers(self):
        text = "<h2>Responsibilities</h2><p>Lead &amp; coach.</p>Own the P&L."
        cases = (
            ("indeed", indeed_response(text), "provider_description"),
            ("greenhouse", {"jobs": [greenhouse_job(content=text)]}, "content"),
            ("ashby", {"jobs": [{"id": "one", "descriptionHtml": text}]}, "descriptionHtml"),
            ("lever", [lever_job(description=text, lists=[], additional=None)], "provider_description"),
        )
        for provider, response, original_field in cases:
            with self.subTest(provider=provider):
                original = copy.deepcopy(response)
                raw = self.parse(provider, response, query=QUERY)["records"][0]["raw"]
                self.assertEqual(raw["description"], "Responsibilities\nLead & coach.\nOwn the P&L.")
                self.assertEqual(raw[original_field], text)
                self.assertEqual(response, original)

    def test_eof_preserves_literal_ampersands_and_less_than_signs(self):
        cases = (
            ("Manage R&D and the P&L.", "Manage R&D and the P&L."),
            ("Lead < 5 teams &", "Lead < 5 teams &"),
            ("Use the comparison <", "Use the comparison <"),
            ("<p>AT&amp;T</p>Budget < 5 and P&L.", "AT&T\nBudget < 5 and P&L."),
        )
        for native, expected in cases:
            with self.subTest(native=native):
                raw = self.parse("indeed", indeed_response(native), query={})["records"][0]["raw"]
                self.assertEqual(raw["description"], expected)
                self.assertEqual(raw["provider_description"], native)

    def test_eof_keeps_html_suppression_and_incomplete_markup_semantics(self):
        cases = (
            ("<p>Lead.</p><script>hidden &</script><style>hidden <</style>Own P&L.", "Lead.\nOwn P&L."),
            ("<p>Lead.</p><script>hidden &", "Lead."),
            ("<p>Lead.</p><style>hidden &", "Lead."),
            ("<p>Lead.</p><!-- hidden &", "Lead."),
            ("<p>Lead.</p><strong", "Lead."),
            ("<p>Lead &amp; coach", "Lead & coach"),
            ("&amp;lt;p&amp;gt;Lead.&amp;lt;/p&amp;gt;Own P&L.", "Lead.\nOwn P&L."),
        )
        for native, expected in cases:
            with self.subTest(native=native):
                raw = self.parse("indeed", indeed_response(native), query={})["records"][0]["raw"]
                self.assertEqual(raw["description"], expected)
                self.assertEqual(raw["provider_description"], native)

    def test_malformed_shapes_rows_ids_and_counts_raise(self):
        cases = [
            ("greenhouse", {}), ("greenhouse", {"jobs": {}}),
            ("greenhouse", {"jobs": [greenhouse_job()], "meta": {"total": 2}}),
            ("greenhouse", {"jobs": [], "meta": {"total": True}}),
            ("greenhouse", {"jobs": [], "meta": {}}),
            ("ashby", {"jobs": [None]}), ("ashby", {"jobs": [{"id": ""}]}),
            ("ashby", {"jobs": [{"id": "x", "isListed": "false"}]}),
            ("lever", {}), ("lever", [lever_job(), "bad"]),
            ("lever", [lever_job(), lever_job()]),
            ("lever", [lever_job(), lever_job(2), lever_job(3)]),
            ("lever", [lever_job(lists=["bad"])]),
            ("indeed", {"jobs": [{"id": "wrong-id"}]}),
            ("indeed", {"jobs": [{"jrtk": "x"}], "total_results": 0}),
            ("indeed", {"jobs": [{"jrtk": "x"}], "resultsShown": 2}),
            ("indeed", {"structuredContent": {"jobs": []}, "isError": True}),
        ]
        for provider, response in cases:
            with self.subTest(provider=provider, response=response):
                with self.assertRaises(ValueError):
                    self.parse(provider, response, query=QUERY)

    def test_invalid_cursor_and_query_are_rejected(self):
        for cursor in ("-1", "1.5", "01", "", 0, True):
            with self.subTest(cursor=cursor), self.assertRaises(ValueError):
                self.parse("lever", [], query=QUERY, cursor=cursor)
        for provider in ("greenhouse", "ashby", "indeed"):
            with self.subTest(provider=provider), self.assertRaises(ValueError):
                self.parse(provider, {"jobs": []}, query=QUERY, cursor="1")

    def test_unstructured_native_payload_never_implies_empty_complete_inventory(self):
        for response in ({"results": [{"url": "https://example.test/job/1"}], "total": 1},
                         {"jobs": [greenhouse_job()], "meta": {"total": 1}},
                         {"structuredContent": {"jobs": [], "totalAvailable": 0}},
                         "Raw browser text", [], None):
            with self.subTest(response=response):
                page = self.parse("unstructured", response, query={"search": "operations"})
                self.assertEqual(page["records"], [])
                self.assertIsNone(page["reported_total"])
                self.assertFalse(page["exhausted"])
                self.assertIsNone(page["next_cursor"])
                self.assertEqual(page["limitations"], ["unstructured_source_not_enumerable"])

    def test_unstructured_explicit_listing_extraction_preserves_complete_rows_and_pointers(self):
        native = {"results": [{"title": "Lead", "url": "https://example.test/jobs/1", "snippet": "Observed excerpt"}], "opaque": [1, 2]}
        pointer = {"employer": "Example", "title": "Lead", "location": "Remote",
                   "posting_url": "https://example.test/jobs/1?ref=search#role", "raw": {"snippet": "Observed excerpt"}}
        complete = {"source_record_id": "native-2", "source": "caller-source", "employer": "Example", "title": "Manager",
                    "location": "Remote", "posting_url": "http://example.test/jobs/2", "requisition_id": "REQ-2",
                    "raw": {"description": "Full duties.\nFull requirements.", "salary": "Undisclosed"}}
        response = {"raw_response": native, "extracted_listings": [pointer, complete]}
        original = copy.deepcopy(response)
        page = self.parse("unstructured", response, query={})
        self.assertEqual(len(page["records"]), 2)
        self.assertEqual(page["records"][0]["source_record_id"], pointer["posting_url"])
        self.assertFalse(page["records"][0]["raw"].get("description"))
        self.assertEqual(page["records"][0]["raw"]["snippet"], "Observed excerpt")
        self.assertEqual(page["records"][1]["raw"], complete["raw"])
        self.assertEqual(page["records"][1]["requisition_id"], "REQ-2")
        self.assertEqual(page["records"][1]["source_record_id"], "native-2")
        self.assertEqual(page["records"][1]["source"], "unstructured")
        self.assertFalse(page["exhausted"])
        self.assertIsNone(page["reported_total"])
        self.assertEqual(response, original)

    def test_unstructured_extraction_requires_original_response_and_valid_records(self):
        row = {"source_record_id": "one", "posting_url": "https://example.test/jobs/1", "raw": {}}
        for response in ({"extracted_listings": [row]},
                         {"raw_response": {}, "extracted_listings": {}},
                         {"raw_response": {}, "extracted_listings": [None]},
                         {"raw_response": {}, "extracted_listings": [{"source_record_id": "one"}]},
                         {"raw_response": {}, "extracted_listings": [row, row]},
                         {"raw_response": {}, "extracted_listings": [{**row, "posting_url": []}]},
                         {"raw_response": {}, "extracted_listings": [{**row, "raw": {"description": ["bad"]}}]},
                         {"raw_response": {}, "extracted_listings": [{**row, "title": {"bad": "shape"}}]}):
            with self.subTest(response=response), self.assertRaises(ValueError):
                self.parse("unstructured", response, query={})
        for url in ("javascript:alert(1)", "file:///tmp/job", "https:///job", "https://user:pass" + "@example.test/job", "https://example.test/a\nb", "https://example.test:invalid/job"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                self.parse("unstructured", {"raw_response": {}, "extracted_listings": [{"posting_url": url, "raw": {}}]}, query={})
        with self.assertRaises(ValueError):
            self.parse("unstructured", {}, query={}, cursor="1")
