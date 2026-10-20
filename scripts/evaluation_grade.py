"""Independent artifact/build graders; never mounted in an agent container."""

import datetime as dt
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
STAGES = {"assess": "01-assessment", "plan": "02-plan", "execute": "03-execution",
          "validate": "04-validation", "summary": "05-summary"}
EXCLUDED = {".java-modernize", ".git", ".agents", ".gradle", ".m2", "target", "build", "__pycache__"}


def load(path):
    if any(item.is_symlink() for item in (path, *path.parents)):
        raise ValueError(f"Artifact symlink is unsupported: {path}")
    return json.loads(path.read_text())


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def run(args, cwd, output, name, java):
    env = dict(os.environ, JAVA_HOME=f"/opt/jdks/{java}")
    env["PATH"] = env["JAVA_HOME"] + "/bin:" + env["PATH"]
    try:
        with (output / f"{name}.log").open("w") as stream:
            result = subprocess.run(args, cwd=cwd, env=env, stdout=stream, stderr=subprocess.STDOUT, timeout=600)
        return result.returncode
    except subprocess.TimeoutExpired:
        return 124
    except OSError as error:
        (output / f"{name}.log").write_text(str(error))
        return 127


def project_classfiles(root):
    paths = set()
    for pattern in ("**/target/classes", "**/target/test-classes", "**/build/classes/java/main", "**/build/classes/java/test"):
        for directory in root.glob(pattern):
            paths.update(directory.rglob("*.class"))
    return sorted(paths)


def build_project(source, original, output, metadata, label, java, restore_tests=False):
    output.mkdir(parents=True, exist_ok=True)
    # Build on the writable workspace mount; /tmp deliberately remains noexec.
    with tempfile.TemporaryDirectory(prefix="work-", dir=output) as directory:
        work = Path(directory) / "project"
        shutil.copytree(source, work, ignore=shutil.ignore_patterns(*EXCLUDED))
        replaced = []
        if restore_tests:
            for test in original.rglob("src/test/**/*.java"):
                relative = test.relative_to(original)
                destination = work / relative
                if not destination.exists() or destination.read_bytes() != test.read_bytes():
                    replaced.append(str(relative))
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(test, destination)
                source_text = destination.read_text()
                annotation = "org.junit.jupiter.api.BeforeEach" if "org.junit.jupiter" in source_text else "org.junit.Before"
                guard = (f' @{annotation} public void evaluationRuntimeGuard() {{ '
                         f'if (Runtime.version().feature() != {java}) '
                         'throw new AssertionError("Wrong evaluation test JVM"); } ')
                guarded, count = re.subn(r"(\bclass\s+\w+\s*\{)", lambda match: match[1] + guard, source_text, count=1)
                if count != 1:
                    raise ValueError(f"Cannot instrument fixture test JVM guard: {test}")
                destination.write_text(guarded)
        run([f"/opt/jdks/{java}/bin/java", "-version"], work, output, label + "-java", java)
        is_gradle = metadata["case"].startswith("gradle-")
        if is_gradle:
            cache = Path(os.environ.get("GRADLE_USER_HOME", "/home/vscode/.gradle"))
            cache.mkdir(parents=True, exist_ok=True)
            (cache / "gradle.properties").write_text(
                "org.gradle.java.installations.auto-download=false\n"
                "org.gradle.java.installations.auto-detect=false\n"
                "org.gradle.java.installations.paths=" + ",".join(f"/opt/jdks/{j}" for j in (8,11,17,21,25)) + "\n"
                "org.gradle.jvmargs=-Xmx768m -XX:MaxMetaspaceSize=384m\n")
            launcher = "./gradlew" if (work / "gradlew").is_file() else "gradle9" if java == 25 else "gradle8"
            command = [launcher, "--no-daemon", "--console=plain", "clean", "test"]
            if metadata["case"] == "gradle-groovy":
                command.append("jacocoTestReport")
        else:
            command = ["mvn", "-B", "-ntp", "clean", "verify"]
        code = run(command, work, output, label + "-build", java)
        graph_code = None
        if label == "target" and code == 0:
            if is_gradle:
                task = ":app:dependencies" if metadata["case"] == "gradle-kotlin" else "dependencies"
                graph_command = [launcher, "--no-daemon", "--console=plain", task, "--configuration", "testRuntimeClasspath"]
            else:
                graph_command = ["mvn", "-B", "-ntp", "org.apache.maven.plugins:maven-dependency-plugin:3.8.1:tree"]
            graph_code = run(graph_command, work, output, "target-dependencies", java)
        counts = dict(tests=0, failures=0, errors=0, skipped=0)
        classnames = set()
        reports = []
        for path in work.rglob("TEST-*.xml"):
            if not (("surefire-reports" in path.parts and "target" in path.parts) or
                    ("test-results" in path.parts and "build" in path.parts)):
                continue
            document = ET.parse(path).getroot()
            suites = [document] if document.tag == "testsuite" else document.findall("testsuite")
            for suite in suites:
                for key in counts:
                    counts[key] += int(suite.get(key, "0"))
                classnames.update(test.get("classname", "") for test in suite.findall("testcase"))
            destination = output / f"{label}-{len(reports)}-{path.name}"
            shutil.copy2(path, destination)
            reports.append(destination.name)
        majors = set()
        classfiles = {}
        for path in project_classfiles(work):
            data = path.read_bytes()
            if len(data) < 8 or data[:4] != b"\xca\xfe\xba\xbe":
                raise ValueError(f"Invalid classfile {path}")
            major = int.from_bytes(data[6:8], "big")
            majors.add(major)
            classfiles[str(path.relative_to(work))] = major
        result = dict(command=command, exit_code=code, java_major=java, tests=counts,
                      test_classes=sorted(classnames), classfile_majors=sorted(majors),
                      classfile_details=classfiles,
                      reports=reports, original_tests_restored=replaced,
                      required_test_classes=sorted("example." + path.stem for path in original.rglob("src/test/**/*.java")),
                      target_jvm_assertion_injected=restore_tests and bool(list(original.rglob("src/test/**/*.java"))),
                      dependency_graph_exit=graph_code)
        if metadata["case"] == "source-recipe" and label == "target" and code == 0:
            probe = Path(directory) / "ExternalProbe.java"
            probe.write_text('''public class ExternalProbe {
                public static void main(String[] args) {
                    for (String name : new String[] {"Java", "", "\\u03bb", null}) {
                        String expected = String.format("Hello, %s", name);
                        if (!expected.equals(example.Greeting.hello(name))) throw new AssertionError(name);
                    }
                    System.out.println("BEHAVIOR_OK");
                }
            }''')
            compiled = run(["javac", "-cp", str(work / "target/classes"), "-d", directory, str(probe)],
                           work, output, "behavior-compile", java)
            executed = run(["java", "-cp", str(work / "target/classes") + ":" + directory, "ExternalProbe"],
                           work, output, "behavior-run", java) if compiled == 0 else None
            result["behavior_probe"] = dict(compile_exit=compiled, run_exit=executed)
        return result


def build_entry():
    metadata = load(Path("/trial.json"))
    output = Path("/results")
    result = {}
    try:
        result["baseline"] = build_project(Path("/original"), Path("/original"), output, metadata,
                                           "baseline", metadata["baseline_java"])
        result["target"] = build_project(Path("/submission"), Path("/original"), output, metadata,
                                         "target", metadata["target_java"], restore_tests=True)
    except Exception as error:
        result["harness_error"] = str(error)
    save(output / "build-results.json", result)
    return 1 if "harness_error" in result else 0


def xml(path):
    document = ET.parse(path).getroot()
    for node in document.iter():
        node.tag = node.tag.split("}")[-1]
    return document


def dependency(root, artifact):
    return next((element for element in root.findall(".//dependency") if element.findtext("artifactId") == artifact), None)


def check(checks, name, passed, detail):
    checks.append({"id": name, "status": "passed" if passed else "failed", "detail": detail})


def build_checks(metadata, target, process_code, checks):
    check(checks, "independent-clean-build", process_code == 0 and target.get("exit_code") == 0,
          "Fresh build uses the submitted build configuration and protected original test assertions.")
    expected_count = 0 if metadata["case"] == "source-recipe" else 1
    counts = target.get("tests", {})
    check(checks, "actual-test-discovery", counts.get("tests", -1) >= expected_count and
          all(counts.get(key) == 0 for key in ("failures", "errors", "skipped")) and
          set(target.get("required_test_classes", [])).issubset(target.get("test_classes", [])),
          f"Required at least {expected_count} test(s), including original fixture assertions; observed {counts}. Zero original source-recipe unit tests are a known limitation.")
    check(checks, "emitted-bytecode", target.get("classfile_majors") == [metadata["source_release"] + 44],
          f"Required classfile major {metadata['source_release'] + 44}; observed {target.get('classfile_majors')}.")
    if metadata["case"] == "source-recipe":
        probe = target.get("behavior_probe", {})
        check(checks, "runtime-behavior", probe.get("compile_exit") == 0 and probe.get("run_exit") == 0,
              "Independent runtime probe verifies normal, empty, Unicode and null greeting inputs.")


def ownership_checks(case, work, original, checks):
    if case == "java8":
        comment = "<!-- This comment and the existing POM formatting should survive migration. -->"
        check(checks, "pom-comment", comment in (work / "pom.xml").read_text(), "Original POM comment survives.")
    elif case == "reactor":
        parent, child = xml(work / "pom.xml"), xml(work / "app/pom.xml")
        valid = all(dependency(parent, artifact) is not None and dependency(child, artifact) is not None and
                    dependency(parent, artifact).findtext("version") == expression and
                    dependency(child, artifact).find("version") is None
                    for artifact, expression in (("lombok", "${lombok.version}"), ("junit-jupiter", "${junit.version}")))
        processors = child.findall(".//annotationProcessorPaths/path") + parent.findall(".//annotationProcessorPaths/path")
        valid = valid and all(child.find("properties/" + prop) is None for prop in ("junit.version", "lombok.version"))
        check(checks, "parent-and-processor-ownership", valid and any(p.findtext("artifactId") == "lombok" and
              p.findtext("version") == "${lombok.version}" for p in processors), "Dependency and processor versions remain property-owned by the parent.")
    elif case == "maven-bom":
        pom = xml(work / "pom.xml")
        bom, junit = dependency(pom, "junit-bom"), dependency(pom, "junit-jupiter")
        check(checks, "bom-ownership", bom is not None and bom.findtext("scope") == "import" and
              junit is not None and junit.find("version") is None, "JUnit remains owned by an imported BOM.")
    elif case == "gradle-kotlin":
        catalog = work / "gradle/libs.versions.toml"
        build = (work / "app/build.gradle.kts").read_text()
        check(checks, "catalog-ownership", catalog.is_file() and "libs.junit" in build and
              "junit:junit:" not in build, "Dependency remains in its version catalog.")
        version = re.search(r'''(?m)^\s*junit\s*=\s*["']([^"']+)["']''', catalog.read_text()) if catalog.is_file() else None
        check(checks, "junit-patch-updated", version is not None and version[1].startswith("4.") and version[1] != "4.12",
              "Requested JUnit patch update is made in its catalog owner.")
        kotlin_sources = [path for path in work.rglob("*.kt") if not EXCLUDED.intersection(path.relative_to(work).parts)]
        check(checks, "no-kotlin-application-upgrade", not kotlin_sources and "kotlin(\"jvm\")" not in build,
              "Kotlin DSL is not treated as a Kotlin application compiler migration.")
    elif case == "gradle-groovy":
        check(checks, "coverage-plugin-retained", "jacoco" in (work / "build.gradle").read_text(), "Existing coverage tooling remains configured and its report task is independently executed.")
    elif case == "boot-context":
        parent = xml(work / "pom.xml").find("parent")
        check(checks, "boot-line-preserved", parent is not None and parent.findtext("version") == "3.5.16",
              "Existing Boot 3.5.16 is preserved as requested.")
        pom = xml(work / "pom.xml")
        check(checks, "platform-managed-dependencies", all(element.find("version") is None for element in pom.findall("dependencies/dependency")),
              "No individual managed dependency versions are introduced.")
    elif case == "source-recipe":
        check(checks, "existing-formatting-behavior-preserved", "String.format" in (work / "src/main/java/example/Greeting.java").read_text(),
              "Existing formatting API is retained; independent runtime probe checks behavior.")
    elif case == "jetty9":
        from evaluate import product_files
        check(checks, "partial-input-preserved", product_files(work) == product_files(original),
              "Missing server/build inputs remain explicit; no unsupported implementation is invented.")


def handoff_checks(output, trial, metadata, checks):
    from evaluate import product_files
    spec = importlib.util.spec_from_file_location("evaluated_skill", output / "skill/scripts/modernize.py")
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    work = trial / "workspace"
    overrides = [work / ".java-modernize/request-policy.json"]
    final_policy = work / ".java-modernize/policy.json"
    if final_policy.is_file():
        overrides.append(final_policy)
    default = helper.resolve_policy(work, overrides)
    requested = helper.resolve_policy(output / "inputs" / metadata["case"], overrides[:1])
    required = helper.load_json(helper.ASSETS / "defaults.json")["required_gates"]
    policies = []
    for stage, stem in STAGES.items():
        captured = trial / "captures" / (stage if metadata["mode"] == "staged" else "assess")
        handoff, markdown = captured / (stem + ".json"), captured / (stem + ".md")
        valid, detail = False, "Canonical Markdown/JSON handoff is missing."
        if handoff.is_file() and markdown.is_file():
            try:
                document = load(handoff)
                helper.validate(document, helper.load_json(helper.ASSETS / "handoff.schema.json"))
                valid = document["stage"] == stage and bool(markdown.read_text().strip())
                detail = f"Canonical {stage} report satisfies the structured contract."
                policy_path = captured / "policy.json"
                if policy_path.is_file():
                    candidates = [load(policy_path)]
                    if metadata["mode"] == "workflow":
                        candidates.append(requested)
                    phase_policy = next((p for p in candidates if helper.digest(p) == document["policy_sha256"]), None)
                    if phase_policy is None:
                        raise ValueError("No retained initial/final policy matches this handoff; use staged mode for intermediate policy audits.")
                    policies.append(phase_policy)
                    phase = next((item for item in metadata["phases"] if item["phase"] == stage), None)
                    source = captured / "product"
                    if metadata["mode"] == "workflow" and stage in {"assess", "plan"}:
                        source = output / "inputs" / metadata["case"]
                    if not source.is_dir() and phase:
                        if product_files(work) == phase["product_after"]:
                            source = work
                        elif phase["product_after"] == load(output / "run.json")["fixtures"][metadata["case"]]:
                            source = output / "inputs" / metadata["case"]
                    if source.is_dir():
                        valid = valid and document["inventory_sha256"] == helper.inventory(source, phase_policy)["inventory_sha256"]
                    if not valid:
                        detail = "Handoff policy/source fingerprint does not match its recorded phase snapshot."
            except (OSError, ValueError, KeyError, TypeError) as error:
                detail = str(error)
        check(checks, f"handoff-{stage}", valid, detail)
    for phase in metadata["phases"]:
        if metadata["mode"] == "staged" and phase["phase"] in {"assess", "plan"}:
            check(checks, f"{phase['phase']}-no-product-edits", phase["product_unchanged"], "Assess/plan leave product inputs unchanged.")
        check(checks, f"agent-{phase['phase']}", phase["exit_code"] == 0 and not phase["agent_errors"],
              f"Actual agent process exit {phase['exit_code']}; agent errors: {len(phase['agent_errors'])}.")
    check(checks, "policy-retained", len(policies) == len(STAGES) and all(p["target_java"] == metadata["target_java"] and
          p["source_release"] == metadata["source_release"] and p["required_gates"] == required and not p["waivers"] and
          p["framework_policy"] == requested["framework_policy"] and
          p.get("remediation") == requested.get("remediation") and
          all(p.get(field, {}).get(name) == value for field in ("dependency_pins", "resource_targets")
              for name, value in requested.get(field, {}).items()) for p in policies),
          "Requested runtime/release, remediation/resource policy and default enterprise gates are retained without waivers.")
    evidence_path = work / ".java-modernize/evidence.json"
    enterprise = {"status": "not_recorded"}
    if metadata["case"] != "jetty9":
        check(checks, "evidence-manifest-present", evidence_path.is_file(), "Buildable cases retain a structured final evidence manifest.")
    if evidence_path.is_file():
        try:
            enterprise = helper.check_evidence(work, default, load(evidence_path))
            integrity_errors = [error for error in enterprise["errors"]
                                if not re.fullmatch(r"[a-z_]+: (?:not_run|failed)", error)]
            check(checks, "evidence-artifact-integrity", not integrity_errors, "; ".join(integrity_errors) or "Declared artifact hashes match the final submitted files.")
            check(checks, "production-acceptance-not-invented", enterprise["status"] == "blocked",
                  "Missing organization/application acceptance inputs remain explicit instead of becoming an enterprise pass.")
        except (OSError, ValueError, KeyError, TypeError) as error:
            enterprise = {"status": "invalid", "errors": [str(error)]}
            check(checks, "evidence-artifact-integrity", False, str(error))
    return enterprise


def grade_trial(output, trial, image, maven_cache):
    from evaluate import docker_base, product_files, sha
    metadata = load(trial / "trial.json")
    if (trial / "grade.json").is_file():
        history = trial / "grading-history" / dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        history.mkdir(parents=True)
        for path in [trial / "grade.json", trial / "review.json"] + list((trial / "grading").glob("*")):
            if not path.is_symlink() and path.is_file():
                shutil.copy2(path, history / path.name)
    case = metadata["case"]
    original = output / "inputs" / case
    if not original.is_dir():
        original = ROOT / "testdata/scenarios" / case
    work = trial / "workspace"
    result = {"id": metadata["id"], "case": case, "checks": [], "semantic_review": "pending"}
    checks = result["checks"]
    if not metadata["phases"] or any(phase["exit_code"] != 0 or phase["agent_errors"] for phase in metadata["phases"]):
        result.update(status="infrastructure_blocked", semantic_review="not_evaluated", enterprise_gate={"status": "not_evaluated"})
        check(checks, "agent-transport", False, "Agent launch/API/session failure; inspect the captured stderr/events. Not counted as a skill decision failure.")
        save(trial / "grade.json", result)
        return result
    submitted = trial / "submitted-files.json"
    check(checks, "submitted-product-integrity", submitted.is_file() and product_files(work) == load(submitted),
          "Product files match the agent's final captured submission; no later edits are silently substituted.")
    check(checks, "original-fixture-integrity", product_files(original) == load(output / "run.json")["fixtures"][case],
          "Original corpus bytes match the prepared inputs.")
    try:
        result["enterprise_gate"] = handoff_checks(output, trial, metadata, checks)
    except (OSError, ValueError, KeyError, TypeError) as error:
        result["enterprise_gate"] = {"status": "invalid", "errors": [str(error)]}
        check(checks, "submitted-handoff-validity", False, str(error))
    try:
        ownership_checks(case, work, original, checks)
    except (OSError, ValueError, ET.ParseError) as error:
        check(checks, "submitted-descriptor-validity", False, str(error))
    if case != "jetty9":
        destination = trial / "grading"
        destination.mkdir(exist_ok=True)
        cache = destination / "gradle-cache"
        cache.mkdir(exist_ok=True)
        command = docker_base(image, work, maven_cache, cache)
        # Read-only submission, original tests and grader; only results/caches are writable.
        index = command.index(f"type=bind,src={work},dst=/work")
        command[index] += ",readonly"
        command += ["--mount", f"type=bind,src={work},dst=/submission,readonly",
                    "--mount", f"type=bind,src={original},dst=/original,readonly",
                    "--mount", f"type=bind,src={Path(__file__).resolve()},dst=/grader.py,readonly",
                    "--mount", f"type=bind,src={trial / 'trial.json'},dst=/trial.json,readonly",
                    "--mount", f"type=bind,src={destination},dst=/results", image, "python3", "/grader.py", "build"]
        with (destination / "container.log").open("w") as stream:
            process = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, timeout=1500)
        if not (destination / "build-results.json").is_file():
            raise RuntimeError("Independent grader produced no build results; inspect grading/container.log")
        built = load(destination / "build-results.json")
        result["independent_build"] = built
        target = built.get("target", {})
        build_checks(metadata, target, process.returncode, checks)
    else:
        summary = work / ".java-modernize/05-summary.json"
        check(checks, "expected-blocked-result", summary.is_file() and load(summary).get("status") == "blocked",
              "Partial Jetty input must retain a blocked result instead of claiming successful deployment.")
    result["status"] = "passed" if checks and all(item["status"] == "passed" for item in checks) else "failed"
    rubric = output / "harness/cases.json"
    result["semantic_criteria"] = next(case for case in load(rubric if rubric.is_file() else ROOT / "testdata/cases.json")["cases"] if case["id"] == metadata["case"])["acceptance"]
    save(trial / "review-template.json", {"reviewer": "", "criteria": [
        {"criterion": criterion, "status": "pending", "evidence": ""} for criterion in result["semantic_criteria"]]})
    result["grader_sha256"] = sha(Path(__file__))
    result["agent_seconds"] = round(sum(phase["seconds"] for phase in metadata["phases"]), 3)
    result["agent_usage"] = {key: sum(usage.get(key, 0) for phase in metadata["phases"]
                                     for usage in phase.get("usage", []))
                             for key in ("input_tokens", "cached_input_tokens", "output_tokens")}
    save(trial / "grade.json", result)
    return result


def scorecard(output, results):
    metadata = load(output / "run.json")
    lines = ["# Java modernization skill evaluation", "",
             f"Target: Java {metadata['target_java']}; mode: {metadata['mode']}; model: {metadata.get('model', 'not recorded')}.", "",
             f"Graded trials: {len(results)} of {len(metadata['trials'])} prepared trials.", "",
             "Evaluation correctness and production readiness are reported separately. Expected partial-input blockers can be correct outcomes.", "",
             "| Trial | Deterministic checks | Semantic review | Enterprise gate | Evidence |",
             "| --- | --- | --- | --- | --- |"]
    for result in results:
        trial_id = result["id"]
        path = f"trials/{trial_id}"
        review_path = output / path / "review.json"
        if review_path.is_file():
            review = load(review_path)
            expected = set(result.get("semantic_criteria", []))
            reviewed = {item["criterion"] for item in review.get("criteria", [])}
            complete = expected and expected == reviewed and review.get("reviewer") and all(
                item.get("evidence") and item.get("status") in {"passed", "not_applicable"} for item in review["criteria"])
            result["semantic_review"] = "passed" if complete else "failed" if any(
                item.get("status") == "failed" for item in review.get("criteria", [])) else "pending"
            result["review"] = review
        elif result["status"] not in {"infrastructure_blocked", "grader_error"}:
            result["semantic_review"] = "pending"
            result.pop("review", None)
        lines.append(f"| {trial_id} | {result['status']} | {result['semantic_review']} | {result['enterprise_gate']['status']} | [Details]({path}/grade.md) |")
        detail = [f"# {trial_id}", "", f"Deterministic checks: **{result['status']}**. Semantic review: **{result['semantic_review']}**.", "",
                  "| Check | Result | Detail |", "| --- | --- | --- |"]
        for item in result["checks"]:
            detail.append(f"| {item['id']} | {item['status']} | " + item["detail"].replace("|", "\\|").replace("\n", " ") + " |")
        detail.extend(["", "## Semantic review checklist", ""])
        if result.get("review"):
            detail.append("Reviewer: " + result["review"]["reviewer"])
            detail.append("")
            for item in result["review"]["criteria"]:
                detail.append(f"- **{item['status']}**: {item['criterion']} — {item.get('evidence', '')}")
            if result["review"].get("observations"):
                detail.extend(["", "## Review observations", ""])
                detail.extend("- " + note for note in result["review"]["observations"])
        else:
            detail.extend("- " + item for item in result.get("semantic_criteria", []))
        built = result.get("independent_build", {})
        if built:
            detail.extend(["", "## Independent builds", "", "| Build | JDK | Exit | Tests | Classfile majors |",
                           "| --- | --- | --- | --- | --- |"])
            for label in ("baseline", "target"):
                record = built.get(label, {})
                detail.append(f"| {label} | {record.get('java_major')} | {record.get('exit_code')} | {record.get('tests')} | {record.get('classfile_majors')} |")
        if "agent_seconds" in result:
            detail.extend(["", "## Agent run measurements", "",
                           f"Sum of phase durations: {result['agent_seconds']} seconds. Trials can run concurrently.",
                           f"Recorded model token usage: {result['agent_usage']}. No monetary cost is inferred."])
        detail.extend(["", "## Evidence", "", "- [Phase transcripts and captured handoffs](captures/)",
                       "- [Agent summary](workspace/.java-modernize/05-summary.md)",
                       "- [Structured grade](grade.json)"])
        if built:
            detail.append("- [Independent build results](grading/build-results.json)")
        detail.extend([
                       "", "The agent has no access to this grader. Builds use protected original test assertions in disposable copies.", ""])
        result["evaluation_status"] = result["status"] if result["status"] != "passed" else (
            "passed" if result["semantic_review"] == "passed" else "failed" if result["semantic_review"] == "failed" else "needs_review")
        save(output / "trials" / trial_id / "grade.json", result)
        (output / "trials" / trial_id / "grade.md").write_text("\n".join(detail))
    lines.extend(["", "## Limits", ""] + ["- " + item for item in metadata["limitations"]] + [
        "- Semantic checklist results require transcript/report/diff review; structural checks alone are insufficient.",
        "- Independent baseline failures and zero-test baselines remain visible in build-results.json.",
        "- Shared Maven artifact caches and network advisory/version data are external inputs.", ""])
    complete = len(results) == len(metadata["trials"]) and all(result["evaluation_status"] == "passed" for result in results)
    overall = "passed" if complete else "failed" if any(result["evaluation_status"] == "failed" for result in results) else "incomplete"
    lines[2:2] = [f"Overall evaluation: **{overall}**.", ""]
    (output / "summary.md").write_text("\n".join(lines))
    save(output / "results.json", {"status": overall, "created_at": dt.datetime.now(dt.timezone.utc).isoformat(), "trials": results})


def publish(output):
    results = [load(output / "trials" / trial / "grade.json") for trial in load(output / "run.json")["trials"]
               if (output / "trials" / trial / "grade.json").is_file()]
    scorecard(output, results)
    return 0 if load(output / "results.json")["status"] == "passed" else 1


def grade_run(output, image, maven_cache, selected=None):
    from evaluate import sha
    metadata = load(output / "run.json")
    image = metadata.get("image_id", image)
    (output / "harness").mkdir(exist_ok=True)
    archives = output / "harness/graders"
    archives.mkdir(exist_ok=True)
    previous = output / "harness/evaluation_grade.py"
    if previous.is_file():
        shutil.copy2(previous, archives / (sha(previous) + ".py"))
    shutil.copy2(Path(__file__), archives / (sha(Path(__file__)) + ".py"))
    shutil.copy2(Path(__file__), output / "harness/evaluation_grade.py")
    results = []
    for trial_id in metadata["trials"]:
        if selected and load(output / "trials" / trial_id / "trial.json")["case"] not in selected:
            continue
        print(f"Grading {trial_id}...", flush=True)
        try:
            result = grade_trial(output, output / "trials" / trial_id, image, maven_cache)
        except Exception as error:
            result = {"id": trial_id, "status": "grader_error", "semantic_review": "not_evaluated",
                      "enterprise_gate": {"status": "unknown"}, "checks": [
                          {"id": "grader-error", "status": "failed", "detail": str(error)}]}
            save(output / "trials" / trial_id / "grade.json", result)
        results.append(result)
        scorecard(output, results)
    print(f"Scorecard: {output / 'summary.md'}", flush=True)
    return 0 if results and all(result.get("evaluation_status") == "passed" for result in results) else 1


if __name__ == "__main__":
    sys.exit(build_entry() if sys.argv[1:] == ["build"] else "Use evaluate.py grade --output <run>.")
