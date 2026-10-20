# Evaluate the modernization skill

The repository has three complementary test layers:

| Layer | Command | Meaning |
| --- | --- | --- |
| Regression | `python3 -m unittest discover -s tests -v` | Helper, corpus and evaluation-grader behavior. |
| Build smoke | `docker compose up --build --abort-on-container-exit --exit-code-from checks` | Predetermined fixture preparations and actual toolchain/build checks. |
| Agent evaluation | `python3 scripts/evaluate.py run ...` | A real agent uses the skill on fresh inputs; separate graders inspect its results. |

Build smokes do not measure the agent's migration decisions. An agent evaluation
does not itself certify an enterprise production release.

## Evaluation design reference

[Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)
by Anthropic explains tasks, trials, graders, transcripts and observed outcomes.
This harness applies those concepts through versioned tasks, isolated trials,
retained traces, independent build/runtime checks and explicit semantic review.
Judge the resulting artifacts and behavior alongside the agent's reports. Repeat
trials to assess consistency, and calibrate model-assisted reviews with human
review before relying on them for release decisions.

## Run the eight cases

Build the pinned image first. Use an installed, authenticated Codex CLI whose
native binary directory contains both `codex` and `codex-code-mode-host`; the
tested CLI is 0.159.3. No agent credentials or CLI binaries are baked into the image.
Use Linux native binaries matching the container architecture; a macOS or Windows
host executable cannot be mounted as a Linux agent binary.
The CLI reads the existing login from `~/.codex/auth.json`, or `--auth-file`.
Use a model available to your account and record it explicitly.

```bash
docker build -t modernize-java-checks:local .
python3 scripts/evaluate.py list
python3 scripts/evaluate.py run \
  --output check-reports/evaluations/java21-trial \
  --target 21 --mode workflow --trials 1 --workers 4 \
  --model YOUR_MODEL \
  --codex-bin-dir /absolute/path/to/native/bin
```

The default runs all eight cases. Repeat `--case` to select a subset. `--target 25`
exercises the other principal target; `source-recipe` deliberately retains release
17 while changing the evaluated runtime. Boot uses its requested 3.5.16 pin.
Tasks are versioned in [tasks.json](tasks.json). Independent semantic acceptance
criteria remain in [cases.json](../testdata/cases.json).

The default `workflow` mode uses one agent session per fixture and four concurrent
fixtures. Each session still writes and consumes all five handoffs. This avoids
repeating discovery and evidence collection in five independent contexts.
Use `--workers 1` or `2` on smaller machines; each container has a 4 GB memory cap.

`staged` launches a fresh agent/container for every phase. Use it on representative
cases such as `--case reactor --case boot-context --mode staged --workers 2` when
testing handoff sufficiency, and run the full staged suite for release audits.
The timeout is 900 seconds per phase in staged mode or per workflow session;
`--timeout` overrides it. Canonical reports are kept concise and reuse current
baseline/source evidence; required builds/tests and explicit gaps remain intact.
Start with one trial per case, then use `--trials 3` or more to measure consistency.
Agent calls consume the account's normal model usage; no cost estimate is invented.

`prepare` writes fresh workspaces and prompts without invoking a model. A later
`run` can execute an untouched prepared directory. Existing attempted runs are
never silently reused. `--defer-grade` separates collection from grading:

```bash
python3 scripts/evaluate.py grade --output check-reports/evaluations/java21-trial
# Independently inspect/rebuild only a selected case:
python3 scripts/evaluate.py grade --output check-reports/evaluations/java21-trial --case reactor
```

## Read the output

Open `<output>/summary.md`, then each trial's `grade.md` and agent summary.
The output retains protected input/skill snapshots, exact prompts, JSONL tool
transcripts, stderr, phase input hashes, product hashes before/after each phase,
captured Markdown/JSON handoffs, real baseline/target builds, JUnit XML, emitted
classfile levels, dependency graphs and a JSON grade. Metadata identifies the
model, image digest, toolchain lock, skill, tasks, runner and native agent binaries.

The grader runs in a separate container after the agent exits. It restores the
original fixture test assertions in a disposable build and adds a test-JVM guard.
Successful compilation with zero tests, skipped/failing tests, wrong bytecode or
incorrect ownership cannot count as a normal fixture pass. `source-recipe` has no
unit tests: its independent runtime behavior probe is reported separately.
It also checks preservation of requested remediation rules and explicit targets.
Execution may add selected versions to the central target file without changing
user constraints. Workflow grading matches initial/final policy snapshots; use
staged mode when auditing additional intermediate policy changes. New remediation
evidence is evaluated against the frozen skill for that run; older results are
not silently reinterpreted under a newer policy.

The incomplete Jetty input is an expected-blocker case. Honest missing-input
reporting can pass the evaluation while enterprise readiness remains blocked.
Missing launch tools, API/auth failures and timeouts are infrastructure results,
not evidence that the skill made a bad migration decision. Do not retry until
successful and discard earlier attempts; retain the failures and classify them.

Semantic review remains explicit. Review the case acceptance checklist against
the reports, transcript, actual diff and independent build evidence. Report
quality, justified version selection and accurate coverage claims cannot be
established by matching a few words. Record reviewer identity and findings before
claiming that the entire skill evaluation passed.
Copy each trial's `review-template.json` to `review.json`, fill reviewer identity,
each criterion's `passed` / `failed` / `not_applicable` status and supporting
evidence, then run `python3 scripts/evaluate.py report --output <run>` to refresh
the scorecard without rerunning builds. Incomplete reviews remain pending.
The final evaluation exit is nonzero for failures, infrastructure errors or
pending semantic review; an enterprise gate can remain blocked in a correct trial.

## Isolation and limits

Agent containers see one writable trial workspace, a read-only skill snapshot,
the native agent binaries and an ephemeral copy of the login. The image's source
tree is hidden; the original corpus, acceptance criteria, graders, other trial
workspaces and host Docker socket are not mounted. Containers run as the image's
non-root user with a read-only root filesystem, dropped capabilities and resource
limits. Codex's bypass flag is used only inside that externally isolated container.
Product/report symlinks are rejected at the host artifact boundary.

Maven artifact caches are shared; Gradle caches are trial-specific. Override
`--maven-cache` to choose an existing warmed Docker volume. Dependency resolution,
public documentation and advisory data remain external changing inputs. Reports
and transcripts stay under the ignored output directory; review before sharing.

The current agent adapter is Codex CLI. Keep the skill portable; add other agent
adapters at the invocation boundary rather than changing skill instructions.
Test actual outcomes with this same rubric when comparing adapters or models.
Future release evaluations should also include convergence, rollback and
with/without-skill comparisons, plus realistic applications beyond these tiny fixtures.
