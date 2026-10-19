# Modernize Java

A portable Java 8–25 modernization skill for coding agents. It handles build
toolchains, common dependencies/frameworks, Jakarta transitions, runtime changes,
tests, deployment packaging, and evidence for enterprise review.

**Assess → plan → execute → validate → summary.** Every stage leaves readable
Markdown and structured JSON that the next stage can consume. You can stop after
any stage, resume in a new session, or request the entire migration.

The package uses the open [Agent Skills format](https://agentskills.io/specification),
JSON Schema 2020-12, and Apache-2.0 licensing. Optional helpers use only Python
3.10+ standard libraries. No hosted service, paid recipe engine, or Python package
installation is required.

## Use it

Install the **entire** [skills/modernize-java](skills/modernize-java) directory in
your agent's supported skill location. For repository-local discovery in clients
that support it, copy it to `<your-project>/.agents/skills/modernize-java/`.
For user-wide installations use the client's documented skill directory. Keep the
folder name `modernize-java`, with `SKILL.md` directly inside it. The optional
`agents/openai.yaml` adds UI metadata; other clients can ignore it.

Open the target repository in the coding agent, then invoke:

```text
Use $modernize-java assess this project for Java 8 to Java 25.
Use $modernize-java plan from .java-modernize/01-assessment.md.
Use $modernize-java execute .java-modernize/02-plan.md.
Use $modernize-java validate from .java-modernize/03-execution.md.
Use $modernize-java summary for this migration.
```

Or request the full workflow:

```text
Use $modernize-java to upgrade this project from Java 8 to Java 25.
Run assess, plan, execute, validate, and summary, saving the Markdown handoffs.
```

These are agent instructions, not shell commands. The agent performs the migration
and runs the project's compiler/tests. The helper provides deterministic policy,
inventory, evidence checks, and report rendering; it does not rewrite Java or
execute build/manifest commands by itself.

## Handoffs

| Stage | Report in the target project's `.java-modernize/` | Outcome |
| --- | --- | --- |
| Assess | `01-assessment.md` | Current state, compatibility risks, baseline, feasibility and unknowns. |
| Plan | `02-plan.md` | Version choices and sources, ordered changes, test criteria, risks and rollback approach. |
| Execute | `03-execution.md` | Implemented changes, deviations and focused development checks. |
| Validate | `04-validation.md` | Clean compile/package, unit/integration tests, runtime checks and other required gates. |
| Summary | `05-summary.md` | Readable upgrade outcome, important changes, validation status and next actions. |

Matching `.json` files preserve decisions, sources, next steps and policy/source
fingerprints. Validation additionally produces `evidence.json` and linked logs.
Reports clearly distinguish implementation completion, verification, blockers and
waivers. See the [phase contract](skills/modernize-java/references/phases.md).

## Override each use

Put shared constraints in the target project's `.java-modernize.json`, then add
explicit per-use JSON overrides. Example for a library that must keep Java 17
APIs/bytecode while being tested on Java 25:

```json
{
  "baseline_java": 8,
  "target_java": 25,
  "source_release": 17,
  "framework_policy": "compatible"
}
```

Ask the agent to honor that file, or pass it to the helper using `--override`.
Objects merge; arrays replace. Later overrides win. Exact dependency pins,
scope filters, custom gates and owned, expiring waivers are supported. A conflict
with Java/framework support is reported, never silently ignored. Save the resolved
policy in `.java-modernize/policy.json` to carry per-use choices to the next stage.
See [policy reference](skills/modernize-java/references/configuration.md) and
[schema](skills/modernize-java/assets/config.schema.json).

## Helpers

Run these from the **target project**, replacing `<skill>` with the actual skill
installation path. They only read inputs and print output:

```bash
mkdir -p .java-modernize
python3 <skill>/scripts/modernize.py config --root . > .java-modernize/policy.json
python3 <skill>/scripts/modernize.py inventory --root . > .java-modernize/inventory.json
python3 <skill>/scripts/modernize.py report-template --root . --stage assess \
  > .java-modernize/01-assessment.json
# The agent fills that JSON from reviewed findings, then renders it:
python3 <skill>/scripts/modernize.py report --root . \
  --handoff .java-modernize/01-assessment.json > .java-modernize/01-assessment.md
```

Use `--override company-policy.json --override run-policy.json` on **each** command
when supplying override layers. During validation:

```bash
python3 <skill>/scripts/modernize.py evidence-template --root . \
  > .java-modernize/evidence.json
# Fill from real results, command/JDK details and hashes of reviewed artifacts.
python3 <skill>/scripts/modernize.py gate --root . \
  --evidence .java-modernize/evidence.json
python3 <skill>/scripts/modernize.py report --root . \
  --handoff .java-modernize/04-validation.json \
  --evidence .java-modernize/evidence.json > .java-modernize/04-validation.md
```

Generate the validation handoff with `report-template --stage validate` after
implementation, then fill it with actual results. All templates start unfinished;
they do not claim tests passed. Source/policy changes invalidate stale handoffs.
Exit codes: `0` success, `1` incomplete/blocked, `2` invalid input. Reports can
still be emitted for blocked work; preserve the command's exit code.

## Enterprise scope

The workflow covers BOM alignment, private repositories, application-server
certification, mixed languages, agents/processors, consumer compatibility,
security/SBOM/license checks, performance, CI/container changes and rollback.
It preserves existing corporate conventions and records unsupported combinations
instead of forcing arbitrary major upgrades. Tool and recipe licenses are checked
separately; Java 25 recipe use is optional.

The scanner is bounded lexical triage, not a dependency resolver or complete
static analyzer. The evidence gate checks self-declared results and artifact
integrity, not test truth, signed provenance, or production certification. Real
compiler/tests and trusted CI remain necessary. This repository supplies a
reusable engineering workflow, not a vendor support contract or support SLA.
See [validation details](skills/modernize-java/references/verification-and-rollout.md).

## Maintain and test

For a pinned Java/Maven/Gradle environment and the full automated build matrix:

```bash
docker compose up --build --abort-on-container-exit --exit-code-from checks
docker compose cp checks:/reports/. ./check-reports
```

See [container usage](docker/README.md) for exact tool versions, JDK selection,
offline reruns, report locations and single-image commands. It includes real
Maven/Gradle smoke builds on Java 17, 21 and 25; AI-agent evaluations remain a
separate workflow.

For the Python tests directly:

```bash
python3 -m unittest discover -s tests -v
git diff --check
```

CI runs the helper tests on Python 3.10, 3.12 and 3.14. Tests cover policy layering,
Maven/Gradle triage, incomplete scans, artifact integrity, waiver expiry, stage
continuation and Markdown generation. Synthetic evidence fixtures test the gate;
they are not evidence of a real Java 25 application migration. Keep version
recommendations verified at use time against the primary sources linked from the
skill references, rather than expanding a stale fixed-version catalog.

The self-contained [test corpus](testdata/README.md) includes eight locally
maintained scenarios with a local checksum manifest for reproducible inputs.
Regression tests run offline on disposable copies. Each case also defines
semantic acceptance criteria for evaluating future skill abilities; those require
real agent/build results. Optional JDK smoke tests compile four standalone classes
without dependency downloads. Corpus data stays outside the installable skill.

Original project content is licensed under [Apache-2.0](LICENSE). The existing
[fixture content's license status](testdata/README.md#fixture-license-status)
remains unspecified; external tools retain their own licenses.
