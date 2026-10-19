# Self-contained modernization test corpus

These projects are development inputs for this skill. They are stored in the
same repository as the code/tests and are not downloaded during tests. Install
only `skills/modernize-java` for ordinary skill use; keep this directory when
developing or evaluating the skill.

`scenarios/` contains eight locally maintained fixture projects, about 10 KB
across 27 files. [fixtures.sha256.json](fixtures.sha256.json) records each file's
SHA-256 for reproducible test inputs. The corpus is maintained independently
within this repository and has no external repository dependency or sync step.

## Coverage and limits

| Case | What it exercises |
| --- | --- |
| `java8` | Maven source/target 1.8, explicit JUnit Jupiter version, test discovery, comment preservation. |
| `reactor` | Parent/child Maven ownership, version expressions, Lombok and inherited processor configuration. |
| `maven-bom` | External BOM import and a versionless dependency; effective versions need model resolution. |
| `gradle-groovy` | Java 8, Groovy DSL, JUnit 4 and an older JaCoCo parser. |
| `gradle-kotlin` | Kotlin DSL, subproject toolchain and a version catalog; application source is Java. |
| `boot-context` | Boot-managed dependencies and a real non-web context test; Boot 4 is not mandatory for Java 25. |
| `source-recipe` | Existing `String.format` behavior and Java 17 release; source changes are optional. |
| `jetty9` | Servlet/WebSocket namespace boundaries, annotation scanning and a runtime health probe. |

Baseline JDK values in [cases.json](cases.json) define evaluation scenarios; they
are not assertions that those runtimes were observed or that builds passed.
Versions in these deliberately old fixtures are test inputs, not recommended
production dependencies.

Some fixtures are partial. `jetty9` has no build descriptor and needs a Jetty
integration harness/dependencies. Gradle fixtures have no wrappers.
`source-recipe` has no unit tests. Other POMs intentionally omit build/test plugin
configuration. Missing infrastructure and zero-test builds are cases to detect,
not reasons to report success or silently introduce an unrelated tool.

## Run the regression tests

From the repository root:

```bash
python3 -m unittest discover -s tests -v
```

The default suite is offline and needs only Python 3.10+. It copies each project
to a temporary workspace, verifies scanner coverage and declared version ownership,
checks the five-stage report/evidence paths, rejects stale handoffs and detects
changes to fixture bytes. It does not launch Maven/Gradle or certify migrations.

Optional real compilation and smoke assertions require an installed JDK whose
compiler supports releases 8 and 17:

```bash
MODERNIZE_JAVA_INTEGRATION=1 MODERNIZE_JAVA_HOME=/path/to/jdk \
  python3 -m unittest discover -s tests -p test_corpus.py -v
```

This compiles four dependency-free production classes, checks classfile majors
52/61 and tests their greeting behavior on the selected runtime. It downloads
nothing and prints the actual JDK/compiler versions. It does not execute the
JUnit test suites, Gradle, Boot, Lombok or Jetty. A run on JDK 21 is only JDK 21
evidence, not Java 25 validation. A Java 25 compiler may need a separate older
compiler toolchain to retain Java 8 bytecode.

## Test a skill ability

`cases.json` separates automatic expectations (`build_files`, `signals`, `poms`)
from semantic acceptance criteria (`acceptance`). The latter must be evaluated
against actual agent behavior and build/runtime results; they are not claimed
as passed by the Python tests.

1. Copy the selected fixture to an isolated work directory. Never modify the
   originals under `testdata/scenarios`.
2. Invoke the skill with a concrete task, target, and relevant overrides. For
   example: `Use $modernize-java to assess, plan, execute, validate, and summarize
   this Maven reactor's Java 25 migration. Preserve parent-owned versions.`
3. Review each Markdown/JSON handoff against the case's acceptance criteria.
   Assess/plan should leave product inputs unchanged. During execution, check
   semantic changes, preserved ownership and the actual diff.
4. Run the relevant clean compile, real unit/integration tests and runtime checks
   in the disposable project. Record test counts and JDKs. Missing prerequisites
   must remain visible blockers. Use real evidence for validate/summary.
5. Repeat the migration on the already migrated workspace to check convergence;
   there should be no further compatibility edits without a new reason. For
   rollback tests, restore the isolated baseline and compare bytes. Never reset
   the development checkout to test rollback.

For a new ability, add an input that exhibits the problem, independent expected
behavior in `cases.json`, and a test that fails when the behavior regresses.
Prefer observable results (effective dependency ownership, test discovery,
classfiles, behavior) to exact report wording. Add new fixtures under `scenarios/`
and extend the case list/test coverage accordingly. Review input changes and
update the local checksum manifest; do not bless a generated output as its own
oracle.

## Maintenance

Maintain the fixtures directly in this repository. For intentional changes,
review the fixture diff, refresh `fixtures.sha256.json`, and review case
expectations separately. Keep these changes together in version control. Normal
test runs do not fetch or update anything.

## Fixture license status

The existing fixture content has no separate license grant recorded. Renaming
and maintaining it locally does not change that status; the project's Apache-2.0
license does not imply a license grant for that content.
