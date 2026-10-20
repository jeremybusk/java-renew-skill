#!/usr/bin/env python3
"""Run isolated agent trials and independently grade Java modernization outcomes."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
STAGES = {"assess": "01-assessment", "plan": "02-plan", "execute": "03-execution",
          "validate": "04-validation", "summary": "05-summary"}
EXCLUDED = {".java-modernize", ".git", ".agents", ".gradle", ".m2", "target", "build", "__pycache__"}
EFFICIENCY = """
Execution efficiency: keep each phase Markdown report under 500 words, with
concise JSON findings and links to raw logs. Reuse this run's checked baseline,
version/support sources and unchanged resolved-graph evidence. Recheck external
sources when selecting a new version or when the retained evidence is stale.
Verify current policy/source fingerprints and referenced artifacts; do not
rehash the entire report tree or reproduce old report contents in new reports.
Execute uses focused checks; validate runs the clean target build and real tests.
Summary consumes retained validation without rerunning builds/scans. Never skip
required tests, hide failures or waive gates to meet these efficiency guidelines.
"""


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def sha(path):
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(block)
    return checksum.hexdigest()


def product_files(root):
    files = {}
    for directory, directories, names in os.walk(root, followlinks=False):
        directories[:] = sorted(name for name in directories if name not in EXCLUDED)
        if any((Path(directory) / name).is_symlink() for name in directories):
            raise ValueError("Product symlink directories are unsupported")
        for name in sorted(names):
            path = Path(directory) / name
            if path.is_symlink():
                raise ValueError(f"Product symlinks are unsupported: {path}")
            files[str(path.relative_to(root))] = sha(path)
    return files


def cases():
    return {case["id"]: case for case in json.loads((ROOT / "testdata/cases.json").read_text())["cases"]}


def prompt(case, stage, target, release, task):
    previous = list(STAGES)[list(STAGES).index(stage) - 1] if stage != "assess" else None
    inputs = (f"Read .java-modernize/{STAGES[previous]}.md and its matching JSON before continuing. "
              "Preserve established decisions and use .java-modernize/policy.json as the final override."
              if previous else "Inspect the supplied project and capture an actual existing-runtime baseline where possible.")
    return f"""Use the modernization skill at /skill/SKILL.md for the project in /work.

User task: {task}
Target runtime: Java {target}. Required source/API/bytecode release: {release}.
The evaluation baseline runtime to investigate is Java {case['baseline_java']}; this
is an evaluation input, not proof of a declared or observed project runtime.
Honor .java-modernize/request-policy.json. Retain the default enterprise gates;
do not add waivers or declare production readiness without the required evidence.

Perform ONLY the {stage} phase now. {inputs}
Write .java-modernize/{STAGES[stage]}.md and .json using the skill's contracts.
If blocked, still write useful, honest handoffs for this phase. Distinguish
completed phase work, tested fixture behavior and production acceptance.
Assess/plan may write reports but must leave product/build inputs unchanged.

The container provides Temurin /opt/jdks/{{8,11,17,21,25}}, JAVA_HOME_N variables,
with-java, Maven, gradle8, gradle9, Python and OSV-Scanner. Default Java is 21.
Use the appropriate actual runtime/toolchain and capture version output and test
counts. Network access is available for official compatibility sources and public
dependencies. Build caches are writable. No production services or organization
policy are implied. Do not commit, publish or inspect credentials.
""" + EFFICIENCY


def prepare(output, selected, target, trials, mode):
    output.mkdir(parents=True, exist_ok=False)
    shutil.copytree(ROOT / "skills/modernize-java", output / "skill")
    (output / "harness").mkdir()
    shutil.copy2(Path(__file__), output / "harness/evaluate.py")
    shutil.copy2(ROOT / "evaluations/tasks.json", output / "harness/tasks.json")
    shutil.copy2(ROOT / "testdata/cases.json", output / "harness/cases.json")
    tasks = json.loads((ROOT / "evaluations/tasks.json").read_text())["tasks"]
    metadata = {"schema_version": 1, "target_java": target, "mode": mode,
                "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "skill_files": product_files(output / "skill"),
                "fixtures": {}, "trials": [], "tasks_sha256": sha(ROOT / "evaluations/tasks.json"),
                "cases_sha256": sha(ROOT / "testdata/cases.json"),
                "runner_sha256": sha(Path(__file__)), "limitations": [
                    "Single trials do not establish reliability across repeated agent runs.",
                    "Deterministic grading is supplemented by an explicit semantic-review checklist.",
                    "Passing an evaluation does not establish production readiness."]}
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    metadata["repository_commit"] = revision.stdout.strip() if revision.returncode == 0 else None
    for name in selected:
        case = cases()[name]
        source = ROOT / "testdata" / case["path"]
        metadata["fixtures"][name] = product_files(source)
        shutil.copytree(source, output / "inputs" / name)
        for trial_number in range(1, trials + 1):
            trial_id = f"{name}-{trial_number:02d}"
            trial = output / "trials" / trial_id
            work = trial / "workspace"
            shutil.copytree(source, work)
            (work / ".java-modernize").mkdir()
            (trial / "prompts").mkdir()
            (trial / "captures").mkdir()
            (trial / "gradle-cache").mkdir()
            release = 17 if name == "source-recipe" else target
            override = {"schema_version": 1, "baseline_java": case["baseline_java"],
                        "target_java": target, "source_release": release}
            if name == "boot-context":
                override.update(framework_policy="preserve", dependency_pins={
                    "org.springframework.boot:spring-boot-starter-parent": "3.5.16"})
            save(work / ".java-modernize/request-policy.json", override)
            for stage in STAGES:
                (trial / "prompts" / f"{stage}.txt").write_text(prompt(case, stage, target, release, tasks[name]))
            save(trial / "trial.json", {"id": trial_id, "case": name, "trial": trial_number,
                 "baseline_java": case["baseline_java"], "target_java": target,
                 "source_release": release, "mode": mode, "phases": []})
            metadata["trials"].append(trial_id)
    save(output / "run.json", metadata)
    return metadata


def docker_base(image, work, maven_cache, gradle_cache):
    return ["docker", "run", "--rm", "--init", "--read-only", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "--memory", "4g", "--cpus", "2",
            "--tmpfs", "/tmp:rw,mode=1777", "--tmpfs", "/workspace:rw,mode=1777",
            "--workdir", "/work", "--mount", f"type=bind,src={work},dst=/work",
            "--mount", f"type=volume,src={maven_cache},dst=/home/vscode/.m2",
            "--mount", f"type=bind,src={gradle_cache},dst=/home/vscode/.gradle"]


def invoke_agent(output, trial, stage, args):
    work = trial / "workspace"
    name = "modernize-eval-" + uuid.uuid4().hex[:12]
    command = docker_base(args.image, work, args.maven_cache, trial / "gradle-cache")
    command += ["--interactive", "--name", name, "--tmpfs", "/home/vscode/.codex:rw,uid=1000,gid=1000,mode=0700",
                "--mount", f"type=bind,src={output / 'skill'},dst=/skill,readonly",
                "--mount", f"type=bind,src={args.codex_bin_dir},dst=/opt/codex/bin,readonly",
                "--mount", f"type=bind,src={args.auth_file},dst=/run/codex-auth.json,readonly",
                args.image, "sh", "-c",
                'cp /run/codex-auth.json /home/vscode/.codex/auth.json; exec /opt/codex/bin/codex "$@"', "agent",
                "exec", "--ignore-user-config", "--ignore-rules", "--ephemeral", "--skip-git-repo-check",
                "--dangerously-bypass-approvals-and-sandbox", "--json", "--model", args.model,
                "-c", f'model_reasoning_effort="{args.reasoning_effort}"', "-"]
    text = (trial / "prompts" / f"{stage}.txt").read_text()
    if args.mode == "workflow":
        text = text.replace("Perform ONLY the assess phase now.",
                            "Perform all five phases in order: assess, plan, execute, validate, summary. "
                            "After each phase, save its canonical Markdown and JSON and read them as input for the next phase.")
        text += "\nWrite all five canonical Markdown/JSON handoffs: 01-assessment, 02-plan, 03-execution, 04-validation, 05-summary. Read each saved handoff as input for the next phase.\n"
    started = time.monotonic()
    stdout = trial / "captures" / f"{stage}.jsonl"
    stderr = trial / "captures" / f"{stage}.stderr.log"
    try:
        with stdout.open("w") as events, stderr.open("w") as errors:
            result = subprocess.run(command, input=text, text=True, stdout=events, stderr=errors,
                                    timeout=args.timeout)
        code = result.returncode
    except subprocess.TimeoutExpired:
        subprocess.run(["docker", "stop", "--time", "5", name], capture_output=True)
        code = 124
    usage = []
    agent_errors = []
    for line in stdout.read_text().splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("type") == "turn.completed":
            usage.append(event.get("usage", {}))
        if event.get("type") in {"error", "turn.failed"}:
            agent_errors.append(event)
        if event.get("item", {}).get("type") == "error":
            agent_errors.append(event)
    return {"phase": stage, "exit_code": code, "seconds": round(time.monotonic() - started, 3),
            "prompt_sha256": hashlib.sha256(text.encode()).hexdigest(), "usage": usage,
            "agent_errors": agent_errors, "events": str(stdout.relative_to(output)),
            "stderr": str(stderr.relative_to(output))}


def run_trial(output, trial_id, args):
    trial = output / "trials" / trial_id
    metadata = json.loads((trial / "trial.json").read_text())
    stages = list(STAGES) if args.mode == "staged" else ["assess"]
    for stage in stages:
        print(f"{trial_id}: {stage} started", flush=True)
        before = product_files(trial / "workspace")
        previous = list(STAGES)[list(STAGES).index(stage) - 1] if stage != "assess" else None
        inputs = {}
        if previous:
            for extension in ("md", "json"):
                path = trial / "workspace/.java-modernize" / f"{STAGES[previous]}.{extension}"
                inputs[str(path.name)] = sha(path) if path.is_file() else None
        result = invoke_agent(output, trial, stage, args)
        after = product_files(trial / "workspace")
        result.update(input_handoffs=inputs, product_before=before, product_after=after,
                      product_unchanged=before == after)
        checkpoint = trial / "captures" / stage
        checkpoint.mkdir()
        for relative in after:
            destination = checkpoint / "product" / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(trial / "workspace" / relative, destination)
        reports = trial / "workspace/.java-modernize"
        if reports.is_symlink():
            raise ValueError("Report directory must not be a symlink")
        for path in reports.iterdir():
            if path.is_symlink():
                raise ValueError("Captured reports must not be symlinks")
            if path.is_file() and path.suffix in {".json", ".md"}:
                shutil.copy2(path, checkpoint / path.name)
        result["output_handoffs"] = {path.name: sha(path) for path in checkpoint.iterdir()
                                      if path.stem == STAGES[stage]}
        metadata["phases"].append(result)
        save(trial / "trial.json", metadata)
        print(f"{trial_id}: {stage} exit {result['exit_code']} ({result['seconds']}s)", flush=True)
        if result["exit_code"] != 0 or result["agent_errors"]:
            break
    save(trial / "submitted-files.json", product_files(trial / "workspace"))
    return metadata


def grade(output, image, maven_cache, selected=None):
    # Imported only on the host; this module is never mounted in agent containers.
    from evaluation_grade import grade_run
    return grade_run(output, image, maven_cache, selected)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("list", "prepare", "run", "grade", "report"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--case", action="append", choices=tuple(cases()))
    parser.add_argument("--target", type=int, choices=(21, 25), default=21)
    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument("--mode", choices=("staged", "workflow"), default="workflow")
    parser.add_argument("--image", default="modernize-java-checks:local")
    parser.add_argument("--maven-cache", default="modernize-java-evaluation-maven")
    parser.add_argument("--codex-bin-dir", type=Path)
    parser.add_argument("--auth-file", type=Path, default=Path.home() / ".codex/auth.json")
    parser.add_argument("--model")
    parser.add_argument("--reasoning-effort", choices=("low", "medium", "high", "xhigh"), default="high")
    parser.add_argument("--timeout", type=int, default=900, help="per-agent-phase seconds")
    parser.add_argument("--workers", type=int, choices=(1, 2, 3, 4), default=4)
    parser.add_argument("--defer-grade", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "list":
        for name, case in cases().items():
            print(f"{name}: baseline scenario Java {case['baseline_java']}")
        return 0
    if args.output is None:
        parser.error("--output is required")
    output = args.output.resolve()
    if args.command == "report":
        from evaluation_grade import publish
        return publish(output)
    if args.command == "grade":
        return grade(output, args.image, args.maven_cache, args.case)
    if args.trials < 1 or args.timeout < 1:
        parser.error("--trials and --timeout must be positive")
    if args.command == "run":
        if not args.model or not args.codex_bin_dir:
            parser.error("run requires --model and --codex-bin-dir (the native codex and codex-code-mode-host directory)")
        args.codex_bin_dir = args.codex_bin_dir.resolve()
        args.auth_file = args.auth_file.resolve()
        for path in (args.codex_bin_dir / "codex", args.codex_bin_dir / "codex-code-mode-host", args.auth_file):
            if not path.is_file():
                parser.error(f"Missing agent prerequisite: {path}")
        inspected = subprocess.run(["docker", "image", "inspect", args.image, "--format", "{{.Id}}"],
                                   capture_output=True, text=True, check=True)
    if args.command == "run" and (output / "run.json").is_file():
        metadata = json.loads((output / "run.json").read_text())
        if metadata["target_java"] != args.target or metadata["mode"] != args.mode:
            parser.error("Prepared target/mode do not match this invocation")
        if args.case:
            available = {json.loads((output / "trials" / trial / "trial.json").read_text())["case"] for trial in metadata["trials"]}
            if set(args.case) - available:
                parser.error("Selected case is not present in this prepared run")
            metadata["trials"] = [trial for trial in metadata["trials"]
                                  if json.loads((output / "trials" / trial / "trial.json").read_text())["case"] in args.case]
        if any(json.loads((output / "trials" / trial / "trial.json").read_text())["phases"] for trial in metadata["trials"]):
            parser.error("Run already contains agent attempts; use a fresh output directory")
    else:
        metadata = prepare(output, list(dict.fromkeys(args.case or list(cases()))), args.target, args.trials, args.mode)
    if args.command == "prepare":
        print(output)
        return 0
    metadata.update(image=args.image, image_id=inspected.stdout.strip(), model=args.model,
                    reasoning_effort=args.reasoning_effort, workers=args.workers,
                    codex_sha256=sha(args.codex_bin_dir / "codex"),
                    codex_host_sha256=sha(args.codex_bin_dir / "codex-code-mode-host"),
                    toolchain_lock_sha256=sha(ROOT / "docker/toolchains.lock.json"),
                    caches="Shared Maven artifacts; trial-specific Gradle caches. Fresh agent context per phase in staged mode.")
    version = subprocess.run([str(args.codex_bin_dir / "codex"), "--version"], capture_output=True, text=True, check=True)
    metadata["agent_cli_version"] = version.stdout.strip()
    save(output / "run.json", metadata)
    args.image = metadata["image_id"]
    execution_ok = True
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(run_trial, output, trial, args): trial for trial in metadata["trials"]}
        for future in as_completed(futures):
            if future.cancelled():
                path = output / "trials" / futures[future] / "trial.json"
                skipped = json.loads(path.read_text())
                skipped["not_run_reason"] = "An earlier agent transport failure stopped queued trials."
                save(path, skipped)
                continue
            try:
                completed = future.result()
                successful = all(phase["exit_code"] == 0 and not phase["agent_errors"] for phase in completed["phases"])
                execution_ok = execution_ok and successful
                if not successful:
                    for pending in futures:
                        pending.cancel()
            except Exception as error:
                execution_ok = False
                save(output / "trials" / futures[future] / "harness-error.json", {"error": str(error)})
                print(f"{futures[future]}: harness error: {error}", flush=True)
    metadata.update(agent_execution_complete=execution_ok, completed_at=dt.datetime.now(dt.timezone.utc).isoformat())
    save(output / "run.json", metadata)
    return (0 if execution_ok else 1) if args.defer_grade else grade(output, args.image, args.maven_cache)


if __name__ == "__main__":
    sys.exit(main())
