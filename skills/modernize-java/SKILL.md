---
name: modernize-java
description: Assess, plan, and implement Java 8 through Java 25 migrations, including Maven/Gradle builds, framework and dependency compatibility, Jakarta transitions, tests, containers, and runtime behavior. Use for Java upgrades or failed migrations; also supports libraries retaining an older bytecode baseline.
license: Apache-2.0
metadata:
  version: "1.0.0"
  runtime: "Optional helpers: Python 3.10+. Migration: project-appropriate JDKs and build tools."
---

# Modernize Java

Deliver a working, reviewable migration with evidence of what ran and what remains
unverified. Default destination: Java 25, with only the framework/dependency changes
needed to reach a supported combination. Modern syntax and architecture changes
are separate choices. An assessment or plan request authorizes those deliverables,
not implementation.

## Establish the contract

Choose the requested stage: **assess → plan → execute → validate → summary**.
Read [phases and Markdown handoffs](references/phases.md) for stage inputs,
canonical output paths, continuation rules, and the report renderer. A whole
migration request runs all five stages. Each stage writes a concise Markdown
report plus structured JSON, including blockers and a concrete next invocation.
Execution completion means implementation is done; only validation establishes
the tested result. Summary can describe either a verified or partial migration.

1. Read repository instructions and build/deployment conventions. Identify the
   requested scope and preserve existing work. Work in an isolated checkout when
   useful; do not reset, stash, commit, publish, or deploy unrelated work.
2. Resolve defaults → project `.java-modernize.json` → explicit `--override` files
   in order → the user's explicit instructions for this use. Materialize user
   overrides in a temporary JSON layer so tooling and reports agree. Read
   [configuration](references/configuration.md) for precedence, pinning, and waivers.
   Never silently relax a failing gate. Existing authorization is sufficient for
   ordinary implementation; a plan is not an additional approval ceremony.
3. Distinguish **build launcher JDK**, **compiler JDK**, **source/API/bytecode
   release**, **test JVM**, and **deployment JVM**, per module. Defaults need not
   match library consumer constraints. Record vendor, patch, OS, architecture,
   application server, licensing/support requirements, and deployment model.

## Discover before selecting versions

Run the bundled read-only helpers using their actual installed path:

```bash
python3 <skill>/scripts/modernize.py config --root <project>
python3 <skill>/scripts/modernize.py inventory --root <project>
```

Inventory is bounded lexical triage: comments can match; no matches is not a clean
bill of health. Read its warnings. It does not execute builds, resolve dependency
graphs, evaluate Gradle, or inspect binary/shaded artifacts. Follow imports,
parents, modules, included builds, profiles, catalogs, lockfiles, generated code,
CI jobs, startup scripts, images, agents, and vendor deployment configuration.
Inspect relevant excluded/generated trees separately when they affect the artifact.

Capture a baseline on the existing JDK: actual test counts, startup and critical
workflows, resolved runtime dependencies, serialized/API/database contracts,
resource limits, and performance. Preserve existing failures with logs. If a JDK,
private dependency, database, or environment is unavailable, state the blocker and
continue independent work; do not manufacture a successful baseline.

## Choose and implement a compatible route

- Read [JDK migration](references/jdk-migration.md) for version boundaries and
  runtime hazards. Choose direct migration if supported; use 11/17/21 checkpoints
  where they isolate a failure or enable a tool/framework bridge. Intermediate
  releases are checkpoints, not automatically approved production destinations.
- Read [dependency decisions](references/dependencies.md) for the detected stack.
  Verify exact versions against current **versioned primary documentation** and
  the organization's support/security policy. Record source URLs, access date,
  resolved coordinates, BOM owner, Java range, and rationale. A version being
  downloadable or compiling is insufficient evidence of vendor support.
- Read [builds and recipes](references/build-and-recipes.md) for toolchain setup
  and transformations. Upgrade the wrapper/plugins on a JVM they can run on;
  separate launcher and compiler JDKs where the compatibility intersection
  requires it. Prefer the existing BOM/platform over individual version overrides.
- Apply small coherent changes: build/toolchain → compatible dependencies →
  source/API fixes → packaging/CI/runtime. Regenerate owned generated sources.
  Inspect semantic diffs after each recipe batch. Use AST/type-aware changes for
  API migrations; do not globally substitute `javax` or dependency versions.
- Check recipe licenses and inspect the **pinned release's expanded recipe list**.
  A composite can change security checks, language level, frameworks, and Kotlin.
  Select compatible subrecipes or direct edits when its behavior or license does
  not fit this use. No external recipe service or paid product is required.
- Keep compatibility flags specific and temporary with owner, reason, ticket,
  expiry, and removal test. Do not solve migration failures by weakening TLS,
  deleting sandbox checks, disabling tests, or hiding compiler/test failures.

## Validate the result

Read [verification and rollout](references/verification-and-rollout.md). Build and
test with the actual target runtime, final packaging, and production-relevant
agents. Verify test discovery, behavioral contracts, security, and performance;
include all affected modules and supported profiles. Do not require Java 25
bytecode from a library that explicitly retains an older consumer baseline.

Store local reports under the project's `.java-modernize/` directory (never commit
secrets). After the final source/config changes, generate an evidence manifest:

```bash
python3 <skill>/scripts/modernize.py evidence-template --root <project>
python3 <skill>/scripts/modernize.py gate --root <project> --evidence <manifest.json>
```

Fill it from real commands and artifact hashes; include the same overrides on all
commands. The gate checks required statuses, policy/project fingerprints, JDK
claims, artifact integrity, and expiring waivers. It does **not** execute tests,
parse their truth, or certify production readiness. Review the underlying reports;
use trusted CI and organization approvals for release decisions. Revalidate after
changes; do not simply replace fingerprints to make stale evidence pass.

Conclude with changed behavior and files, selected JDK/dependency versions and
sources, baseline versus target test counts, actual command outcomes, unresolved
risks, scoped exceptions, and rollout/rollback steps. Distinguish **assessed**,
**planned**, **implemented but blocked**, **verified**, and **verified with
waivers**. Missing production checks remain explicit; compilation alone never
means the migration is complete. Publish/deploy only within the user's scope.
