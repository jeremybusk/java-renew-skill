# Verification, evidence and rollout

Scale test selection to the affected system. A reusable skill cannot establish an
organization's acceptance thresholds, certification, commercial support contract
or production change authorization. Reuse the project's established gates and
record explicit scoped exceptions rather than claiming those guarantees.

## Required gate meanings

| Gate | Minimum useful evidence |
| --- | --- |
| `baseline` | Existing JDK/vendor/patch, exact command and exit status, module/profile/test counts, known failures and representative behavior/performance before changes. |
| `build` | Clean full affected build, actual launcher/compiler toolchains, release/classfile checks and resolved plugin versions; no compiler failures hidden by flags. |
| `unit` | Tests actually discovered and run, assertions, failures/errors/skips and coverage delta; compare with baseline and explain any decrease. |
| `integration` | Relevant database, messaging, HTTP, identity and server integrations; production-like versions and disposable data. Capture test/container versions and profiles. |
| `runtime` | Final packaged artifact/image starts on the exact target JDK with production-like flags, agents, native libraries, probes, resource limits and graceful termination. |
| `dependencies` | Effective resolved dependency/plugin/processor/agent trees and compatibility matrix with exact versions and versioned primary sources; identify every unsupported combination and temporary bridge. |
| `security` | Organization-approved SCA/container scan and license review, current advisory data, truststore/TLS/identity tests and no security downgrades. Produce an SBOM in CycloneDX or SPDX through existing approved tooling where available. An SBOM alone is not a vulnerability assessment. |
| `compatibility` | API/wire/database/serialization fixtures, reflection/native/module diagnostics and, for libraries, minimum-runtime consumer tests and ABI comparison. Document every lexical finding's disposition, including false positives. |
| `performance` | Comparable baseline/target load with warmup, throughput, p95/p99 latency, errors, startup, CPU/RSS/heap/GC, resource limits and workload details. Apply the system's SLO/regression budget; do not invent a universal acceptable percentage. |
| `rollback` | Previous immutable artifact/image retained; configuration, flags, truststore and schema compatibility assessed; controlled rollback rehearsal or verifiable procedure with triggers, owner and irreversibility limits. |

The baseline check's `java_major` is `baseline_java`; every other check names
`target_java` as the migration's evaluated runtime context. This is a declaration,
not detection: record auxiliary compiler JDKs, library minimum-runtime tests,
and non-Java scanners in the command/summary and underlying reports. Multi-JDK
jobs should include version output for every involved process.

For checkpoints, rerun the affected build/tests before proceeding. At final
verification run the clean build and production-relevant matrix. Capture actual
exit codes with the project's CI/logging conventions, and check zero-test success,
skipped profiles, flaky retries and ignored failures explicitly. Adding a new
test engine must not silently strand the old tests.

## Evidence manifest

Keep all generated artifacts in `.java-modernize/` so reports do not invalidate
their own source fingerprint. Review before committing any reports; they can
contain private coordinates, paths, endpoints and test data. Source snippets and
environment variables are not included by the inventory helper. Test tools can
still log credentials; redact sensitive output before recording artifact hashes.

After source/config is final, run `evidence-template`. Each check starts as
`not_run`. Fill it from actual results; example check (hash is illustrative):

```json
{
  "status": "passed",
  "command": "./mvnw -B clean verify",
  "java_major": 25,
  "summary": "412 tests; 0 failures; 0 errors; 3 explained skips. JDK and profile details in log.",
  "artifacts": [{"path": ".java-modernize/verify.log", "sha256": "<actual SHA-256 of the reviewed log>"}]
}
```

Use a file hashing utility or Python's `hashlib.file_digest` where available.
Artifact paths are relative to the project root. They must be nonempty regular
local files, without traversal or symlinks. Commands are descriptive strings and
are never executed by the gate. Attach structured test/scan reports and the
trusted CI run identity in addition to logs when available; arbitrary nonempty
files and self-declared statuses cannot prove a test actually passed.

The gate recomputes the current bounded inventory and effective policy, compares
both hashes to the manifest, verifies declared Java majors, required statuses,
artifact hashes and UTC waiver expiry. Changed included source/config, policy,
missing artifacts, absent checks, stale hashes, a failed/not-run status or an
incomplete/empty inventory block the gate. A valid explicit waiver produces
`passed_with_waivers`, never an unqualified pass. It checks only `required_gates`;
list any removed gates and do not bury a relevant failure in an optional check.

This is **local consistency checking**, not signed attestation, test execution,
build provenance, or tamper resistance against an author who can rewrite the
manifest and artifacts. Trust CI identities and approved provenance tooling for
those assurances. The source fingerprint covers selected UTF-8/config candidates,
not all repository bytes, external parents, repository servers, environment,
untracked binary dependencies or container layers. Record resolved external inputs
and final artifact/image digests separately. Reproduce on a clean trusted runner.

## Delivery and rollout

The Markdown stage reports described in `references/phases.md` are the handoff.
Record a compatibility matrix; exact before/after versions and support sources;
change rationale; commands and module/profile/test counts; diagnostic dispositions;
open risks and expiring exceptions; immutable artifact references and rollout plan.
Report unavailable JDKs/services/private repositories as unverified work.

Update CI runners, toolchain caches, Docker/multi-stage images, buildpacks,
deployment charts/manifests, VM/systemd scripts, developer instructions and
application-server settings that actually own the runtime. Pin approved base
image digests, check CA/font/timezone/native contents, and run as the expected
non-root user. Rebuild CDS/AOT/custom `jlink` images using the actual target JDK;
do not reuse incompatible cached runtime artifacts.

Recommend canary or staged rollout with existing health/error/latency/resource
metrics and explicit rollback triggers. Check mixed-version cluster/cache/session
compatibility and schema forward/backward compatibility **before** rollout.
Prefer expand/contract database changes when changes are necessary. A binary
rollback cannot reverse destructive schema or irreversible message/data writes.
Publishing, production deployment and external changes require the task's actual
authorization; a verified report does not grant it.
