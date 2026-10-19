"""Check independent result grading and verified build-tool installation."""

import hashlib
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


checks = module("checks", "scripts/checks.py")
installer = module("installer", "docker/install_tools.py")


class CheckRunnerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="modernize-check-tests-")
        self.addCleanup(temporary.cleanup)
        self.work = Path(temporary.name)

    def test_grade_actual_test_reports_and_reject_zero_or_failed_tests(self):
        report = self.work / "tests.xml"
        report.write_text('<testsuite tests="3" failures="0" errors="0" skipped="1"/>')
        self.assertEqual(checks.test_counts([report]), {"tests": 3, "failures": 0, "errors": 0, "skipped": 1})
        for data in ['<testsuite tests="0"/>', '<testsuite tests="1" failures="1"/>', '<testsuite tests="1" errors="1"/>']:
            report.write_text(data)
            with self.subTest(data=data), self.assertRaises(ValueError):
                checks.test_counts([report])
        with self.assertRaises(ValueError):
            checks.test_counts([])

    def test_classfile_header_checks_reject_missing_or_nonclass_content(self):
        path = self.work / "Example.class"
        path.write_bytes(b"\xca\xfe\xba\xbe\x00\x00\x00\x41")
        self.assertEqual(checks.classfile_majors([path]), [65])
        path.write_bytes(b"not bytecode")
        with self.assertRaises(ValueError):
            checks.classfile_majors([path])
        with self.assertRaises(ValueError):
            checks.classfile_majors([])

    def test_command_failures_and_timeouts_are_preserved_in_reports(self):
        failure = checks.run_command("failure", [sys.executable, "-c", "raise SystemExit(3)"], self.work)
        self.assertEqual((failure["status"], failure["exit_code"]), ("failed", 3))
        timeout = checks.run_command("timeout", [sys.executable, "-c", "import time; time.sleep(5)"], self.work, timeout=0.05)
        self.assertEqual(timeout["exit_code"], 124)
        self.assertIn("Timed out", (self.work / timeout["log"]).read_text())
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(checks.write_report(self.work, [failure, timeout]), 1)
        self.assertEqual(json.loads((self.work / "results.json").read_text())["status"], "failed")

    def test_with_java_sets_the_selected_context_and_rejects_unknown_versions(self):
        result = subprocess.run(["sh", str(ROOT / "docker/with-java"), "17", sys.executable,
                                 "-c", "import os; print(os.environ['JAVA_HOME']); print(os.environ['MODERNIZE_JAVA_HOME'])"],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["/opt/jdks/17", "/opt/jdks/17"])
        result = subprocess.run(["sh", str(ROOT / "docker/with-java"), "12", "java", "-version"],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 2)

    def test_installation_rejects_hash_mismatch_and_zip_traversal(self):
        archive = self.work / "tool.zip"
        with zipfile.ZipFile(archive, "w") as stream:
            stream.writestr("gradle-test/bin/gradle", "#!/bin/sh\n")
        entry = {"url": archive.as_uri(), "sha256": "0" * 64}
        destination = self.work / "installed"
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            installer.install("gradle8", entry, destination)
        self.assertFalse(destination.exists())
        entry["sha256"] = hashlib.sha256(archive.read_bytes()).hexdigest()
        installer.install("gradle8", entry, destination)
        self.assertTrue((destination / "bin/gradle").stat().st_mode & 0o111)
        with zipfile.ZipFile(archive, "w") as stream:
            stream.writestr("../outside", "unsafe")
        entry["sha256"] = hashlib.sha256(archive.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError, "unsafe archive path"):
            installer.install("gradle8", entry, self.work / "invalid")
        self.assertFalse((self.work / "outside").exists())


if __name__ == "__main__":
    unittest.main()
