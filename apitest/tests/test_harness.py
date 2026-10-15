"""Self-contained tests, without contacting any running service."""

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from ..run_all import DiscoveryError, discover, run, write_report
from ..support import Result


class HarnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "cases"
        self.root.mkdir()
        self.report = Path(self.temp.name) / "report.html"

    def case(
        self,
        path: str,
        body: str = 'checks.require(True, "response.schema")',
        registration: str | None = None,
    ) -> None:
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        method = target.stem
        url = "/" + "/".join(Path(path).parts[:-1])
        target.write_text(
            "from apitest.support import Operation\n"
            f"def run(context, checks):\n    {body}\n"
            + (registration or f"OPERATION = Operation({method!r}, {url!r}, run)\n"),
        )

    def test_discovery_is_stable(self) -> None:
        self.case("api/z/POST.py")
        self.case("api/a/GET.py")
        self.assertEqual(
            [(row.method, row.path) for row in discover(self.root)],
            [("GET", "/api/a"), ("POST", "/api/z")],
        )

    def test_rejects_malformed_and_mismatched_registration(self) -> None:
        for path, registration in [
            ("api/a/post.py", None),
            ("api/a/GET.py", "OPERATION = 1\n"),
            ("api/a/POST.py", 'OPERATION = Operation("GET", "/api/a", run)\n'),
        ]:
            with self.subTest(path=path):
                self.case(path, registration=registration)
                with self.assertRaises(DiscoveryError):
                    discover(self.root)
                (self.root / path).unlink()

    def test_rejects_duplicate_parameterized_operations(self) -> None:
        self.case("api/a/{id}/GET.py")
        self.case("api/a/{other_id}/GET.py")
        with self.assertRaisesRegex(DiscoveryError, "duplicate_operation"):
            discover(self.root)

    def test_suite_continues_after_failure_and_crash_without_content(self) -> None:
        secret = "Bearer secret_token password=secret postgres://secret private prompt"
        self.case("api/a/GET.py", 'checks.require(False, "response.shape")')
        self.case("api/b/GET.py", f"raise RuntimeError({secret!r})")
        self.case("api/c/GET.py", f"checks.require(False, {secret!r})")
        self.case("api/d/GET.py")
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(run(self.root, self.report), 1)
        document = self.report.read_text()
        self.assertIn("1/4 passed", document)
        self.assertIn("case_crashed", document)
        self.assertIn("response.shape", document)
        self.assertIn("assertion_failed", document)
        for part in ("secret_token", "postgres://", "private prompt", "password="):
            self.assertNotIn(part, document + stdout.getvalue())

    def test_prints_system_exit_and_token_shaped_labels_are_redacted(self) -> None:
        self.case("api/a/GET.py", 'print("PRIVATE_BODY"); raise SystemExit("TOKEN")')
        self.case(
            "api/b/GET.py",
            'checks.require(False, "abcdefghijklmnopqrstuvxyz")',
            'print("IMPORT_SECRET")\nOPERATION = Operation("GET", "/api/b", run)\n',
        )
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            self.assertEqual(run(self.root, self.report), 1)
        text = output.getvalue() + self.report.read_text()
        for secret in ("PRIVATE_BODY", "TOKEN", "IMPORT_SECRET", "abcdefghijklmnopqrstuvxyz"):
            self.assertNotIn(secret, text)

    def test_passing_and_empty_suites(self) -> None:
        self.assertEqual(run(self.root, self.report), 1)
        self.assertIn("empty_suite", self.report.read_text())
        self.case("api/a/GET.py")
        self.assertEqual(run(self.root, self.report), 0)
        self.assertIn("1/1 passed", self.report.read_text())
        self.assertIn("duration", self.report.read_text())

    def test_discovery_crash_has_safe_report(self) -> None:
        self.case("api/a/GET.py", registration='raise RuntimeError("SECRET")')
        self.assertEqual(run(self.root, self.report), 1)
        self.assertNotIn("SECRET", self.report.read_text())

    def test_html_is_escaped_and_offline(self) -> None:
        write_report([Result("GET", "/<script>", "failed", 0.125, ("<img src=x>",))], self.report)
        document = self.report.read_text()
        self.assertIn("&lt;script&gt;", document)
        self.assertNotIn("<img", document)
        self.assertNotIn("<script", document)
        self.assertIn("default-src 'none'", document)

    def test_bounded_details(self) -> None:
        self.case("api/a/GET.py", '[checks.require(True, "safe") for _ in range(1000)]')
        self.assertEqual(run(self.root, self.report), 0)
        self.assertEqual(self.report.read_text().count("<td>safe</td>"), 1)

    def test_literal_extension_paths_and_exact_selection(self) -> None:
        self.case("api/openapi.json/GET.py")
        self.case("api/other/GET.py", 'checks.require(False, "response.shape")')
        self.assertEqual(len(discover(self.root)), 2)
        self.assertEqual(run(self.root, self.report, operation_filter="GET /api/openapi.json"), 0)
        self.assertIn("1/1 passed", self.report.read_text())
        self.assertEqual(run(self.root, self.report, operation_filter="GET /api/missing"), 1)
        self.assertIn("empty_suite", self.report.read_text())

    def test_late_assertions_survive_repetition(self) -> None:
        self.case(
            "api/a/GET.py",
            '[checks.require(True, "response.schema") for _ in range(200)]; '
            'checks.require(True, "database.messages")',
        )
        self.assertEqual(run(self.root, self.report), 0)
        self.assertIn("database.messages", self.report.read_text())


if __name__ == "__main__":
    unittest.main()
