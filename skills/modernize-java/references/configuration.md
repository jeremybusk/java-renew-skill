# Policy and per-use overrides

The portable interface is `SKILL.md` in the [Agent Skills format](https://agentskills.io/specification).
The helper interface is JSON, with [JSON Schema 2020-12](https://json-schema.org/draft/2020-12).
`agents/openai.yaml` is optional UI metadata; the workflow does not depend on it.
Policy is an instruction contract for the agent, not a sandbox or build executor.
Stages (`assess`, `plan`, `execute`, `validate`, `summary`) are invocation choices,
not persistent migration constraints; changing stages does not change the policy
fingerprint. `config` prints the merged policy object, suitable for reuse as a
final `--override`; `inventory` and handoffs include its SHA-256 fingerprint.

## Resolve policy

1. Load `assets/defaults.json`.
2. Merge `<project>/.java-modernize.json` if present.
3. Merge repeated `--override <file>` layers, left to right. Paths are relative
   to the helper's working directory, not implicitly to `--root`.
4. Honor explicit instructions for the current use. Save them as a final temporary
   override and pass it to every helper invocation; show the effective policy.

Objects merge recursively; arrays and scalars replace. There is no implicit search
in parent/home directories or environment interpolation. `null`, duplicate keys,
unknown fields, non-finite JSON numbers, invalid ranges, and malformed waivers fail.
To remove one inherited pin, edit its defining layer; an empty object does not
erase a merged map. To clear waivers or exclusions, replace the array with `[]`.
Every layer is validated, including overridden values; typos cannot disappear
silently. Do not store credentials in policy.

## Set target versions in one place

Use `<project>/.java-modernize.json` as the central target file; every helper
loads it automatically. Start from [project-policy.example.json](../assets/project-policy.example.json).
Set `target_java` and `source_release` here, Maven/framework/BOM pins in
`dependency_pins`, and other resources in `resource_targets`. Add a resource by
adding a named entry; no Python or schema changes are needed. Omit unused entries
instead of introducing another build tool or framework.

```json
{
  "target_java": 21,
  "source_release": 17,
  "dependency_pins": {
    "org.springframework.boot:spring-boot-starter-parent": "3.5.16"
  },
  "resource_targets": {
    "maven": {"kind": "tool", "selector": "Maven Wrapper and CI launcher", "version": "3.9.16"},
    "gradle": {"kind": "tool", "selector": "Gradle Wrapper", "version": "8.14.6"},
    "coverage": {"kind": "gradle-plugin", "selector": "org.example.coverage", "version": "1.2.3"}
  }
}
```

These are syntax examples, not current security/support approvals. Select actual
versions using remediation research. Plugin selectors are literal plugin IDs;
JDK selectors identify the compiler/test/deployment role and vendor. Image targets
use `kind: "image"`, a selector such as `Dockerfile final FROM`, and a full image
reference ending in `@sha256:<64 lowercase hex characters>`. Tool/JDK/plugin
versions must be exact; moving aliases, snapshots and version ranges are rejected.
Targets constrain the agent's edits; the offline helper does not install tools,
rewrite manifests or verify their observed versions. Capture those in validation.

Keep a managed artifact's version at its existing owner: use the BOM pin, not
duplicate leaf pins. Conflicting selectors/pins and remediation needs are blockers
to resolve, not permission to silently override them. Reconcile a changed target
file with saved `policy.json` before continuing; a saved final override can retain
old targets. Regenerate affected evidence after changing the effective policy.

Skill-wide defaults live in [defaults.json](../assets/defaults.json). Repository
check-image Maven/Gradle/scanner pins live in `docker/toolchains.lock.json`;
JDK/base-image digests are Dockerfile build arguments. These configure the skill's
test environment, separate from the target application's policy.

```json
{
  "schema_version": 1,
  "baseline_java": 8,
  "target_java": 25,
  "source_release": 17,
  "framework_policy": "compatible",
  "scope": {"include": ["service/**", "pom.xml", ".mvn/**", ".github/**"]}
}
```

This example upgrades the deployment JVM while retaining Java 17 APIs/bytecode.
For a multi-release library, supplement this single default with a per-module
matrix; do not flatten modules to one release. Validate `javac --help` for the
compiler's supported `--release` values. In particular, do not assume a JDK 25
compiler can emit Java 8 bytecode; use an appropriate older compiler toolchain
when necessary, then run the artifact on Java 25.

| Field | Meaning |
| --- | --- |
| `baseline_java` | Existing supported runtime, default 8; set the real baseline. |
| `target_java` | Destination runtime, integer 8–25. Source and baseline cannot exceed it. |
| `source_release` | Default compiler API/bytecode level, default 25; module exceptions must be documented. |
| `framework_policy` | Default `current-supported`: retain a supported secure line or choose one when required. `preserve` constrains the current line; `compatible` limits framework compatibility changes. Remediation still applies; conflicting EOL/security constraints block acceptance. |
| `remediation` | Default `eol: replace`, `vulnerabilities: fix`, `allow_major_upgrades: true`, `max_review_age_days: 1`. `report` for either action disables automatic fixes for that category, not the acceptance checks. All severities and unrated advisories are included. |
| `allow_preview` | Default false. If true, source and target must match; prove packaging/runtime flags and exact release compatibility. |
| `dependency_pins` | Exact `group:artifact` → version constraints; no snapshots, ranges, wildcards, property references, or moving aliases. Verify compatibility/security; conflicting pins are blockers, not permission to override a BOM silently. |
| `resource_targets` | Named exact targets with `kind` (`tool`, `jdk`, `gradle-plugin`, `image`), literal `selector`, and `version`. New named entries need no code changes. Images require digest references. These are constraints, not proof of installation/support/security. |
| `scope` | File triage limits and filters; does not define all deployment verification. |
| `required_gates` | Named evidence checks; arrays replace. Defaults cover ten enterprise concerns. Removing checks narrows the claim and must appear in the report. Custom names work. |
| `waivers` | Explicit owned, dated exceptions for required checks; never generated to bypass a failure without user authorization. |

For a compatibility-only implementation that reports remediation work without
making it, explicitly set:

```json
{
  "framework_policy": "compatible",
  "remediation": {"eol": "report", "vulnerabilities": "report", "allow_major_upgrades": false}
}
```

Unresolved EOL/vulnerability findings and incomplete reviews still block their
acceptance gates. See [remediation](remediation.md) for coverage and evidence.

## Scanner boundaries

Patterns use case-sensitive Python `fnmatchcase` on POSIX relative paths; `*` can
match `/`, and a leading `**/` also matches zero directories. These are not
gitignore patterns. Exclude directory trees with `legacy/**` and individual
files with their relative paths. `exclude_dirs` matches directory basenames
at any depth; replace the default array when needed.

The scanner always excludes `.git`, `.hg`, `.svn`, `.aws`, `.ssh`, `.codex`,
`.agents`, and `.java-modernize`. It does not obey gitignore, follows no discovered
symlinks, and does not evaluate build scripts. An explicitly supplied root may
itself resolve through a symlink. Every scoped regular file is fingerprinted by
content and executable permission, including launchers, lockfiles, extensionless
service descriptors, database migrations and binary resources. Recognized UTF-8
source/build/configuration files additionally receive lexical triage; other files
are opaque resources and are never decoded. Maven metadata is **declared**, not
an effective POM or resolved graph.

Size/count limits apply to all scoped files, including opaque resources. Directory
errors, symlinks, malformed POMs, unsupported encodings in text candidates, and
exceeded limits produce warnings and an incomplete scan. Common generated/cache
directories are excluded by default, including `target`, `build`, `.gradle`,
`.m2` and `__pycache__`. Review large/generated resources elsewhere and narrow
scope explicitly, or increase the configured limits within the schema's bounds.
Do not suppress a warning by presenting a partial scan as repository coverage.

Version 1.2 broadens the fingerprint contract. Earlier inventories, evidence and
handoffs must be regenerated after reviewing the newly covered inputs. JSON
policy, handoff and evidence inputs must be regular files, not symlinks or special
files, and are limited to 16 MiB. The helper checks the opened file's type before
reading; commands embedded in inputs are never executed.

## Evidence exceptions

```json
{
  "waivers": [{
    "gate": "performance",
    "owner": "payments-platform",
    "reason": "Load environment unavailable; isolated replay passed",
    "ticket": "CHANGE-1234",
    "expires": "2026-12-01"
  }]
}
```

The date is illustrative; use a short real expiry. Set that evidence check to
`waived`; a waiver does not turn `failed` into `passed`. Expiry uses the UTC date,
inclusive of the expiry day. Policy must contain one waiver per waived gate;
unknown/duplicate gates fail. A policy change invalidates existing evidence.
Waivers and reduced gates are visible scope exceptions, not production approvals.

Exit codes: `0` resolved config/complete inventory/accepted evidence; `1` incomplete
inventory or blocked gate/report; `2` invalid input or operational error. Output is
JSON on stdout, except `report` prints Markdown and input errors print JSON on
stderr. Helpers write no files, start no
processes, download nothing, and never execute manifest commands. The bundled
validator implements only the keyword subset used by its own schemas; use a full
2020-12 validator for independently extended schemas.
