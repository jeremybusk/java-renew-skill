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
| `framework_policy` | `preserve`: keep the current line, report incompatible constraints; `compatible`: minimum supported changes; `current-supported`: select an actively supported compatible line after checking policy. None means blindly choose the newest version. |
| `allow_preview` | Default false. If true, source and target must match; prove packaging/runtime flags and exact release compatibility. |
| `dependency_pins` | Exact `group:artifact` → version constraints; no snapshots, ranges, wildcards, property references, or moving aliases. Verify compatibility/security; conflicting pins are blockers, not permission to override a BOM silently. |
| `scope` | File triage limits and filters; does not define all deployment verification. |
| `required_gates` | Named evidence checks; arrays replace. Defaults cover ten enterprise concerns. Removing checks narrows the claim and must appear in the report. Custom names work. |
| `waivers` | Explicit owned, dated exceptions for required checks; never generated to bypass a failure without user authorization. |

## Scanner boundaries

Patterns use case-sensitive Python `fnmatchcase` on POSIX relative paths; `*` can
match `/`, and a leading `**/` also matches zero directories. These are not
gitignore patterns. Exclude directory trees with `legacy/**` and individual
files with their relative paths. `exclude_dirs` matches directory basenames
at any depth; replace the default array when needed.

The scanner always excludes `.git`, `.hg`, `.svn`, `.aws`, `.ssh`, `.codex`,
`.agents`, and `.java-modernize`. It ignores noncandidate suffixes, does not obey
gitignore, follows no discovered symlinks, and does not evaluate build scripts.
An explicitly supplied root may itself resolve through a symlink. UTF-8 source
and build/configuration candidates are hashed; Maven metadata is **declared**,
not an effective POM or resolved graph. Directory errors, symlinks, malformed
POMs, other encodings, and configured size/count limits produce warnings and an
incomplete scan. Review elsewhere and narrow scope explicitly, or fix the cause.
Do not suppress a warning by presenting a partial scan as repository coverage.

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
