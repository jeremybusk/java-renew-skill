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
| `dependencies` | Effective graphs and support matrix for runtime/test/tooling/processor/agent/container inputs, exact versions and dated primary sources. Complete the support review and close EOL findings with verified replacements or applicable support evidence. |
| `security` | Complete advisory coverage and close known vulnerabilities at every severity, with final resolved artifact/image rescans. Retain organization SCA/container/license/TLS requirements. An SBOM alone is not a vulnerability assessment. |
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

Follow [remediation](remediation.md). Populate the template's structured support
and vulnerability reviews, coverage and findings; keep unresolved findings open.
The gate blocks declared dependency/security passes if their review is missing,
stale/incomplete or has open findings. Recheck the final resolved versions and
resource targets after fixes. A dated report with zero discovered packages does
not establish advisory coverage; absent application dependencies do not remove
the build launcher's/plugin graph from scope.

### Optional OSV dependency check

When available and permitted, use `osv-scanner scan source -r <project>` as
additional dependency vulnerability evidence. Preserve JSON with `--format json
--all-packages --output-file <report.json>`, actual exit status, diagnostics,
scanner version, UTC scan date, discovered package coverage and advisory IDs.
Findings, scanner/network errors and zero discovered packages are distinct results;
never report any of these as a clean security pass. Implement in-scope fixes per
remediation policy; pins or unavailable fixes become explicit blockers. Keep the
requested Java target and consumer baseline.

Maven POM transitive resolution uses external services by default, can differ from
the effective build and omits test dependencies. Compare its package set with the
actual resolved graph. Scan a build-generated CycloneDX/SPDX SBOM or supported
resolved lockfile as well when the POM scan is insufficient, including managed,
private, test and Gradle graphs. Ordinary Gradle build scripts alone do not provide
resolved dependency coverage. Honor organization policy for sending coordinates
to public services. Offline scans need a dated, retained advisory database;
offline Maven resolution does not recover the full transitive graph.

OSV does not itself establish the complete `security` gate. Retain existing
organization SCA, license, TLS/identity and release requirements. See official
[source scanning](https://google.github.io/osv-scanner/usage/scan-source),
[supported Java inputs](https://google.github.io/osv-scanner/supported-languages-and-lockfiles/)
and [offline behavior](https://google.github.io/osv-scanner/usage/offline-mode/).

### Record actual evidence

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
incomplete/empty inventory block the gate. A scope containing only opaque
resources, with no recognized source/build/configuration inputs, also blocks it.
A valid explicit waiver produces
`passed_with_waivers`, never an unqualified pass. It checks only `required_gates`;
list any removed gates and do not bury a relevant failure in an optional check.

This is **local consistency checking**, not signed attestation, test execution,
build provenance, or tamper resistance against an author who can rewrite the
manifest and artifacts. Trust CI identities and approved provenance tooling for
those assurances. The source fingerprint covers all files within configured scope,
including opaque resources and executable permissions. Excluded directories/files,
external parents, repository servers, environment, external binary dependencies
and container layers remain outside that fingerprint. Record resolved external inputs
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
