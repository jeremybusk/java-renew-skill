#!/usr/bin/env python3
"""Run repository checks and deterministic fixture builds in the pinned image."""

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
LOCK = json.loads((ROOT / "docker/toolchains.lock.json").read_text())


def java_home(major):
    return Path(os.environ.get(f"JAVA_HOME_{major}", f"/opt/jdks/{major}"))


def environment(major):
    env = dict(os.environ)
    env.update(JAVA_HOME=str(java_home(major)), MODERNIZE_JAVA_HOME=str(java_home(major)))
    env["PATH"] = str(java_home(major) / "bin") + os.pathsep + env.get("PATH", "")
    return env


def run_command(name, args, output, cwd=ROOT, env=None, timeout=600):
    log = output / f"{name}.log"
    start = time.monotonic()
    try:
        with log.open("w", encoding="utf-8") as stream:
            result = subprocess.run(args, cwd=cwd, env=env, stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=timeout)
        code = result.returncode
    except subprocess.TimeoutExpired:
        code = 124
        with log.open("a", encoding="utf-8") as stream:
            stream.write(f"\nTimed out after {timeout} seconds.\n")
    except OSError as error:
        code = 127
        log.write_text(str(error) + "\n", encoding="utf-8")
    return {"name": name, "status": "passed" if code == 0 else "failed",
            "exit_code": code, "seconds": round(time.monotonic() - start, 3),
            "command": [str(arg) for arg in args], "log": log.name}


def test_counts(paths):
    counts = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    for path in paths:
        root = ET.parse(path).getroot()
        suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
        for suite in suites:
            for key in counts:
                counts[key] += int(suite.get(key, "0"))
    if counts["tests"] == 0 or counts["failures"] or counts["errors"]:
        raise ValueError(f"Tests missing or failed: {counts}")
    return counts


def classfile_majors(paths):
    majors = []
    for path in paths:
        data = path.read_bytes()
        if data[:4] != b"\xca\xfe\xba\xbe" or len(data) < 8:
            raise ValueError(f"Invalid classfile: {path.name}")
        majors.append(int.from_bytes(data[6:8], "big"))
    if not majors:
        raise ValueError("No compiled classes found")
    return sorted(set(majors))


def scan_coverage(document):
    packages = [item for result in document.get("results", []) for item in result.get("packages", [])]
    unresolved = [item["package"]["name"] for item in packages
                  if not (item["package"].get("version") or item["package"].get("commit"))]
    advisories = sorted({vuln["id"] for item in packages for vuln in item.get("vulnerabilities", [])})
    return {"packages": len(packages), "versioned_packages": len(packages) - len(unresolved),
            "unresolved_packages": unresolved, "advisories": advisories}


def security_scan(output, root, sbom, offline, timeout):
    args = ["osv-scanner", "scan", "source", "--all-packages", "--format", "json",
            "--output-file", str(output / "osv-scan.json")]
    args += ["-L", str(sbom)] if sbom else ["-r", str(root)]
    if offline:
        args.append("--offline")
    raw = output / "osv-scan.json"
    raw.unlink(missing_ok=True)
    record = run_command("osv-scan", args, output, timeout=timeout)
    record["input"] = str(sbom or root)
    try:
        coverage = scan_coverage(json.loads(raw.read_text()))
        record.update(coverage)
        if coverage["advisories"]:
            record.update(status="failed", detail="Known vulnerability findings; review osv-scan.json and scan diagnostics.")
        elif not coverage["versioned_packages"] or coverage["unresolved_packages"]:
            record.update(status="failed", detail="Incomplete package/version coverage; scan a build-generated SBOM or resolved lockfile.")
        elif record["exit_code"] != 0:
            record["detail"] = "Scanner failed; inspect diagnostics."
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        record.update(status="failed", detail=f"Missing or invalid scanner report: {error}")
    return record


def versions(output, timeout):
    results = []
    for major in (8, 11, 17, 21, 25):
        record = run_command(f"java-{major}", [java_home(major) / "bin/java", "-version"], output, timeout=timeout)
        text = (output / record["log"]).read_text()
        expected = 'version "1.8.' if major == 8 else f'version "{major}.'
        if expected not in text:
            record.update(status="failed", detail=f"Expected Java {major} version output")
        results.append(record)
    for name, command in (("maven", "mvn"), ("gradle8", "gradle8"), ("gradle9", "gradle9"),
                          ("osv-scanner", "osv-scanner")):
        record = run_command(name, [command, "--version"], output, env=environment(21), timeout=timeout)
        if LOCK[name]["version"] not in (output / record["log"]).read_text():
            record.update(status="failed", detail="Tool version does not match docker/toolchains.lock.json")
        results.append(record)
    script = ("import json,shutil,sys; tools=('java','javac','mvn','gradle','gradle8','gradle9','osv-scanner'); "
              "found={tool:shutil.which(tool) for tool in tools}; print(json.dumps(found,indent=2)); "
              "sys.exit(any(path is None for path in found.values()))")
    results.append(run_command("login-shell-tools", ["bash", "-lc", "python3 -c " + shlex.quote(script)],
                               output, env=environment(21), timeout=timeout))
    return results


def fixture_build(case, major, output, offline, timeout):
    name = f"{case}-java{major}"
    with tempfile.TemporaryDirectory(prefix="modernize-build-") as directory:
        work = Path(directory) / case
        shutil.copytree(ROOT / "testdata/scenarios" / case, work)
        env = environment(major)
        if case == "boot-context":
            pom = work / "pom.xml"
            source = pom.read_text()
            if f"<version>{LOCK['fixtures']['spring_boot']}</version>" not in source:
                raise ValueError("Boot fixture differs from the pinned smoke scenario")
            pom.write_text(source.replace("<java.version>17</java.version>", f"<java.version>{major}</java.version>"))
            args = ["mvn", "-B", "-ntp"] + (["-o"] if offline else []) + ["clean", "verify"]
            report_paths = lambda: list((work / "target/surefire-reports").glob("TEST-*.xml"))
            classes = lambda: list((work / "target/test-classes").rglob("*.class"))
        else:
            if case == "gradle-groovy":
                build = work / "build.gradle"
                source = build.read_text()
                source = source.replace("sourceCompatibility = JavaVersion.VERSION_1_8\n", "")
                source = source.replace("targetCompatibility = JavaVersion.VERSION_1_8\n", "")
                source = source.replace("toolVersion = '0.8.8'", f"toolVersion = '{LOCK['fixtures']['jacoco']}'")
                build.write_text(source + f"\njava {{ toolchain {{ languageVersion = JavaLanguageVersion.of({major}) }} }}\n")
            else:
                build = work / "app/build.gradle.kts"
                build.write_text(build.read_text().replace("JavaLanguageVersion.of(17)", f"JavaLanguageVersion.of({major})"))
            (work / "gradle.properties").write_text(
                "org.gradle.java.installations.auto-download=false\n"
                "org.gradle.java.installations.auto-detect=false\n"
                "org.gradle.java.installations.paths=" + ",".join(str(java_home(j)) for j in (8, 11, 17, 21, 25)) + "\n"
                "org.gradle.jvmargs=-Xmx768m -XX:MaxMetaspaceSize=384m\n")
            args = ["gradle9" if major == 25 else "gradle8", "--no-daemon", "--console=plain"]
            args += (["--offline"] if offline else []) + ["clean", "test"]
            report_paths = lambda: list(work.rglob("build/test-results/test/TEST-*.xml"))
            classes = lambda: list(work.rglob("build/classes/java/**/*.class"))
        record = run_command(name, args, output, cwd=work, env=env, timeout=timeout)
        if record["exit_code"] == 0:
            try:
                paths = report_paths()
                counts = test_counts(paths)
                majors = classfile_majors(classes())
                if counts["tests"] != 1 or counts["skipped"] or majors != [major + 44]:
                    raise ValueError(f"Unexpected test/bytecode outcome: {counts}; majors={majors}")
                if case == "boot-context" and f"BOOT_CONTEXT_VERSION={LOCK['fixtures']['spring_boot']}" not in (output / record["log"]).read_text():
                    raise ValueError("Boot context did not report the pinned runtime version")
                record.update(tests=counts, classfile_majors=majors, java=major)
                artifacts = output / name
                artifacts.mkdir(exist_ok=True)
                for index, path in enumerate(paths):
                    shutil.copy2(path, artifacts / f"{index}-{path.name}")
            except (OSError, ValueError, ET.ParseError) as error:
                record.update(status="failed", detail=str(error))
        return record


def write_report(output, results, scope=None):
    passed = all(record["status"] == "passed" for record in results)
    report = {"status": "passed" if passed else "failed",
              "created_at": dt.datetime.now(dt.timezone.utc).isoformat(), "checks": results,
              "environment": {"python": platform.python_version(), "platform": platform.platform(),
                              "architecture": platform.machine(),
                              "toolchain_lock_sha256": hashlib.sha256((ROOT / "docker/toolchains.lock.json").read_bytes()).hexdigest()},
              "scope": scope or "Repository tests and deterministic fixture build smokes; no AI agent execution or production certification."}
    (output / "results.json").write_text(json.dumps(report, indent=2) + "\n")
    lines = ["# Validation checks", "", f"Result: **{report['status']}**", "",
             "| Check | Result | Seconds | Evidence |", "| --- | --- | --- | --- |"]
    for record in results:
        evidence = f"[{record['log']}]({record['log']})" if record['log'] else "No command ran"
        lines.append(f"| {record['name']} | {record['status']} | {record['seconds']} | {evidence} |")
    details = [record for record in results if record.get("detail")]
    if details:
        lines.extend(["", "## Failures", ""])
        for record in details:
            lines.append(f"- {record['name']}: " + record["detail"].replace("\n", " "))
    for record in results:
        if "versioned_packages" in record:
            lines.extend(["", "## Dependency scan coverage", "",
                          f"- Package entries: {record['packages']}; versioned: {record['versioned_packages']}; unresolved: {len(record['unresolved_packages'])}.",
                          "- Unresolved: " + (", ".join(sorted(set(record["unresolved_packages"]))) or "none") + ".",
                          "- Advisory IDs: " + (", ".join(record["advisories"]) or "none reported") + ".",
                          "", "[Raw scan JSON](osv-scan.json)"])
    lines.extend(["", report["scope"], "", "See results.json and linked evidence for full details.", ""])
    (output / "summary.md").write_text("\n".join(lines))
    print(f"{report['status']}: {len(results)} checks; report: {output / 'summary.md'}", flush=True)
    return 0 if passed else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=("versions", "unit", "builds", "security", "all"), default="all")
    parser.add_argument("--scan-root", type=Path, default=ROOT / "testdata/scenarios", help="security suite source scope")
    parser.add_argument("--sbom", type=Path, help="security suite: scan this build-generated SBOM instead of source")
    parser.add_argument("--java", type=int, choices=(17, 21, 25), action="append", help="build lanes; default: 17, 21 and 25")
    parser.add_argument("--output", type=Path, default=Path("/reports"))
    parser.add_argument("--offline", action="store_true", help="require cached Maven/Gradle dependencies or an existing OSV database")
    parser.add_argument("--timeout", type=int, default=600, help="per-command timeout in seconds")
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    args.output.mkdir(parents=True, exist_ok=True)
    results = []
    if args.suite == "security":
        result = security_scan(args.output.resolve(), args.scan_root.resolve(), args.sbom.resolve() if args.sbom else None,
                               args.offline, args.timeout)
        return write_report(args.output, [result], "OSV dependency scan with package/version coverage checks; not the full organization security gate. Compare coverage with the effective build graph.")
    if args.suite in ("versions", "all"):
        results.extend(versions(args.output, args.timeout))
        if any(record["status"] == "failed" for record in results):
            return write_report(args.output, results)
    if args.suite in ("unit", "all"):
        env = environment(21)
        env["MODERNIZE_JAVA_INTEGRATION"] = "1"
        results.append(run_command("unit-and-compiler", [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
                                   args.output, env=env, timeout=args.timeout))
    if args.suite in ("builds", "all"):
        for major in dict.fromkeys(args.java or (17, 21, 25)):
            for case in ("boot-context", "gradle-groovy", "gradle-kotlin"):
                print(f"Building {case} on Java {major}...", flush=True)
                try:
                    results.append(fixture_build(case, major, args.output, args.offline, args.timeout))
                except (OSError, ValueError) as error:
                    results.append({"name": f"{case}-java{major}", "status": "failed", "exit_code": 2,
                                    "seconds": 0, "command": [], "log": "", "detail": str(error)})
    return write_report(args.output, results)


if __name__ == "__main__":
    sys.exit(main())
