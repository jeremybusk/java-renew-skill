# Build systems and transformation tooling

## Maven

- Use the repository wrapper when present; inspect its distribution URL and
  checksum configuration before running downloaded code. Inspect `.mvn/`, active
  profiles, extensions, parent POMs, repositories, toolchains, enforcer rules,
  compiler/test plugins, forked compilers and IDE configuration. Select an exact
  compatible Maven release; a major upgrade is not automatically necessary.
- Configure the compiler's `release` or the existing parent-managed equivalent.
  `source`/`target` alone do not restrict accidental linkage to newer JDK APIs.
  [Compiler release documentation](https://maven.apache.org/plugins/maven-compiler-plugin/examples/set-compiler-release.html)
  explains the distinction. Verify which releases the selected compiler supports;
  use a separate toolchain for older library bytecode when needed.
- Explicitly configure annotation processor paths and versions with a compatible
  compiler plugin. For Maven 4/compiler plugin 4.x, use that generation's processor
  model; do not copy Maven 3-only snippets uncritically. Do not globally restore
  unrestricted processor discovery to hide a missing declaration.
- Update Surefire/Failsafe and provider dependencies as a compatible set. Preserve
  JaCoCo late-bound agent arguments when adding Mockito/APM agents. Test both
  forked and in-process paths actually used by the project.
- Preserve managed parents/BOMs, reproducibility settings, mirrors, offline
  repositories, Maven Enforcer, dependency convergence, signing and deployment
  settings. Do not overwrite a corporate parent to obtain a new Java property.

Example commands, adapted to the repo's wrapper and relevant profiles:

```bash
./mvnw --version
./mvnw -B help:effective-pom
./mvnw -B dependency:tree
./mvnw -B clean verify
```

Maven goals resolve/run plugins and project lifecycle code; inspect untrusted
repositories before execution. Pin auxiliary plugin versions in the migration
record when they are not already managed. Capture command exit status and logs;
do not make a pipeline's final logging process the test result. Never run `deploy`
merely to validate a build.

## Gradle

- Read wrapper properties/JAR, distribution checksum, `settings.gradle[.kts]`,
  included builds, `buildSrc`, convention plugins, init scripts, version catalogs,
  plugin management, dependency locks and verification metadata. Update wrappers
  through the supported wrapper task on a runnable JDK; retain wrapper integrity.
- Consult the [Java compatibility matrix](https://docs.gradle.org/current/userguide/compatibility.html)
  for both **running Gradle** and **toolchains**. Gradle 9.1+ supports Java 25;
  Gradle 9 also changes the runtime floor, plugin APIs and embedded language
  compatibility. Framework/plugin ranges may require another route. Use a
  supported launcher/toolchain intersection; do not assume any old launcher can
  compile Java 25 simply because Java toolchains exist.
- Configure the Java toolchain and `options.release` separately if appropriate.
  Bind test launchers and custom `JavaExec` tasks as well. Match Kotlin/Groovy/Scala
  target constraints; verify compiler plugins and test fixtures independently.
- Upgrade deprecated Gradle APIs in owned plugins and validate third-party
  plugins before a major wrapper jump. Refresh locks and verification hashes
  using reviewed artifacts, never by turning verification off. Do not delete
  caches/locks to conceal unresolved compatibility problems.

```bash
./gradlew --version
./gradlew javaToolchains
./gradlew dependencies
./gradlew dependencyInsight --dependency <coordinate> --configuration runtimeClasspath
./gradlew clean check --warning-mode all
```

Find custom integration/contract/load tasks; `check` need not run all of them.
Container images, offline mirrors and toolchain downloads need the same pinned
vendor/patch and integrity policy as production builds.

## Ant, Bazel, sbt and proprietary builds

Keep the existing build system unless replacement is requested. Inventory custom
compiler tasks, ECJ, direct `javac`, bootclasspath assumptions and external tools.
For Bazel verify Java toolchain and remote-execution worker images; for sbt verify
Scala/JDK compatibility and compiler bridges. For application-server builds use
the vendor-certified compiler/runtime path. Missing tooling is a documented
blocker, not permission to replace the build or claim it ran.

## OpenRewrite and alternatives

[OpenRewrite's recipe catalog](https://docs.openrewrite.org/recipes/java/migrate/upgradetojava25)
contains `org.openrewrite.java.migrate.UpgradeToJava25`. At the 2026-10-19 research
baseline the current composite is documented under the Moderne Source Available
License with commercial restrictions. Check the exact artifact/release license,
transitive recipe licenses and organization entitlement **before use**. Availability
on a public repository does not imply an OSI license or commercial rights. This
skill's Apache license does not relicense external tools or recipes.

Use the pinned recipe documentation/source to inspect the expanded composition.
It can change Kotlin, dependency versions, language usage and Security Manager
code. Exclude transformations outside this task; removing security enforcement
requires a verified replacement. Keeping an older bytecode baseline often needs
selected subrecipes instead of the Java 25 composite.

Follow the chosen release's
[running recipes documentation](https://docs.openrewrite.org/running-recipes/getting-started).
Resolve and record exact plugin and recipe artifact versions; discover available
recipe names, run a dry run, inspect changed files, then apply approved-scope
changes. Do not paste `RELEASE`, `latest.release`, dynamic ranges or guessed
artifact versions into build commands. A project build must be able to attribute
types correctly; unresolved attribution is not evidence a recipe was unnecessary.

No recipe execution is built into the helper. When licensing, attribution, build
support or semantics do not fit, perform focused edits using the compiler/IDE AST
or manual changes and the same verification. Never globally replace `javax.` with
`jakarta.` or apply text substitution to generated/vendor/binary archives.
