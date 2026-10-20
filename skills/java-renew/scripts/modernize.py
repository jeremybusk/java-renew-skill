#!/usr/bin/env python3
"""Offline, read-only inventory, policy resolution, and evidence checks. Python 3.10+."""

import argparse
import copy
from contextlib import contextmanager
import datetime as dt
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import xml.etree.ElementTree as ET

ASSETS = Path(__file__).resolve().parents[1] / "assets"
HARD_EXCLUDES = {".git", ".hg", ".svn", ".aws", ".ssh", ".codex", ".agents", ".java-modernize"}
SUFFIXES = {".java", ".xml", ".gradle", ".kts", ".kt", ".groovy", ".scala", ".sbt",
            ".toml", ".properties", ".yml", ".yaml", ".sh", ".bat", ".cmd", ".ps1",
            ".conf", ".config", ".cfg", ".json", ".mf", ".dockerfile", ".lockfile", ".lock",
            ".sql", ".jsp", ".jspx", ".tag", ".tld", ".xhtml", ".fxml", ".wsdl", ".xsd"}
NAMES = {"Dockerfile", "Jenkinsfile", "Makefile", ".java-version", ".tool-versions", ".sdkmanrc",
         "mvnw", "gradlew"}
MAX_JSON_BYTES = 16 * 1024 * 1024
STAGES = {"assess": "01-assessment", "plan": "02-plan", "execute": "03-execution",
          "validate": "04-validation", "summary": "05-summary"}
REMEDIATION_SCOPES = ("runtime", "test", "build", "processors", "agents", "containers")
# One finding per rule per file. These are review hints, never proof of incompatibility.
RULES = [
    ("internal-api", "high", r"\b(?:sun\.misc|sun\.reflect|jdk\.internal|com\.sun\.(?:tools|image|xml\.internal))\b",
     "Replace unsupported internals; inspect the dependency owning each call."),
    ("deep-reflection", "high", r"setAccessible\s*\(|--add-(?:opens|exports)|--illegal-access",
     "Test strong encapsulation; replace reflection before adding temporary module flags."),
    ("removed-javaee", "high", r"\bjavax\.(?:xml\.(?:bind|ws|soap)|activation|annotation(?!\.processing\b)|jws)\b|\borg\.omg\b",
     "Review modules removed from the JDK; select API and implementation matching the framework namespace."),
    ("jakarta-boundary", "medium", r"\b(?:javax|jakarta)\.(?:servlet|websocket|persistence|validation|transaction(?!\.xa\b)|inject|enterprise|ws\.rs)\b",
     "Align framework, application server, API, provider, and generated code namespaces."),
    ("security-manager", "high", r"\b(?:SecurityManager|setSecurityManager|AccessController)\b|java\.security\.manager",
     "Review reliance on the security sandbox; Security Manager is disabled in Java 24+."),
    ("removed-engine", "high", r"\b(?:nashorn|Pack200|rmic|javaws|appletviewer)\b|getEngineByName\s*\(",
     "Replace removed engines or deployment tools and validate embedded scripts."),
    ("javafx", "medium", r"\bjavafx\.",
     "Provide a compatible standalone JavaFX distribution and platform-native modules."),
    ("jdk-layout", "high", r"(?:rt|tools)\.jar|java\.ext\.dirs|java\.endorsed\.dirs|BootClassLoader|URLClassLoader",
     "Remove JDK 8 image/classloader assumptions; test custom loaders and packaging."),
    ("obsolete-jvm-flags", "high", r"UseConcMarkSweepGC|UseParNewGC|(?:Max)?PermSize|PrintGCDetails|Xloggc|AggressiveOpts|UseBiasedLocking",
     "Verify startup flags against the actual target JVM and replace removed GC/logging options."),
    ("encoding-locale", "medium", r"FileReader\s*\(|FileWriter\s*\(|getBytes\s*\(\s*\)|new\s+String\s*\(|java\.locale\.providers|file\.encoding|SimpleDateFormat",
     "Test explicit encodings, CLDR formatting, time zones, and persisted text contracts."),
    ("native-access", "medium", r"System\.load(?:Library)?\s*\(|\b(?:JNI|JNA)\b|--enable-native-access|sun\.misc\.Unsafe",
     "Validate native architecture, restricted access warnings, and vendor compatibility."),
    ("agents", "medium", r"-javaagent:|ByteBuddyAgent|mockito-inline|EnableDynamicAgentLoading|VirtualMachine\.attach",
     "Verify agent classfile support and attachment behavior; test startup agent configuration."),
    ("annotation-processing", "medium", r"\b(?:lombok|mapstruct|querydsl|errorprone|annotationProcessor|kapt)\b",
     "Declare processors explicitly; Java 23+ no longer implicitly discovers them as before."),
    ("bytecode-tooling", "medium", r"\b(?:jacoco|byte-buddy|cglib|javassist|powermock|groovy|org\.ow2\.asm)\b",
     "Verify compiler/runtime support, including classfile major 69 for Java 25."),
    ("dependency-platform", "medium", r"spring-boot|hibernate|quarkus|micronaut|io\.netty|slf4j|log4j|flyway|liquibase",
     "Resolve the platform BOM and supported dependency combination before choosing versions."),
    ("tests-disabled", "high", r"maven\.test\.skip|skipTests|failIfNoTests|ignoreFailures|exclude.*[Tt]est",
     "Review skipped tests and discovery; a successful build can execute zero tests."),
    ("legacy-java-config", "medium", r"(?:VERSION_1_8|JavaVersion\.VERSION_1_8|java-version:\s*['\"]?8\b|(?:source|target|release)>1?\.?8<|java\.version>1?\.?8<)",
     "Reconcile build launcher, compiler release, test launcher, CI, and runtime Java versions."),
    ("preview", "medium", r"--enable-preview",
     "Preview bytecode requires the matching JDK release and flags at compile, test, and runtime."),
]
RULES = [(key, level, re.compile(pattern, re.I), message) for key, level, pattern, message in RULES]


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True).encode()).hexdigest()


@contextmanager
def open_regular(path):
    """Reject special files before reading, including a leaf replaced during open."""
    path = Path(path)
    if path.is_symlink():
        raise ValueError("symlink file is unsupported")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(path, flags)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode) or path.is_symlink():
            raise ValueError("expected a regular file")
        stream = os.fdopen(descriptor, "rb")
    except BaseException:
        os.close(descriptor)
        raise
    with stream:
        yield stream


def file_digest(path):
    result = hashlib.sha256()
    with open_regular(path) as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def load_json(path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def invalid_number(_):
        raise ValueError("non-finite JSON number")

    with open_regular(path) as stream:
        data = stream.read(MAX_JSON_BYTES + 1)
    if len(data) > MAX_JSON_BYTES:
        raise ValueError("JSON input exceeds 16 MiB limit")
    return json.loads(data.decode("utf-8"), object_pairs_hook=pairs, parse_constant=invalid_number)


def validate(value, schema, location="$"):
    """Validate the JSON Schema keyword subset used by the bundled schemas only."""
    kinds = {"object": dict, "array": list, "string": str, "integer": int, "boolean": bool}
    if "type" in schema and type(value) is not kinds[schema["type"]]:
        raise ValueError(f"{location}: expected {schema['type']}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{location}: unsupported value")
    if isinstance(value, dict):
        if set(schema.get("required", [])) - value.keys():
            raise ValueError(f"{location}: missing required fields")
        properties = schema.get("properties", {})
        for key, item in value.items():
            if "propertyNames" in schema:
                validate(key, schema["propertyNames"], location + ".<key>")
            child = properties.get(key, schema.get("additionalProperties", {}))
            if child is False:
                raise ValueError(f"{location}.{key}: unknown field")
            if isinstance(child, dict):
                validate(item, child, location + "." + key)
    elif isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            raise ValueError(f"{location}: too few items")
        if schema.get("uniqueItems") and len({digest(item) for item in value}) != len(value):
            raise ValueError(f"{location}: duplicate items")
        for index, item in enumerate(value):
            validate(item, schema.get("items", {}), f"{location}[{index}]")
    elif isinstance(value, str):
        if len(value.strip()) < schema.get("minLength", 0):
            raise ValueError(f"{location}: empty or short string")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            raise ValueError(f"{location}: invalid format")
        if schema.get("format") == "date":
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                raise ValueError(f"{location}: expected YYYY-MM-DD")
            dt.date.fromisoformat(value)
    elif type(value) is int:
        if not schema.get("minimum", value) <= value <= schema.get("maximum", value):
            raise ValueError(f"{location}: outside supported range")


def merge(base, layer):
    result = copy.deepcopy(base)
    for key, value in layer.items():
        result[key] = merge(result[key], value) if isinstance(value, dict) and key in result else value
    return result


def resolve_policy(root, overrides):
    schema = load_json(ASSETS / "config.schema.json")
    policy = load_json(ASSETS / "defaults.json")
    project = root / ".java-modernize.json"
    paths = ([project] if project.exists() or project.is_symlink() else []) + [Path(path) for path in overrides]
    for path in paths:
        layer = load_json(path)
        validate(layer, schema)
        policy = merge(policy, layer)
    validate(policy, schema)
    if set(policy) != set(load_json(ASSETS / "defaults.json")):
        raise ValueError("effective policy is incomplete")
    if policy["source_release"] > policy["target_java"] or policy["baseline_java"] > policy["target_java"]:
        raise ValueError("source_release and baseline_java must not exceed target_java")
    if policy["allow_preview"] and policy["source_release"] != policy["target_java"]:
        raise ValueError("preview requires source_release equal to target_java")
    for name, target in policy["resource_targets"].items():
        if set(target) != {"kind", "selector", "version"}:
            raise ValueError(f"resource_targets.{name}: kind, selector and version are required")
        version = target["version"]
        valid = (re.fullmatch(r"\S+@sha256:[0-9a-f]{64}", version) if target["kind"] == "image"
                 else re.fullmatch(r"[0-9][0-9A-Za-z._+-]*", version) and
                 "SNAPSHOT" not in version.upper() and not version.endswith(("+", ".", "-")))
        if not valid:
            raise ValueError(f"resource_targets.{name}: use an exact version or immutable image digest")
    seen = set()
    for waiver in policy["waivers"]:
        if waiver["gate"] not in policy["required_gates"] or waiver["gate"] in seen:
            raise ValueError("waivers must name distinct required gates")
        seen.add(waiver["gate"])
    return policy


def matches(path, patterns):
    # '**/' also matches zero directories. Other semantics are Python fnmatchcase.
    for pattern in patterns:
        while True:
            if fnmatch.fnmatchcase(path, pattern):
                return True
            if not pattern.startswith("**/"):
                break
            pattern = pattern[3:]
    return False


def kind(path):
    name = path.name
    if name == "pom.xml":
        return "maven"
    if name in {"build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts"}:
        return "gradle"
    if name == "build.xml":
        return "ant"
    if path.suffix == ".sbt":
        return "sbt"
    if path.suffix in {".java", ".kt", ".scala", ".groovy"}:
        return "source"
    return "configuration" if text_candidate(path) else "resource"


def text_candidate(path):
    return path.suffix.lower() in SUFFIXES or path.name in NAMES or path.name.startswith("Dockerfile.")


def pom_metadata(content):
    # Never resolve external entities, parents, repositories, profiles, or properties.
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", content, re.I):
        raise ValueError("XML DTD/entity declarations are unsupported")
    tree = ET.fromstring(content)
    for element in tree.iter():
        element.tag = element.tag.rsplit("}", 1)[-1]
    coordinates = []
    for element in tree.iter():
        if element.tag in {"dependency", "plugin", "parent"}:
            coordinates.append({"kind": element.tag, **{
                key: (element.findtext(key) or "").strip()
                for key in ("groupId", "artifactId", "version", "scope", "type")}})
    properties = tree.find("properties")
    return {"declared_coordinates": coordinates,
            "modules": [item.text or "" for item in tree.findall("./modules/module")],
            "java_properties": {item.tag: item.text or "" for item in properties
                                if item.tag in {"java.version", "maven.compiler.source",
                                                "maven.compiler.target", "maven.compiler.release"}}
            if properties is not None else {}}


def inventory(root, policy):
    scope = policy["scope"]
    files, findings, warnings = [], [], []
    excluded = HARD_EXCLUDES | set(scope["exclude_dirs"])

    def warn(path, reason):
        warnings.append({"path": path, "reason": reason})

    def walk_error(error):
        warn(os.path.relpath(error.filename or root, root), "directory could not be read")

    stopped = False
    considered = 0
    for parent, dirs, names in os.walk(root, followlinks=False, onerror=walk_error):
        parent = Path(parent)
        kept = []
        for name in sorted(dirs):
            relative = (parent / name).relative_to(root).as_posix()
            if name in excluded or matches(relative, scope["exclude"]) or matches(relative + "/", scope["exclude"]):
                continue
            if (parent / name).is_symlink():
                warn(relative, "symlink directory not followed; scope explicitly if reviewed elsewhere")
            else:
                kept.append(name)
        dirs[:] = kept
        for name in sorted(names):
            path = parent / name
            relative = path.relative_to(root).as_posix()
            if not matches(relative, scope["include"]) or matches(relative, scope["exclude"]):
                continue
            if considered >= scope["max_files"]:
                warn(relative, "file count limit exceeded")
                stopped = True
                break
            considered += 1
            try:
                info = path.lstat()
                if not stat.S_ISREG(info.st_mode):
                    warn(relative, "non-regular file or symlink not read")
                    continue
                if info.st_size > scope["max_file_bytes"]:
                    warn(relative, "file size limit exceeded")
                    continue
                with open_regular(path) as stream:
                    info = os.fstat(stream.fileno())
                    data = stream.read(scope["max_file_bytes"] + 1)
                if len(data) > scope["max_file_bytes"]:
                    warn(relative, "file size limit exceeded during read")
                    continue
                item = {"path": relative, "sha256": hashlib.sha256(data).hexdigest(),
                        "bytes": len(data), "kind": kind(path),
                        "executable": bool(info.st_mode & 0o111)}
                files.append(item)
                if not text_candidate(path):
                    continue
                content = data.decode("utf-8-sig")
                if "\x00" in content:
                    raise ValueError("binary data in text candidate")
                if item["kind"] == "maven":
                    item.update(pom_metadata(content))
                for rule, severity, pattern, message in RULES:
                    match = pattern.search(content)
                    if match:
                        findings.append({"rule": rule, "severity": severity, "path": relative,
                                         "line": content.count("\n", 0, match.start()) + 1,
                                         "message": message})
            except (OSError, UnicodeError, ValueError, ET.ParseError) as error:
                reason = "unreadable file" if isinstance(error, OSError) else "unsupported encoding, binary content, or invalid XML"
                warn(relative, reason)
        if stopped:
            break
    result = {"schema_version": 1, "policy_sha256": digest(policy),
              "scan_complete": not warnings, "files": sorted(files, key=lambda x: x["path"]),
              "findings": sorted(findings, key=lambda x: (x["path"], x["rule"])),
              "warnings": sorted(warnings, key=lambda x: (x["path"], x["reason"]))}
    result["inventory_sha256"] = digest(result)
    return result


def evidence_template(snapshot, policy):
    return {"schema_version": 1, "inventory_sha256": snapshot["inventory_sha256"],
            "policy_sha256": digest(policy), "target_java": policy["target_java"],
            "checks": {gate: {"status": "not_run", "command": "",
                              "java_major": policy["baseline_java"] if gate == "baseline" else policy["target_java"],
                              "summary": "", "artifacts": []} for gate in policy["required_gates"]},
            "remediation": {"reviews": {name: {
                "status": "not_run", "checked_on": "", "summary": "", "artifacts": [],
                "coverage": {scope: "incomplete" for scope in REMEDIATION_SCOPES}}
                for name in ("support", "vulnerabilities")}, "findings": []}}


def artifact_errors(root, artifacts, label):
    errors = []
    for artifact in artifacts:
        relative = Path(artifact["path"])
        path = root / relative
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            errors.append(f"{label}: artifact path must be relative and contained")
            continue
        if any((root / Path(*relative.parts[:index])).is_symlink()
               for index in range(1, len(relative.parts) + 1)):
            errors.append(f"{label}: artifact symlink is unsupported")
            continue
        try:
            if not stat.S_ISREG(path.stat().st_mode) or path.stat().st_size == 0:
                raise ValueError("missing or empty artifact")
            if file_digest(path) != artifact["sha256"]:
                errors.append(f"{label}: artifact digest mismatch")
        except (OSError, ValueError):
            errors.append(f"{label}: artifact missing, empty, or non-regular")
    return errors


def remediation_errors(root, policy, evidence, gate, today):
    ledger = evidence.get("remediation")
    label = f"{gate}: remediation"
    if ledger is None:
        return [f"{label} review is missing"]
    name, kind = ("support", "eol") if gate == "dependencies" else ("vulnerabilities", "vulnerability")
    review = ledger["reviews"][name]
    errors = []
    coverage = review["coverage"]
    if (review["status"] != "complete" or set(coverage) != set(REMEDIATION_SCOPES) or
            any(status == "incomplete" for status in coverage.values()) or
            not review["summary"].strip() or not review["artifacts"]):
        errors.append(f"{label} {name} review/coverage is incomplete")
    try:
        date = dt.date.fromisoformat(review["checked_on"])
        age = (today - date).days
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", review["checked_on"]) or not 0 <= age <= policy["remediation"]["max_review_age_days"]:
            raise ValueError("stale or future date")
    except ValueError:
        errors.append(f"{label} {name} review date is missing, stale or in the future")
    errors.extend(artifact_errors(root, review["artifacts"], label))
    seen = set()
    for finding in ledger["findings"]:
        if finding["kind"] != kind:
            continue
        key = (finding["id"], finding["component"], finding["version"])
        if key in seen:
            errors.append(f"{label} duplicate finding {finding['id']}")
        seen.add(key)
        if finding["status"] == "open":
            errors.append(f"{label} open {kind}: {finding['component']}@{finding['version']} ({finding['id']})")
        elif (not finding["summary"].strip() or not finding["artifacts"] or
              finding["status"] == "fixed" and not finding["replacement"].strip()):
            errors.append(f"{label} {finding['id']} disposition needs summary, artifacts and a fixed replacement")
        errors.extend(artifact_errors(root, finding["artifacts"], label))
    return errors


def check_evidence(root, policy, evidence):
    validate(evidence, load_json(ASSETS / "evidence.schema.json"))
    current = inventory(root, policy)
    errors, accepted_waivers = [], []
    if evidence["policy_sha256"] != digest(policy):
        errors.append("policy changed; regenerate and review evidence")
    if evidence["inventory_sha256"] != current["inventory_sha256"]:
        errors.append("project inventory changed; regenerate and review evidence")
    if evidence["target_java"] != policy["target_java"]:
        errors.append("evidence target does not match policy")
    if not current["files"] or not current["scan_complete"]:
        errors.append("inventory is empty or incomplete; resolve warnings and scope")
    elif not any(item["kind"] != "resource" for item in current["files"]):
        errors.append("inventory has no recognized source/build/configuration inputs; review root and scope")
    waivers = {item["gate"]: item for item in policy["waivers"]}
    today = dt.datetime.now(dt.timezone.utc).date()
    for gate in policy["required_gates"]:
        check = evidence["checks"].get(gate)
        if check is None:
            errors.append(f"{gate}: missing evidence")
            continue
        if check["status"] == "waived":
            waiver = waivers.get(gate)
            if not waiver or dt.date.fromisoformat(waiver["expires"]) < today:
                errors.append(f"{gate}: waiver missing or expired")
            else:
                accepted_waivers.append(waiver)
            continue
        if check["status"] != "passed":
            errors.append(f"{gate}: {check['status']}")
            continue
        if not check["command"].strip() or not check["summary"].strip() or not check["artifacts"]:
            errors.append(f"{gate}: passed check needs command, summary, and artifacts")
        expected = policy["baseline_java"] if gate == "baseline" else policy["target_java"]
        if check["java_major"] != expected:
            errors.append(f"{gate}: expected Java {expected} evidence")
        errors.extend(artifact_errors(root, check["artifacts"], gate))
        if gate in {"dependencies", "security"}:
            errors.extend(remediation_errors(root, policy, evidence, gate, today))
    return {"status": "blocked" if errors else "passed_with_waivers" if accepted_waivers else "passed",
            "errors": errors, "waivers": accepted_waivers,
            "inventory_sha256": current["inventory_sha256"],
            "policy_sha256": digest(policy),
            "limitation": "Validates declared evidence and local artifact integrity, not test truth or production certification."}


def handoff_template(stage, snapshot, policy):
    following = {"assess": "plan", "plan": "execute", "execute": "validate", "validate": "summary"}.get(stage)
    next_step = (f"Use the java-renew skill to {following} this project. Read "
                 f".java-modernize/{STAGES[stage]}.md and its JSON handoff first; "
                 "use .java-modernize/policy.json as the final policy override."
                 if following else "Resolve any blockers and review the recorded scope, exceptions, and rollout/rollback procedure before release.")
    return {"schema_version": 1, "stage": stage, "status": "in_progress",
            "inventory_sha256": snapshot["inventory_sha256"], "policy_sha256": digest(policy),
            "summary": "Stage work has not yet been recorded.", "versions": [], "findings": [],
            "decisions": [], "changes": [], "validation": [], "blockers": [], "next_steps": [next_step]}


def render_report(root, policy, handoff, evidence=None):
    validate(handoff, load_json(ASSETS / "handoff.schema.json"))
    snapshot = inventory(root, policy)
    if handoff["inventory_sha256"] != snapshot["inventory_sha256"] or handoff["policy_sha256"] != digest(policy):
        raise ValueError("stale handoff: review changed project/policy before regenerating the stage report")
    gate = check_evidence(root, policy, evidence) if evidence is not None else None
    stage, status = handoff["stage"], handoff["status"]
    if stage in {"validate", "summary"} and status == "complete" and gate is None:
        raise ValueError("complete validate/summary reports require --evidence; otherwise use in_progress or blocked")
    has_inputs = any(item["kind"] != "resource" for item in snapshot["files"])
    if ((gate and gate["errors"]) or not snapshot["scan_complete"] or not has_inputs or
            handoff["blockers"]):
        status = "blocked"
    label = "complete with waivers" if status == "complete" and gate and gate["waivers"] else status
    lines = [f"# Java Renew — {stage}", "", f"Status: **{label}**", "",
             f"Runtime: Java {policy['baseline_java']} → {policy['target_java']}; "
             f"default source/API release: {policy['source_release']}.", "", handoff["summary"], ""]
    if stage == "execute":
        lines.extend(["Implementation status only. Full validation is a separate stage; this report alone does not establish readiness.", ""])

    def section(title, items, empty):
        lines.extend([f"## {title}", ""])
        lines.extend([f"- {item}" for item in items] if items else [empty])
        lines.append("")

    def cell(value):
        return value.replace("|", "\\|").replace("\n", " ").replace("\r", " ")

    lines.extend(["## Versions and sources", ""])
    if handoff["versions"]:
        lines.extend(["| Component | Before | Selected | Source | Checked |", "| --- | --- | --- | --- | --- |"])
        for item in handoff["versions"]:
            lines.append("| " + " | ".join(cell(item[key]) for key in ("component", "before", "after", "source", "checked_on")) + " |")
    else:
        lines.append("Version selection has not been recorded.")
    lines.append("")
    for field, title, empty in [
        ("findings", "Findings and impact", "No reviewed findings recorded."),
        ("decisions", "Decisions and migration route", "No decisions recorded."),
        ("changes", "Changes", "No implementation changes recorded."),
        ("validation", "Validation", "No validation results recorded."),
        ("blockers", "Blockers and risks", "No blockers recorded; this is not proof of readiness."),
    ]:
        section(title, handoff[field], empty)
    lines.extend(["## Evidence gate", ""])
    if gate:
        lines.extend([f"Result: **{gate['status']}**.", ""])
        lines.extend([f"- {item}" for item in gate["errors"]])
        for item in gate["waivers"]:
            lines.append(f"- Waiver: {item['gate']}; {item['owner']}; expires {item['expires']}; {item['ticket']}: {item['reason']}")
    else:
        lines.append("Not supplied. No claim of verified execution.")
    if evidence and evidence.get("remediation"):
        ledger = evidence["remediation"]
        lines.extend(["", "## EOL and vulnerability remediation", ""])
        for name, review in ledger["reviews"].items():
            lines.append(f"- {name}: {review['status']}; checked {review['checked_on'] or 'not recorded'}.")
        findings = ledger["findings"]
        counts = {status: sum(item["status"] == status for item in findings) for status in ("open", "fixed", "not_affected")}
        lines.append(f"- Findings: {counts['fixed']} fixed; {counts['open']} open; {counts['not_affected']} not affected. See the evidence manifest for dispositions and artifacts.")
        for finding in [item for item in findings if item["status"] == "open"][:5]:
            lines.append(f"- Open {cell(finding['kind'])}: {cell(finding['component'])}@{cell(finding['version'])}; {cell(finding['id'])}.")
    lines.extend(["", "Required gates: " + ", ".join(f"`{item}`" for item in policy["required_gates"]) + ".", "",
                  "The gate checks declared evidence and artifact integrity; review actual test results and release approvals.", ""])
    lines.extend(["## Handoff integrity", "", f"- Inventory: `{snapshot['inventory_sha256']}`",
                  f"- Policy: `{digest(policy)}`",
                  f"- Scoped files: {len(snapshot['files'])}; lexical signals: {len(snapshot['findings'])}.",
                  "- Fingerprints cover the configured scan scope, not all external build/deployment inputs.", ""])
    inventory_warnings = [f"`{item['path']}`: {item['reason']}" for item in snapshot["warnings"]]
    if not snapshot["files"]:
        inventory_warnings.append("Inventory is empty; review the project root and configured scope.")
    elif not has_inputs:
        inventory_warnings.append("No recognized source/build/configuration inputs; review the project root and configured scope.")
    if inventory_warnings:
        section("Inventory warnings", inventory_warnings, "")
    if stage == "assess" and snapshot["findings"]:
        lines.extend(["## Automated triage signals", "", "Review these candidates; they are not confirmed defects.", "",
                      "| Severity | Rule | Location | Review action |", "| --- | --- | --- | --- |"])
        triage = sorted(snapshot["findings"], key=lambda item: ({"high": 0, "medium": 1, "info": 2}[item["severity"]], item["path"], item["rule"]))
        for item in triage[:25]:
            lines.append("| " + " | ".join(cell(str(value)) for value in
                         (item["severity"], item["rule"], f"{item['path']}:{item['line']}", item["message"])) + " |")
        lines.append("")
        if len(triage) > 25:
            lines.extend([f"Showing 25 of {len(triage)} signals; see `.java-modernize/inventory.json` for all candidates.", ""])
    section("Next step", handoff["next_steps"], "No next step recorded.")
    return "\n".join(lines), 1 if status == "blocked" else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["config", "inventory", "evidence-template", "gate", "report-template", "report"])
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="project root (default: cwd)")
    parser.add_argument("--override", action="append", default=[], help="JSON policy layer; repeat in precedence order")
    parser.add_argument("--evidence", type=Path, help="evidence manifest (gate or report)")
    parser.add_argument("--stage", choices=STAGES, help="stage for report-template")
    parser.add_argument("--handoff", type=Path, help="completed JSON handoff for report")
    args = parser.parse_args(argv)
    try:
        root = args.root.resolve(strict=True)
        if not root.is_dir():
            raise ValueError("root must be a directory")
        policy = resolve_policy(root, args.override)
        code = 0
        if args.command == "config":
            result = policy
        elif args.command == "report":
            if not args.handoff:
                raise ValueError("report requires --handoff")
            report, code = render_report(root, policy, load_json(args.handoff),
                                         load_json(args.evidence) if args.evidence else None)
            print(report)
            return code
        elif args.command == "gate":
            if not args.evidence:
                raise ValueError("gate requires --evidence")
            result = check_evidence(root, policy, load_json(args.evidence))
            code = 1 if result["errors"] else 0
        else:
            snapshot = inventory(root, policy)
            if args.command == "report-template":
                if not args.stage:
                    raise ValueError("report-template requires --stage")
                result = handoff_template(args.stage, snapshot, policy)
            else:
                result = snapshot if args.command == "inventory" else evidence_template(snapshot, policy)
            code = 1 if not snapshot["scan_complete"] else 0
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=True))
        return code
    except (OSError, ValueError, RecursionError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
