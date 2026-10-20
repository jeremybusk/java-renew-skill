"""Exercise evaluation isolation, transport and independently graded outcomes."""

import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


evaluation = module("evaluate")
grader = module("evaluation_grade")


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.output = Path(temporary.name) / "run"

    def test_preparation_isolates_all_inputs_and_retains_library_release_override(self):
        original = evaluation.product_files(ROOT / "testdata/scenarios")
        metadata = evaluation.prepare(self.output, list(evaluation.cases()), 21, 1, "staged")
        self.assertEqual(len(metadata["trials"]), 8)
        for trial_id in metadata["trials"]:
            trial = self.output / "trials" / trial_id
            self.assertEqual(len(list((trial / "prompts").glob("*.txt"))), 5)
            self.assertFalse((trial / "workspace" / "cases.json").exists())
            self.assertFalse((trial / "workspace" / "evaluation_grade.py").exists())
        library = self.output / "trials/source-recipe-01/workspace"
        policy = json.loads((library / ".java-modernize/request-policy.json").read_text())
        self.assertEqual((policy["source_release"], policy["target_java"]), (17, 21))
        (library / "pom.xml").write_text("changed copy")
        self.assertEqual(evaluation.product_files(ROOT / "testdata/scenarios"), original)
        with self.assertRaises(FileExistsError):
            evaluation.prepare(self.output, ["java8"], 21, 1, "staged")

    def test_agent_transport_supplies_stdin_and_keeps_graders_outside_container(self):
        evaluation.prepare(self.output, ["java8"], 21, 1, "staged")
        trial = self.output / "trials/java8-01"
        args = SimpleNamespace(image="example@sha256:abc", maven_cache="cache", codex_bin_dir=Path("/native"),
                               auth_file=Path("/auth"), model="configured-model", reasoning_effort="high",
                               timeout=30, mode="staged")
        def execute(command, **kwargs):
            self.assertIn("--interactive", command, "Docker must forward the prompt to Codex stdin")
            self.assertTrue(kwargs["input"].strip())
            mounts = [arg for arg in command if arg.startswith("type=bind")]
            self.assertTrue(any("dst=/skill,readonly" in arg for arg in mounts))
            self.assertFalse(any("evaluation_grade" in arg or "docker.sock" in arg for arg in mounts))
            self.assertFalse(any(f"src={ROOT}," in arg for arg in mounts))
            kwargs["stdout"].write(json.dumps({"type":"item.completed", "item":{"type":"error", "message":"helper unavailable"}})+"\n")
            kwargs["stdout"].write(json.dumps({"type":"turn.completed", "usage":{"input_tokens":10}})+"\n")
            return SimpleNamespace(returncode=0)
        with mock.patch.object(evaluation.subprocess, "run", side_effect=execute):
            result = evaluation.invoke_agent(self.output, trial, "assess", args)
        self.assertEqual(len(result["agent_errors"]), 1)
        self.assertEqual(result["usage"][0]["input_tokens"], 10)

    def test_build_grade_rejects_zero_tests_wrong_bytecode_and_failed_process(self):
        metadata = {"case":"java8", "source_release":21}
        target = {"exit_code":0, "tests":{"tests":1,"failures":0,"errors":0,"skipped":0}, "classfile_majors":[65]}
        checks = []
        grader.build_checks(metadata, target, 0, checks)
        self.assertTrue(all(item["status"] == "passed" for item in checks))
        target["tests"]["tests"] = 0
        target["classfile_majors"] = [52]
        checks = []
        grader.build_checks(metadata, target, 1, checks)
        self.assertTrue(all(item["status"] == "failed" for item in checks))

    def test_library_override_requires_runtime_behavior_without_inventing_unit_tests(self):
        metadata = {"case":"source-recipe", "source_release":17}
        target = {"exit_code":0,"tests":{"tests":0,"failures":0,"errors":0,"skipped":0},
                  "classfile_majors":[61],"behavior_probe":{"compile_exit":0,"run_exit":0}}
        checks = []
        grader.build_checks(metadata, target, 0, checks)
        self.assertTrue(all(item["status"] == "passed" for item in checks))
        target["behavior_probe"]["run_exit"] = 1
        checks = []
        grader.build_checks(metadata, target, 0, checks)
        self.assertEqual(checks[-1]["status"], "failed")

    def test_ownership_grader_rejects_child_and_bom_version_overrides(self):
        evaluation.prepare(self.output, ["reactor", "maven-bom"], 21, 1, "staged")
        for case, relative, artifact in (("reactor", "app/pom.xml", "lombok"), ("maven-bom", "pom.xml", "junit-jupiter")):
            work = self.output / "trials" / f"{case}-01/workspace"
            path = work / relative
            path.write_text(path.read_text().replace(f"<artifactId>{artifact}</artifactId>",
                            f"<artifactId>{artifact}</artifactId><version>99</version>"))
            checks = []
            grader.ownership_checks(case, work, ROOT / "testdata/scenarios" / case, checks)
            self.assertEqual(checks[0]["status"], "failed")

    def test_structural_success_does_not_hide_missing_or_failed_semantic_review(self):
        evaluation.prepare(self.output, ["java8"], 21, 1, "staged")
        trial = self.output / "trials/java8-01"
        result = {"id":"java8-01", "status":"passed", "semantic_review":"pending", "enterprise_gate":{"status":"blocked"},
                  "checks":[], "semantic_criteria":["Preserve behavior", "Report missing inputs"]}
        grader.scorecard(self.output, [result])
        self.assertEqual(result["evaluation_status"], "needs_review")
        review = {"reviewer":"independent reviewer", "criteria":[
            {"criterion":c,"status":"passed","evidence":"Inspected actual outputs"} for c in result["semantic_criteria"]]}
        (trial/"review.json").write_text(json.dumps(review))
        grader.scorecard(self.output, [result])
        self.assertEqual(result["evaluation_status"], "passed")
        review["criteria"][0]["status"] = "failed"
        (trial/"review.json").write_text(json.dumps(review))
        grader.scorecard(self.output, [result])
        self.assertEqual(result["evaluation_status"], "failed")

    def test_untrusted_artifact_symlinks_are_rejected_before_reading_targets(self):
        self.output.mkdir()
        outside = self.output.parent / "private.json"
        outside.write_text('{"private":"not an evaluation artifact"}')
        link = self.output / "report.json"
        link.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "symlink"):
            grader.load(link)
        link.unlink()
        (self.output / "module").symlink_to(self.output.parent, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            evaluation.product_files(self.output)

    def test_bytecode_grader_excludes_expanded_coverage_dependency_classes(self):
        project = self.output / "app/build/classes/java/main/example/Greeting.class"
        dependency = self.output / "app/build/tmp/expandedArchives/ant/Legacy.class"
        for path in (project, dependency):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"\xca\xfe\xba\xbe\x00\x00\x00\x41")
        self.assertEqual(grader.project_classfiles(self.output), [project])


if __name__ == "__main__":
    unittest.main()
