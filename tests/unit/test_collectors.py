import importlib.util
import io
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request


QUERY = {"board": "example-company", "employer": "Example"}


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec("career_pipeline.collectors"),
                             "Board fetches need fixed hosts, validated arguments and bounded requests")
        from career_pipeline import collectors
        self.collectors = collectors

    def test_exact_unfiltered_endpoints_and_original_payload(self):
        for provider, query, cursor, expected in (
            ("greenhouse", QUERY, None, "https://boards-api.greenhouse.io/v1/boards/example-company/jobs?content=true"),
            ("ashby", QUERY, None, "https://api.ashbyhq.com/posting-api/job-board/example-company?includeCompensation=true"),
            ("lever", QUERY, None, "https://api.lever.co/v0/postings/example-company?mode=json&skip=0&limit=100"),
            ("lever", {**QUERY, "region": "eu", "page_size": 2}, "2", "https://api.eu.lever.co/v0/postings/example-company?mode=json&skip=2&limit=2"),
        ):
            with self.subTest(provider=provider, cursor=cursor):
                seen = []
                response = {"unmodified": [1, 2, {"deep": True}]}
                def fetch(url):
                    seen.append(url)
                    return response
                actual = self.collectors.fetch_board_page(provider, query=query, cursor=cursor, fetch_json=fetch)
                self.assertIs(actual, response)
                self.assertEqual(seen, [expected])

    def test_invalid_arguments_do_not_request_network(self):
        calls = []
        cases = [("unknown", QUERY, None), ("indeed", QUERY, None), ("unstructured", QUERY, None)]
        for board in ("", "../evil", "foo/bar", "foo?x=y", "x%2fy", "x" + "@evil.test", "https://evil.test", " x", "x\\y", None):
            cases.append(("lever", {**QUERY, "board": board}, None))
        for size in (0, -1, 101, True, "2", 1.5):
            cases.append(("lever", {**QUERY, "page_size": size}, None))
        for cursor in ("-1", "01", "1.5", "", 0, True):
            cases.append(("lever", QUERY, cursor))
        cases.extend([("lever", {**QUERY, "region": "evil.test"}, None),
                      ("greenhouse", QUERY, "1"), ("ashby", QUERY, "0"),
                      ("greenhouse", {"board": "example"}, None)])
        for provider, query, cursor in cases:
            with self.subTest(provider=provider, query=query, cursor=cursor), self.assertRaises(ValueError):
                self.collectors.fetch_board_page(provider, query=query, cursor=cursor, fetch_json=lambda url: calls.append(url))
        self.assertEqual(calls, [])

    def test_cross_host_and_downgrade_redirects_are_rejected(self):
        redirect = self.collectors._SafeRedirectHandler()
        request = Request("https://api.lever.co/v0/postings/example?mode=json")
        for destination in ("https://evil.test/jobs", "http://api.lever.co/jobs", "https://user:pass" + "@api.lever.co/jobs", "https://api.lever.co:444/jobs"):
            with self.subTest(destination=destination), self.assertRaises(ValueError):
                redirect.redirect_request(request, None, 302, "redirect", {}, destination)
        allowed = redirect.redirect_request(request, None, 302, "redirect", {}, "https://api.lever.co/new")
        self.assertEqual(allowed.full_url, "https://api.lever.co/new")

    def test_unsupported_filters_cannot_silently_fetch_a_whole_board(self):
        # Removing the query allowlist would fetch an unfiltered page while
        # the caller believed these registered constraints were applied.
        calls = []
        for provider in ("greenhouse", "ashby", "lever"):
            for field, value in (("location", "Remote"), ("remote", True),
                                 ("salary_min", 150000), ("department", "Operations"),
                                 ("search", "AI"), ("filters", {}),
                                 ("limit", 10), ("scope", "filtered")):
                with self.subTest(provider=provider, field=field):
                    with self.assertRaisesRegex(ValueError, "unsupported_board_query_fields"):
                        self.collectors.fetch_board_page(
                            provider, query={**QUERY, field: value},
                            fetch_json=lambda url: calls.append(url))
        self.assertEqual(calls, [])

    def test_provider_specific_options_are_not_ignored_by_other_boards(self):
        calls = []
        for provider in ("greenhouse", "ashby"):
            for field, value in (("page_size", 50), ("region", "us"), ("region", "eu")):
                with self.subTest(provider=provider, field=field, value=value):
                    with self.assertRaisesRegex(ValueError, "unsupported_board_query_fields"):
                        self.collectors.fetch_board_page(
                            provider, query={**QUERY, field: value},
                            fetch_json=lambda url: calls.append(url))
        self.assertEqual(calls, [])

    def test_network_uses_timeout_no_credentials_and_rejects_bad_json(self):
        seen = []
        class Response(io.BytesIO):
            status = 200
            def geturl(self):
                return "https://api.lever.co/v0/postings/example-company?mode=json&skip=0&limit=100"
        class Opener:
            def open(self, request, timeout):
                seen.append((request, timeout))
                return Response(b"not JSON")
        with patch.object(self.collectors, "build_opener", return_value=Opener()):
            with self.assertRaises(ValueError):
                self.collectors.fetch_board_page("lever", query=QUERY)
        self.assertGreater(seen[0][1], 0)
        self.assertLessEqual(seen[0][1], 60)
        self.assertNotIn("Authorization", dict(seen[0][0].header_items()))
        self.assertNotIn("Cookie", dict(seen[0][0].header_items()))

    def test_fetch_failure_is_propagated_for_caller_to_persist(self):
        def fail(url):
            raise HTTPError(url, 503, "Unavailable", {}, None)
        with self.assertRaises(HTTPError):
            self.collectors.fetch_board_page("greenhouse", query=QUERY, fetch_json=fail)
