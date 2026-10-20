"""Behavioral checks for policy, triage, evidence integrity, and stage handoffs."""

import datetime as dt
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SKILL = Path(__file__).resolve().parents[1] / "skills" / "java-renew"
SCRIPT = SKILL / "scripts" / "modernize.py"
spec = importlib.util.spec_from_file_location("modernize", SCRIPT)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

POM = '''<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <parent><groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-parent</artifactId><version>2.7.18</version></parent>
  <groupId>example</groupId><artifactId>legacy</artifactId><version>1</version>
  <properties><java.version>1.8</java.version><private.token>DO_NOT_PRINT</private.token></properties>
  <modules><module>service</module></modules>
  <dependencies><dependency><groupId>org.projectlombok</groupId>
    <artifactId>lombok</artifactId><version>${lombok.version}</version></dependency></dependencies>
</project>'''


class ProjectCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="java-renew-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.write("pom.xml", POM)
        self.write("service/src/main/java/Example.java", "class Example { }\n")
        self.policy = m.resolve_policy(self.root, [])

    def write(self, path, content):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return target

    def write_json(self, path, value):
        return self.write(path, json.dumps(value))

    def snapshot(self):
        return m.inventory(self.root, self.policy)

    def cli(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *args, "--root", str(self.root)],
                              text=True, capture_output=True, timeout=15)

    def passing_evidence(self):
        artifact = self.write(".java-modernize/test-results.log", "SYNTHETIC UNIT TEST EVIDENCE\n")
        evidence = m.evidence_template(self.snapshot(), self.policy)
        for check in evidence["checks"].values():
            check.update(status="passed", command="synthetic fixture command; not a Java migration",
                         summary="Synthetic fixture verifies evidence integrity only.",
                         artifacts=[{"path": ".java-modernize/test-results.log", "sha256": m.file_digest(artifact)}])
        for review in evidence["remediation"]["reviews"].values():
            review.update(status="complete", checked_on=dt.datetime.now(dt.timezone.utc).date().isoformat(),
                          summary="Synthetic complete review; tests gate consistency only.",
                          coverage={scope: "complete" for scope in m.REMEDIATION_SCOPES},
                          artifacts=[{"path": ".java-modernize/test-results.log", "sha256": m.file_digest(artifact)}])
        return evidence


class PolicyTests(ProjectCase):
    def test_remediation_defaults_and_explicit_report_only_overrides(self):
        self.assertEqual(self.policy["framework_policy"], "current-supported")
        self.assertEqual(self.policy["remediation"], {"eol": "replace", "vulnerabilities": "fix",
                         "allow_major_upgrades": True, "max_review_age_days": 1})
        override = self.write_json(".java-modernize/override.json", {
            "remediation": {"vulnerabilities": "report", "allow_major_upgrades": False}})
        policy = m.resolve_policy(self.root, [override])
        self.assertEqual(policy["remediation"]["vulnerabilities"], "report")
        self.assertEqual(policy["remediation"]["eol"], "replace")
        self.assertFalse(policy["remediation"]["allow_major_upgrades"])
        for layer in ({"remediation": {"eol": "ignore"}}, {"remediation": {"unknown": True}},
                      {"remediation": {"max_review_age_days": -1}},
                      {"remediation": {"max_review_age_days": True}}):
            with self.subTest(layer=layer), self.assertRaises(ValueError):
                m.resolve_policy(self.root, [self.write_json(".java-modernize/bad.json", layer)])

    def test_central_targets_extend_and_override_without_new_schema_fields(self):
        template = m.load_json(SKILL / "assets/project-policy.example.json")
        template["resource_targets"] = {
            "custom_compiler": {"kind": "jdk", "selector": "compiler Temurin", "version": "21.0.12.1+1"},
            "build_launcher": {"kind": "tool", "selector": "Maven Wrapper", "version": "3.9.16"},
            "custom_plugin": {"kind": "gradle-plugin", "selector": "example.plugin", "version": "1.2.3"},
            "runtime": {"kind": "image", "selector": "Dockerfile final FROM", "version": "example/image@sha256:" + "a" * 64}}
        self.write_json(".java-modernize.json", template)
        layer = self.write_json(".java-modernize/override.json", {
            "target_java": 21, "source_release": 17,
            "resource_targets": {"build_launcher": {"version": "3.9.17"}}})
        policy = m.resolve_policy(self.root, [layer])
        self.assertEqual((policy["target_java"], policy["source_release"]), (21, 17))
        self.assertEqual(policy["resource_targets"]["build_launcher"],
                         {"kind": "tool", "selector": "Maven Wrapper", "version": "3.9.17"})
        self.assertEqual(policy["resource_targets"]["custom_plugin"], template["resource_targets"]["custom_plugin"])

    def test_resource_targets_reject_incomplete_and_moving_versions(self):
        for kind, version in (("tool", "LATEST"), ("tool", "1.+"), ("tool", "[1,2)"),
                              ("tool", "1.0-SNAPSHOT"), ("image", "example/image:latest"),
                              ("image", "example/image@sha256:bad")):
            target = {"kind": kind, "selector": "explicit owner", "version": version}
            layer = self.write_json(".java-modernize/bad.json", {"resource_targets": {"custom": target}})
            with self.subTest(target=target), self.assertRaises(ValueError):
                m.resolve_policy(self.root, [layer])
        layer = self.write_json(".java-modernize/bad.json", {"resource_targets": {"custom": {"version": "1.0"}}})
        with self.assertRaisesRegex(ValueError, "kind, selector and version"):
            m.resolve_policy(self.root, [layer])

    def test_layer_order_recursive_maps_and_replaced_arrays(self):
        self.write_json(".java-modernize.json", {"source_release": 17,
            "dependency_pins": {"g:a": "1.0"}, "scope": {"exclude": ["old/**"]}})
        first = self.write_json(".java-modernize/org.json", {"source_release": 21,
            "dependency_pins": {"g:b": "2.0"}, "scope": {"exclude": ["other/**"]}})
        second = self.write_json(".java-modernize/run.json", {"source_release": 17,
            "dependency_pins": {"g:a": "1.1"}})
        policy = m.resolve_policy(self.root, [first, second])
        self.assertEqual(policy["source_release"], 17)
        self.assertEqual(policy["dependency_pins"], {"g:a": "1.1", "g:b": "2.0"})
        self.assertEqual(policy["scope"]["exclude"], ["other/**"])
        self.assertEqual(policy["target_java"], 25)

    def test_invalid_values_and_typos_fail_before_use(self):
        bad_layers = [{"target_jvaa": 25}, {"target_java": True}, {"target_java": 26},
                      {"target_java": 17}, {"scope": {"max_files": 0}},
                      {"scope": {"unknown": []}}, {"scope": {"include": []}},
                      {"scope": {"exclude_dirs": ["a/b"]}}, {"required_gates": []},
                      {"required_gates": ["unit", "unit"]}, {"source_release": None},
                      {"dependency_pins": {"not-a-coordinate": "1.0"}},
                      {"dependency_pins": {"g:a": "LATEST"}},
                      {"dependency_pins": {"g:a": "1.0-SNAPSHOT"}},
                      {"allow_preview": True, "source_release": 17},
                      {"waivers": [{"gate": "unit"}]}]
        for layer in bad_layers:
            with self.subTest(layer=layer):
                override = self.write_json(".java-modernize/override.json", layer)
                with self.assertRaises(ValueError):
                    m.resolve_policy(self.root, [override])

    def test_duplicate_keys_and_non_finite_numbers_rejected(self):
        for text in ['{"target_java":25,"target_java":21}', '{"baseline_java":NaN}', '{"x":Infinity}']:
            with self.subTest(text=text):
                path = self.write(".java-modernize/bad.json", text)
                with self.assertRaises(ValueError):
                    m.load_json(path)

    def test_valid_older_bytecode_baseline(self):
        layer = self.write_json(".java-modernize/library.json", {"source_release": 8})
        self.assertEqual(m.resolve_policy(self.root, [layer])["source_release"], 8)

    def test_waiver_schema_dates_and_duplicate_gate_validation(self):
        waiver = {"gate": "unit", "owner": "team", "reason": "test", "ticket": "T-1", "expires": "2099-01-01"}
        for waivers in [[dict(waiver, expires="2099-02-30")], [dict(waiver, gate="unknown")],
                        [waiver, waiver], [dict(waiver, owner=" ")]]:
            layer = self.write_json(".java-modernize/waiver.json", {"waivers": waivers})
            with self.subTest(waivers=waivers), self.assertRaises(ValueError):
                m.resolve_policy(self.root, [layer])


class InventoryTests(ProjectCase):
    def test_wrappers_locks_and_opaque_resources_invalidate_evidence(self):
        inputs = {
            "mvnw": b"#!/bin/sh\nexec mvn verify\n",
            "gradlew": b"#!/bin/sh\nexec gradle test\n",
            "gradle.lockfile": b"example:library:1.0=runtimeClasspath\n",
            "src/main/resources/META-INF/services/example.Provider": b"example.ProviderImpl\n",
            "src/main/resources/db/migration/V1__schema.sql": b"CREATE TABLE orders (id INT);\n",
            "gradle/wrapper/gradle-wrapper.jar": b"PK\x00\xffopaque wrapper bytes",
        }
        for relative, data in inputs.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        self.assertTrue(self.snapshot()["scan_complete"])
        for relative, data in inputs.items():
            with self.subTest(path=relative):
                evidence = self.passing_evidence()
                (self.root / relative).write_bytes(data + b"changed")
                result = m.check_evidence(self.root, self.policy, evidence)
                self.assertTrue(any("inventory changed" in error for error in result["errors"]))

    @unittest.skipUnless(os.name == "posix", "POSIX executable permissions")
    def test_launcher_permission_changes_invalidate_evidence(self):
        launcher = self.write("mvnw", "#!/bin/sh\n")
        launcher.chmod(0o644)
        evidence = self.passing_evidence()
        launcher.chmod(0o755)
        self.assertEqual(m.check_evidence(self.root, self.policy, evidence)["status"], "blocked")

    def test_unknown_symlinks_and_oversized_resources_mark_incomplete(self):
        target = self.write(".java-modernize/private", "private data")
        (self.root / "linked-resource").symlink_to(target)
        self.assertFalse(self.snapshot()["scan_complete"])
        (self.root / "linked-resource").unlink()
        self.policy["scope"]["max_file_bytes"] = 1024
        self.write("src/main/resources/opaque.bin", "x" * 1025)
        self.assertFalse(self.snapshot()["scan_complete"])

    @unittest.skipUnless(hasattr(os, "O_NOFOLLOW"), "requires no-follow file opens")
    def test_file_replaced_by_symlink_during_open_is_rejected(self):
        target = self.write(".java-modernize/private", "never read private data")
        candidate = self.write("Race.java", "class Race {}")
        real_open = os.open

        def replace_then_open(path, flags):
            if Path(path) == candidate:
                candidate.unlink()
                candidate.symlink_to(target)
            return real_open(path, flags)

        with mock.patch.object(m.os, "open", side_effect=replace_then_open):
            snapshot = self.snapshot()
        self.assertFalse(snapshot["scan_complete"])
        self.assertNotIn("never read private data", json.dumps(snapshot))
        self.assertNotIn("Race.java", {item["path"] for item in snapshot["files"]})

    def test_declared_metadata_and_deterministic_fingerprint(self):
        first, second = self.snapshot(), self.snapshot()
        self.assertEqual(first, second)
        pom = next(item for item in first["files"] if item["path"] == "pom.xml")
        self.assertEqual(pom["java_properties"], {"java.version": "1.8"})
        self.assertEqual(pom["modules"], ["service"])
        self.assertEqual(pom["declared_coordinates"][1]["version"], "${lombok.version}")
        self.assertNotIn("DO_NOT_PRINT", json.dumps(first))
        self.assertTrue(first["scan_complete"])
        self.write("service/src/main/java/Example.java", "class Changed {}")
        self.assertNotEqual(first["inventory_sha256"], self.snapshot()["inventory_sha256"])

    def test_signals_include_line_numbers_without_source_snippets(self):
        self.write("Risk.java", "// private text\nimport sun.misc.Unsafe;\nclass Risk { }\n")
        finding = next(item for item in self.snapshot()["findings"] if item["rule"] == "internal-api")
        self.assertEqual(finding["line"], 2)
        self.assertNotIn("private text", json.dumps(finding))

    def test_javase_namespaces_are_not_jakarta_candidates(self):
        self.write("Standard.java", "import javax.sql.DataSource; import javax.crypto.Cipher; import javax.xml.parsers.DocumentBuilder; import javax.annotation.processing.Processor; import javax.transaction.xa.XAResource;")
        findings = [item for item in self.snapshot()["findings"] if item["path"] == "Standard.java"]
        self.assertFalse(any(item["rule"] in {"removed-javaee", "jakarta-boundary"} for item in findings))

    def test_gradle_catalog_and_pipeline_are_inventoried_without_evaluation(self):
        self.write("build.gradle.kts", 'plugins { java }; dependencies { testImplementation("org.mockito:mockito-inline:5.2.0") }')
        self.write("gradle/libs.versions.toml", '[versions]\njava = "8"\n')
        self.write(".github/workflows/build.yml", 'java-version: "8"\n')
        self.write("Dockerfile", "FROM eclipse-temurin:8\n")
        self.write(".mvn/jvm.config", "-XX:+UseConcMarkSweepGC\n")
        snapshot = self.snapshot()
        paths = {item["path"] for item in snapshot["files"]}
        self.assertTrue({"build.gradle.kts", "gradle/libs.versions.toml", ".github/workflows/build.yml", "Dockerfile", ".mvn/jvm.config"} <= paths)
        self.assertTrue(any(item["rule"] == "obsolete-jvm-flags" for item in snapshot["findings"]))

    def test_reports_and_build_output_do_not_change_snapshot(self):
        before = self.snapshot()["inventory_sha256"]
        self.write(".java-modernize/inventory.json", '{"report":true}')
        self.write("target/Generated.java", "import sun.misc.Unsafe;")
        self.write(".aws/secret.json", '{"secret":"never report"}')
        self.assertEqual(before, self.snapshot()["inventory_sha256"])

    def test_scope_patterns_exclude_root_and_nested_files(self):
        self.write("Risk.java", "import sun.misc.Unsafe;")
        self.write("other/Risk.java", "import sun.misc.Unsafe;")
        self.policy["scope"]["include"] = ["**/*.java"]
        self.policy["scope"]["exclude"] = ["other/**"]
        paths = {item["path"] for item in self.snapshot()["files"]}
        self.assertIn("Risk.java", paths)
        self.assertNotIn("other/Risk.java", paths)
        self.assertNotIn("pom.xml", paths)

    def test_limits_encoding_and_invalid_xml_mark_incomplete(self):
        for content in ["<project>", '<!DOCTYPE x [<!ENTITY e "unsafe">]><project>&e;</project>']:
            with self.subTest(content=content):
                self.write("pom.xml", content)
                self.assertFalse(self.snapshot()["scan_complete"])
        self.write("pom.xml", POM)
        self.write("large.java", "x" * 2048)
        self.policy["scope"]["max_file_bytes"] = 1024
        self.assertFalse(self.snapshot()["scan_complete"])
        self.policy["scope"]["max_file_bytes"] = 1048576
        (self.root / "large.java").write_bytes(b"\xff\xfeBAD")
        self.assertFalse(self.snapshot()["scan_complete"])
        self.policy["scope"]["max_files"] = 1
        self.assertFalse(self.snapshot()["scan_complete"])

    def test_symlinks_are_not_followed(self):
        target = self.write(".java-modernize/private.java", "SECRET internal source")
        try:
            (self.root / "Linked.java").symlink_to(target)
            (self.root / "linked-dir").symlink_to(target.parent, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlink privileges unavailable")
        snapshot = self.snapshot()
        self.assertFalse(snapshot["scan_complete"])
        self.assertNotIn("SECRET", json.dumps(snapshot))
        self.assertFalse(any(item["path"].startswith("linked") for item in snapshot["files"]))


class EvidenceTests(ProjectCase):
    def test_opaque_resources_alone_do_not_establish_usable_project_inputs(self):
        self.write("README.md", "Project documentation only")
        self.policy["scope"]["include"] = ["README.md"]
        snapshot = self.snapshot()
        self.assertTrue(snapshot["scan_complete"])
        self.assertEqual(len(snapshot["files"]), 1)
        result = m.check_evidence(self.root, self.policy, self.passing_evidence())
        self.assertTrue(any("no recognized" in error for error in result["errors"]))
        handoff = m.handoff_template("execute", snapshot, self.policy)
        handoff["status"] = "complete"
        report, code = m.render_report(self.root, self.policy, handoff)
        self.assertEqual(code, 1)
        self.assertIn("Status: **blocked**", report)

    def finding(self, kind="vulnerability", status="open"):
        return {"id": "SYNTHETIC-ADVISORY", "kind": kind, "component": "example:legacy", "version": "1.0",
                "status": status, "replacement": "", "summary": "Synthetic finding, not a real advisory.", "artifacts": []}

    def test_open_eol_and_advisories_block_declared_passes_even_in_report_mode(self):
        self.policy["remediation"].update(eol="report", vulnerabilities="report")
        for kind, gate in (("eol", "dependencies"), ("vulnerability", "security")):
            evidence = self.passing_evidence()
            evidence["remediation"]["findings"].append(self.finding(kind))
            result = m.check_evidence(self.root, self.policy, evidence)
            with self.subTest(kind=kind):
                self.assertEqual(result["status"], "blocked")
                self.assertTrue(any(item.startswith(gate + ": remediation open") for item in result["errors"]))

    def test_remediation_coverage_and_dates_cannot_be_replaced_by_a_clean_claim(self):
        today = dt.datetime.now(dt.timezone.utc).date()
        mutations = [lambda r: r.update(status="not_run"), lambda r: r["coverage"].pop("build"),
                     lambda r: r["coverage"].update(processors="incomplete"),
                     lambda r: r.update(checked_on=(today - dt.timedelta(days=2)).isoformat()),
                     lambda r: r.update(checked_on=(today + dt.timedelta(days=1)).isoformat()),
                     lambda r: r.update(checked_on="not-a-date"), lambda r: r.update(artifacts=[])]
        for name in ("support", "vulnerabilities"):
            for mutation in mutations:
                evidence = self.passing_evidence()
                mutation(evidence["remediation"]["reviews"][name])
                with self.subTest(name=name, mutation=mutation):
                    self.assertEqual(m.check_evidence(self.root, self.policy, evidence)["status"], "blocked")
        evidence = self.passing_evidence()
        evidence.pop("remediation")
        self.assertEqual(m.check_evidence(self.root, self.policy, evidence)["status"], "blocked")

    def test_fixed_and_not_affected_dispositions_require_retained_proof(self):
        for status in ("fixed", "not_affected"):
            evidence = self.passing_evidence()
            finding = self.finding(status=status)
            evidence["remediation"]["findings"].append(finding)
            self.assertEqual(m.check_evidence(self.root, self.policy, evidence)["status"], "blocked")
            finding["artifacts"] = [dict(item) for item in evidence["checks"]["security"]["artifacts"]]
            if status == "fixed":
                self.assertEqual(m.check_evidence(self.root, self.policy, evidence)["status"], "blocked")
                finding["replacement"] = "example:replacement@2.0"
            self.assertEqual(m.check_evidence(self.root, self.policy, evidence)["status"], "passed")
            finding["artifacts"][0]["sha256"] = "0" * 64
            self.assertEqual(m.check_evidence(self.root, self.policy, evidence)["status"], "blocked")

    def test_remediation_artifacts_reject_traversal_and_duplicate_dispositions(self):
        evidence = self.passing_evidence()
        finding = self.finding(status="not_affected")
        finding["artifacts"] = [dict(item) for item in evidence["checks"]["security"]["artifacts"]]
        evidence["remediation"]["findings"] = [finding, dict(finding)]
        self.assertTrue(any("duplicate finding" in item for item in m.check_evidence(self.root, self.policy, evidence)["errors"]))
        evidence["remediation"]["findings"] = [finding]
        finding["artifacts"][0]["path"] = "../outside.log"
        self.assertTrue(any("relative and contained" in item for item in m.check_evidence(self.root, self.policy, evidence)["errors"]))

    def test_explicit_waiver_remains_distinct_from_fixed_and_does_not_cover_other_gate(self):
        self.policy["waivers"] = [{"gate": "dependencies", "owner": "test-owner", "reason": "synthetic exception",
                                  "ticket": "TEST-1", "expires": dt.datetime.now(dt.timezone.utc).date().isoformat()}]
        evidence = self.passing_evidence()
        evidence["checks"]["dependencies"]["status"] = "waived"
        evidence["remediation"]["findings"] = [self.finding("eol")]
        self.assertEqual(m.check_evidence(self.root, self.policy, evidence)["status"], "passed_with_waivers")
        report, _ = m.render_report(self.root, self.policy, m.handoff_template("summary", self.snapshot(), self.policy), evidence)
        self.assertIn("0 fixed; 1 open", report)
        evidence["remediation"]["findings"].append(self.finding("vulnerability"))
        self.assertEqual(m.check_evidence(self.root, self.policy, evidence)["status"], "blocked")

    def test_real_local_artifact_hashes_and_required_checks_pass(self):
        evidence = self.passing_evidence()
        result = m.check_evidence(self.root, self.policy, evidence)
        self.assertEqual(result["status"], "passed", result)

    def test_template_is_not_a_pass(self):
        result = m.check_evidence(self.root, self.policy, m.evidence_template(self.snapshot(), self.policy))
        self.assertEqual(len(result["errors"]), len(self.policy["required_gates"]))

    def test_source_policy_and_artifact_changes_invalidate_evidence(self):
        evidence = self.passing_evidence()
        self.write("service/src/main/java/Example.java", "class Changed {}")
        self.assertTrue(any("inventory changed" in item for item in m.check_evidence(self.root, self.policy, evidence)["errors"]))
        evidence = self.passing_evidence()
        self.policy["source_release"] = 17
        self.assertTrue(any("policy changed" in item for item in m.check_evidence(self.root, self.policy, evidence)["errors"]))
        evidence = self.passing_evidence()
        self.write(".java-modernize/test-results.log", "altered")
        self.assertTrue(any("digest mismatch" in item for item in m.check_evidence(self.root, self.policy, evidence)["errors"]))

    def test_missing_empty_and_traversal_artifacts_block(self):
        for path in [".java-modernize/missing.log", "../outside.log", str(self.root / "absolute.log"), ""]:
            evidence = self.passing_evidence()
            evidence["checks"]["unit"]["artifacts"][0]["path"] = path
            with self.subTest(path=path):
                if not path:
                    with self.assertRaises(ValueError):
                        m.check_evidence(self.root, self.policy, evidence)
                else:
                    self.assertEqual(m.check_evidence(self.root, self.policy, evidence)["status"], "blocked")
        evidence = self.passing_evidence()
        self.write(".java-modernize/test-results.log", "")
        self.assertEqual(m.check_evidence(self.root, self.policy, evidence)["status"], "blocked")

    def test_wrong_jdk_missing_check_failed_and_fake_pass_block(self):
        for mutation in [lambda e: e["checks"].pop("unit"),
                         lambda e: e["checks"]["unit"].update(status="failed"),
                         lambda e: e["checks"]["unit"].update(java_major=8),
                         lambda e: e["checks"]["unit"].update(command=""),
                         lambda e: e["checks"]["unit"].update(artifacts=[]),
                         lambda e: e.update(target_java=21)]:
            evidence = self.passing_evidence()
            mutation(evidence)
            self.assertEqual(m.check_evidence(self.root, self.policy, evidence)["status"], "blocked")

    def test_symlink_artifact_and_symlink_parent_block(self):
        target = self.write(".java-modernize/real/results.log", "synthetic data")
        try:
            (self.root / ".java-modernize/linked.log").symlink_to(target)
            (self.root / ".java-modernize/linked-dir").symlink_to(target.parent, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlink privileges unavailable")
        for path in [".java-modernize/linked.log", ".java-modernize/linked-dir/results.log"]:
            evidence = self.passing_evidence()
            evidence["checks"]["unit"]["artifacts"] = [{"path": path, "sha256": m.file_digest(target)}]
            self.assertEqual(m.check_evidence(self.root, self.policy, evidence)["status"], "blocked")

    def test_owned_waivers_expire_and_do_not_override_failures(self):
        today = dt.datetime.now(dt.timezone.utc).date()
        self.policy["waivers"] = [{"gate": "performance", "owner": "team", "reason": "fixture",
                                  "ticket": "TEST-1", "expires": today.isoformat()}]
        evidence = self.passing_evidence()
        evidence["checks"]["performance"]["status"] = "waived"
        self.assertEqual(m.check_evidence(self.root, self.policy, evidence)["status"], "passed_with_waivers")
        evidence["checks"]["performance"]["status"] = "failed"
        self.assertEqual(m.check_evidence(self.root, self.policy, evidence)["status"], "blocked")
        self.policy["waivers"][0]["expires"] = (today - dt.timedelta(days=1)).isoformat()
        evidence = self.passing_evidence()
        evidence["checks"]["performance"]["status"] = "waived"
        self.assertEqual(m.check_evidence(self.root, self.policy, evidence)["status"], "blocked")

    def test_waiver_without_policy_and_empty_inventory_block(self):
        evidence = self.passing_evidence()
        evidence["checks"]["unit"]["status"] = "waived"
        self.assertEqual(m.check_evidence(self.root, self.policy, evidence)["status"], "blocked")
        self.policy["scope"]["include"] = ["nonexistent/**"]
        self.assertEqual(m.check_evidence(self.root, self.policy, self.passing_evidence())["status"], "blocked")


class ReportAndCliTests(ProjectCase):
    def test_completion_cannot_hide_blockers_or_empty_inventory(self):
        for stage in m.STAGES:
            with self.subTest(stage=stage):
                handoff = m.handoff_template(stage, self.snapshot(), self.policy)
                handoff.update(status="complete", blockers=["Required environment unavailable"])
                report, code = m.render_report(self.root, self.policy, handoff, self.passing_evidence())
                self.assertEqual(code, 1)
                self.assertIn("Status: **blocked**", report)
        self.policy["scope"]["include"] = ["missing/**"]
        handoff = m.handoff_template("execute", self.snapshot(), self.policy)
        handoff["status"] = "complete"
        report, code = m.render_report(self.root, self.policy, handoff)
        self.assertEqual(code, 1)
        self.assertIn("Status: **blocked**", report)

    def test_json_inputs_reject_special_files_symlinks_and_oversized_data(self):
        target = self.write_json(".java-modernize/policy.json", {})
        link = self.root / "linked.json"
        link.symlink_to(target)
        with self.assertRaises((OSError, ValueError)):
            m.load_json(link)
        oversized = self.write(".java-modernize/oversized.json", " " * (16 * 1024 * 1024) + "{}")
        with self.assertRaises(ValueError):
            m.load_json(oversized)
        (self.root / ".java-modernize.json").symlink_to(self.root / "missing-policy.json")
        result = self.cli("config")
        self.assertEqual(result.returncode, 2, "A broken project policy link must not fall back to defaults")
        (self.root / ".java-modernize.json").unlink()
        if hasattr(os, "mkfifo"):
            fifo = self.root / "fifo.json"
            os.mkfifo(fifo)
            result = self.cli("config", "--override", str(fifo))
            self.assertEqual(result.returncode, 2)

    def test_each_stage_has_a_continuation_handoff(self):
        for stage in m.STAGES:
            handoff = m.handoff_template(stage, self.snapshot(), self.policy)
            report, code = m.render_report(self.root, self.policy, handoff)
            self.assertEqual(code, 0)
            self.assertIn(f"# Java Renew — {stage}", report)
            self.assertIn("## Next step", report)
            self.assertIn("## Handoff integrity", report)
        execution = m.handoff_template("execute", self.snapshot(), self.policy)
        self.assertIn("validate", execution["next_steps"][0])

    def test_validation_requires_evidence_and_reports_blockers(self):
        handoff = m.handoff_template("validate", self.snapshot(), self.policy)
        handoff["status"] = "complete"
        with self.assertRaises(ValueError):
            m.render_report(self.root, self.policy, handoff)
        evidence = self.passing_evidence()
        evidence["checks"]["unit"]["status"] = "failed"
        report, code = m.render_report(self.root, self.policy, handoff, evidence)
        self.assertEqual(code, 1)
        self.assertIn("Status: **blocked**", report)
        self.assertIn("unit: failed", report)
        report, code = m.render_report(self.root, self.policy, handoff, self.passing_evidence())
        self.assertEqual(code, 0)
        self.assertIn("Result: **passed**", report)

    def test_completed_execution_does_not_claim_validated_readiness(self):
        handoff = m.handoff_template("execute", self.snapshot(), self.policy)
        handoff["status"] = "complete"
        report, code = m.render_report(self.root, self.policy, handoff)
        self.assertEqual(code, 0)
        self.assertIn("Implementation status only", report)
        self.assertIn("No claim of verified execution", report)

    def test_stale_handoff_and_unsafe_table_content(self):
        handoff = m.handoff_template("plan", self.snapshot(), self.policy)
        handoff["versions"] = [{"component": "API|test", "before": "8", "after": "25",
                                "source": "primary\nsource", "checked_on": "2026-10-19"}]
        report, _ = m.render_report(self.root, self.policy, handoff)
        self.assertIn(r"API\|test", report)
        self.assertIn("primary source", report)
        self.write("New.java", "class New {}")
        with self.assertRaises(ValueError):
            m.render_report(self.root, self.policy, handoff)

    def test_cli_commands_formats_and_exit_codes(self):
        for command in ["config", "inventory", "evidence-template"]:
            result = self.cli(command)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIsInstance(json.loads(result.stdout), dict)
        result = self.cli("report-template", "--stage", "assess")
        handoff = self.write_json(".java-modernize/01-assessment.json", json.loads(result.stdout))
        report = self.cli("report", "--handoff", str(handoff))
        self.assertEqual(report.returncode, 0, report.stderr)
        self.assertTrue(report.stdout.startswith("# Java Renew"))
        evidence = self.write_json(".java-modernize/evidence.json", m.evidence_template(self.snapshot(), self.policy))
        result = self.cli("gate", "--evidence", str(evidence))
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["status"], "blocked")
        for args in [("gate",), ("report",), ("report-template",)]:
            result = self.cli(*args)
            self.assertEqual(result.returncode, 2)
            self.assertIn("error", json.loads(result.stderr))

    def test_report_outputs_do_not_stale_the_next_stage(self):
        for stage in m.STAGES:
            handoff = m.handoff_template(stage, self.snapshot(), self.policy)
            path = self.write_json(f".java-modernize/{m.STAGES[stage]}.json", handoff)
            report, _ = m.render_report(self.root, self.policy, m.load_json(path))
            self.write(f".java-modernize/{m.STAGES[stage]}.md", report)
            self.assertEqual(handoff["inventory_sha256"], self.snapshot()["inventory_sha256"])


class PackageTests(unittest.TestCase):
    def test_open_skill_frontmatter_and_portable_resources(self):
        import re
        text = (SKILL / "SKILL.md").read_text()
        frontmatter = text.split("---", 2)[1]
        name = re.search(r"^name: (.+)$", frontmatter, re.M).group(1)
        description = re.search(r"^description: (.+)$", frontmatter, re.M).group(1)
        self.assertEqual(name, SKILL.name)
        self.assertRegex(name, r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
        self.assertLessEqual(len(name), 64)
        self.assertTrue(1 <= len(description) <= 1024)
        self.assertTrue((SKILL / "LICENSE").is_file())
        self.assertIn("Apache License", (SKILL / "LICENSE").read_text())

    def test_schema_defaults_and_internal_reference_integrity(self):
        defaults = m.load_json(SKILL / "assets/defaults.json")
        m.validate(defaults, m.load_json(SKILL / "assets/config.schema.json"))
        for path in [SKILL / "SKILL.md", *sorted((SKILL / "references").glob("*.md"))]:
            import re
            for target in re.findall(r"\]\(([^)]+)\)", path.read_text()):
                if "://" not in target and not target.startswith("#"):
                    # SKILL.md uses root-relative links; reference files use normal relative links.
                    self.assertTrue((path.parent / target.split("#")[0]).exists(), (path, target))
        self.assertLess(len((SKILL / "SKILL.md").read_text().splitlines()), 500)


if __name__ == "__main__":
    unittest.main()
