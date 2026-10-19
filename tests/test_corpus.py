"""Offline regression corpus; opt-in dependency-free Java compiler smoke checks."""

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "testdata"
SCENARIOS = DATA / "scenarios"
spec = importlib.util.spec_from_file_location("modernize_corpus", ROOT / "skills/modernize-java/scripts/modernize.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
CASES = m.load_json(DATA / "cases.json")["cases"]


class CorpusTests(unittest.TestCase):
    def workspace(self, case):
        temporary = tempfile.TemporaryDirectory(prefix=f"modernize-corpus-{case['id']}-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name) / "project"
        shutil.copytree(DATA / case["path"], root)
        policy = m.resolve_policy(root, [])
        policy["baseline_java"] = case["baseline_java"]
        return root, policy

    def test_fixture_files_match_local_checksum_manifest(self):
        manifest = m.load_json(DATA / "fixtures.sha256.json")
        self.assertEqual(manifest["schema_version"], 1)
        self.assertEqual(manifest["algorithm"], "sha256")
        actual = {path.relative_to(SCENARIOS).as_posix(): m.file_digest(path)
                  for path in SCENARIOS.rglob("*") if path.is_file()}
        self.assertEqual(actual, manifest["files"], "Fixture files changed; review the changes and update the local checksum manifest.")

    def test_every_scenario_has_a_case_contract(self):
        directories = {"scenarios/" + path.name for path in SCENARIOS.iterdir() if path.is_dir()}
        self.assertEqual(directories, {case["path"] for case in CASES})
        self.assertEqual(len(CASES), len({case["id"] for case in CASES}))
        for case in CASES:
            with self.subTest(case=case["id"]):
                path = Path(case["path"])
                self.assertFalse(path.is_absolute())
                self.assertNotIn("..", path.parts)
                self.assertTrue((DATA / path).is_dir())
                self.assertIn(case["baseline_java"], range(8, 26))
                self.assertGreaterEqual(len(case["acceptance"]), 3)
                for path in [*case["build_files"], *case["poms"], *(signal["path"] for signal in case["signals"])]:
                    self.assertTrue((DATA / case["path"] / path).is_file(), path)

    def test_all_projects_inventory_with_expected_descriptors_and_signals(self):
        for case in CASES:
            with self.subTest(case=case["id"]):
                root, policy = self.workspace(case)
                snapshot = m.inventory(root, policy)
                self.assertTrue(snapshot["scan_complete"], snapshot["warnings"])
                files = {item["path"]: item for item in snapshot["files"]}
                self.assertEqual(set(files), {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()})
                for path, kind in case["build_files"].items():
                    self.assertEqual(files[path]["kind"], kind)
                signals = {(item["path"], item["rule"]) for item in snapshot["findings"]}
                self.assertTrue({(item["path"], item["rule"]) for item in case["signals"]} <= signals, signals)

    def test_maven_version_ownership_and_expressions_remain_declared(self):
        for case in CASES:
            with self.subTest(case=case["id"]):
                root, policy = self.workspace(case)
                files = {item["path"]: item for item in m.inventory(root, policy)["files"]}
                for path, expected in case["poms"].items():
                    actual = files[path]
                    for key in ("java_properties", "modules"):
                        if key in expected:
                            self.assertEqual(actual[key], expected[key])
                    for coordinate in expected.get("coordinates", []):
                        self.assertTrue(any(all(item.get(key) == value for key, value in coordinate.items())
                                            for item in actual["declared_coordinates"]), (path, coordinate))

    def test_reports_and_evidence_templates_do_not_modify_fixture_inputs(self):
        for case in CASES:
            with self.subTest(case=case["id"]):
                root, policy = self.workspace(case)
                snapshot = m.inventory(root, policy)
                reports = root / ".java-modernize"
                reports.mkdir()
                for stage, filename in m.STAGES.items():
                    handoff = m.handoff_template(stage, snapshot, policy)
                    handoff["findings"] = case["acceptance"]
                    (reports / f"{filename}.json").write_text(json.dumps(handoff), encoding="utf-8")
                    report, code = m.render_report(root, policy, handoff)
                    self.assertEqual(code, 0)
                    self.assertIn("Status: **in_progress**", report)
                    (reports / f"{filename}.md").write_text(report, encoding="utf-8")
                evidence = m.evidence_template(snapshot, policy)
                self.assertTrue(all(check["status"] == "not_run" for check in evidence["checks"].values()))
                self.assertEqual(m.check_evidence(root, policy, evidence)["status"], "blocked")
                self.assertEqual(m.inventory(root, policy), snapshot)

    def test_changed_project_invalidates_prior_stage_for_every_case(self):
        for case in CASES:
            with self.subTest(case=case["id"]):
                root, policy = self.workspace(case)
                snapshot = m.inventory(root, policy)
                plan = m.handoff_template("plan", snapshot, policy)
                path = root / snapshot["files"][0]["path"]
                path.write_bytes(path.read_bytes() + b"\n")
                with self.assertRaisesRegex(ValueError, "stale handoff"):
                    m.render_report(root, policy, plan)

    def test_per_use_override_retains_library_release_without_rewriting_source(self):
        case = next(case for case in CASES if case["id"] == "source-recipe")
        root, _ = self.workspace(case)
        before = {path.relative_to(root).as_posix(): m.file_digest(path) for path in root.rglob("*") if path.is_file()}
        overrides = root / ".java-modernize/run-policy.json"
        overrides.parent.mkdir()
        overrides.write_text(json.dumps({"baseline_java": 17, "target_java": 25, "source_release": 17}), encoding="utf-8")
        policy = m.resolve_policy(root, [overrides])
        self.assertEqual((policy["source_release"], policy["target_java"]), (17, 25))
        self.assertEqual(before, {path: m.file_digest(root / path) for path in before})
        self.assertEqual(m.inventory(root, policy)["findings"], [])


@unittest.skipUnless(os.environ.get("MODERNIZE_JAVA_INTEGRATION") == "1",
                     "set MODERNIZE_JAVA_INTEGRATION=1 to compile dependency-free fixture sources")
class JavaCompilerSmokeTests(unittest.TestCase):
    def test_greeting_behavior_and_declared_bytecode_on_selected_jdk(self):
        java_home = os.environ.get("MODERNIZE_JAVA_HOME")
        suffix = ".exe" if os.name == "nt" else ""
        if java_home:
            java = str(Path(java_home) / "bin" / ("java" + suffix))
            javac = str(Path(java_home) / "bin" / ("javac" + suffix))
        else:
            java, javac = shutil.which("java"), shutil.which("javac")
        self.assertTrue(java and javac, "An integration run needs java and javac; configure MODERNIZE_JAVA_HOME.")
        versions = [subprocess.run([tool, "-version"], text=True, capture_output=True, check=True, timeout=15) for tool in (java, javac)]
        print("\nFixture compiler smoke uses:\n" + "".join(item.stdout + item.stderr for item in versions), flush=True)
        examples = [("java8", "Greeting.hello(\"Java\")", "Hello, Java", 8),
                    ("gradle-groovy", "Greeting.hello()", "hello", 8),
                    ("gradle-kotlin/app", "Greeting.hello()", "hello", 17),
                    ("source-recipe", "Greeting.hello(\"Java\")", "Hello, Java", 17)]
        for fixture, call, expected, release in examples:
            with self.subTest(fixture=fixture), tempfile.TemporaryDirectory(prefix="modernize-java-compile-") as directory:
                work = Path(directory)
                source = SCENARIOS / fixture / "src/main/java/example/Greeting.java"
                driver = work / "FixtureCheck.java"
                driver.write_text("import example.Greeting; public class FixtureCheck { public static void main(String[] args) { "
                                  f"if (!{json.dumps(expected)}.equals({call})) throw new AssertionError(\"Greeting contract changed\");"
                                  " } }", encoding="utf-8")
                classes = work / "classes"
                classes.mkdir()
                compiled = subprocess.run([javac, "--release", str(release), "-d", str(classes), str(source), str(driver)],
                                          text=True, capture_output=True, timeout=60)
                self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
                bytecode = (classes / "example/Greeting.class").read_bytes()
                self.assertEqual(int.from_bytes(bytecode[6:8], "big"), release + 44)
                ran = subprocess.run([java, "-cp", str(classes), "FixtureCheck"], text=True, capture_output=True, timeout=30)
                self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)


if __name__ == "__main__":
    unittest.main()
