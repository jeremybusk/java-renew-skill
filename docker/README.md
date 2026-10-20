# Reproducible check environment

Use one image for the repository tests, Java compiler checks and real Maven/Gradle
fixture builds. The base is Microsoft's
[Python 3.12 Bookworm devcontainer](https://github.com/devcontainers/images/tree/main/src/python),
published on `mcr.microsoft.com` as listed by the requested
[Docker Hub image catalog](https://hub.docker.com/r/microsoft/devcontainers).
Python runs the harness; the installed JDKs run Java builds and tests.

## Run all automated checks

```bash
docker compose up --build --abort-on-container-exit --exit-code-from checks
docker compose cp checks:/reports/. ./check-reports
```

Open `check-reports/summary.md`. JSON results, complete command logs, actual
version output and JUnit XML are saved alongside it. Any failed command, missing
test discovery, incorrect bytecode or version mismatch produces a nonzero exit.
The workspace is mounted read-only; builds use disposable copies. Maven and
Gradle caches and reports use persistent named volumes. The process runs as
the devcontainer's non-root `vscode` user, without a Docker socket mount.
Results also record Python, platform, architecture and the toolchain lock hash.
CI runs this same matrix and uploads the reports.

The default run checks:

- Installed versions of all five JDKs, Maven, both Gradle distributions and OSV-Scanner.
- All Python regression tests plus the four real compiler/behavior smoke cases.
- Boot 3.5.16 clean Maven verification on JDK 17, 21 and 25.
- Both Gradle fixture DSLs with real JUnit execution on JDK 17, 21 and 25.
- Actual JUnit counts and emitted classfile majors for every fixture build.

These are deterministic fixture build smokes. They do not invoke an AI agent or
prove that the skill autonomously migrated a project. The Maven fixture contains
only a context test, so it does not establish deployable-application readiness.
The other fixture scenarios are covered by the corpus regression tests; this
command does not claim complete live builds for the partial Jetty fixture.

## Pinned tools

| Tool | Selection |
| --- | --- |
| Python / OS | Devcontainers Python 3.12 / Debian Bookworm, immutable image digest. |
| JDKs | Temurin 8, 11, 17, 21 and 25, each from an immutable image digest. |
| Default Java | 21. |
| Maven | 3.9.16; verified SHA-512. |
| `gradle` / `gradle8` | 8.14.6; verified SHA-256. Used for Java 17/21 fixture builds. |
| `gradle9` | 9.8.2; verified SHA-256. Used for Java 25 fixture builds. |
| OSV-Scanner | 2.7.0; architecture-specific release binary, verified SHA-256. |

[Dockerfile](../Dockerfile) pins the base/JDK image indexes and
[toolchains.lock.json](toolchains.lock.json) pins tool archives and fixture smoke
versions. Build uses no moving apt/pip/SDKMAN installation. The actual JDK patch
versions are captured in the check logs; digests freeze their exact contents.
The archives' checksums come from the publishers:
[Maven](https://archive.apache.org/dist/maven/maven-3/3.9.16/binaries/apache-maven-3.9.16-bin.tar.gz.sha512),
[Gradle](https://services.gradle.org/versions/all).

Gradle 8 remains useful for Java 8-era builds and the Boot 3.5 build-tool range;
Gradle 9 supports the Java 25 lane. Choose deliberately using the
[Gradle Java matrix](https://docs.gradle.org/current/userguide/compatibility.html)
and the framework's requirements. JDKs 8/11 are available for baseline work;
Boot 3.5 itself requires at least Java 17.

## Select checks or use the tools directly

```bash
docker compose run --rm checks python3 scripts/checks.py --suite unit
docker compose run --rm checks python3 scripts/checks.py --suite builds --java 21
docker compose --profile offline run --rm offline
docker compose run --rm checks with-java 8 mvn --version
docker compose run --rm checks with-java 25 gradle9 --version
docker compose run --rm checks bash
```

`--java` can repeat; the default build lanes are 17, 21 and 25. `--timeout` sets
the per-command limit. Compiler regression tests use JDK 21 for compatibility
with both Java 8 and 17 source releases, independent of the build lane.
Gradle toolchain auto-download is disabled; the runner uses the installed JDKs.
Known fixture copies receive explicit release/toolchain settings and a compatible
JaCoCo version. These fixed smoke preparations are visible in `scripts/checks.py`.

The first build downloads the pinned image/tool inputs. The first fixture run
also resolves Maven/Gradle dependencies. `--offline` fails when an artifact is
not already cached; it does not silently skip a check. To reproduce with no
network, retain the final image by digest and the populated cache volumes.
The `offline` Compose profile runs the complete matrix with networking disabled
and writes its separate reports under `/reports/offline`. CI verifies this after
the initial online run.
Project dependency provenance and current advisory/security checks are separate
from pinning the development toolchain.

## Optional dependency vulnerability scan

OSV-Scanner is installed in the image. Run it explicitly against the project being
migrated; its network-dependent findings do not belong in deterministic fixture
regression results. The corpus intentionally includes old dependencies.

```bash
# Scan the complete corpus; findings produce a nonzero exit.
docker compose --profile security run --rm security
# Scan one fixture and reject missing/unresolved package versions.
docker compose run --rm checks python3 scripts/checks.py --suite security \
  --scan-root /workspace/testdata/scenarios/boot-context --output /reports/boot-security
# Prefer this when a build-generated SBOM has already been saved in /reports.
docker compose run --rm checks python3 scripts/checks.py --suite security \
  --sbom /reports/project/bom.json --output /reports/project-security
```

The security profile saves Markdown/JSON summaries, diagnostics and raw
`osv-scan.json` under `/reports/security`; export reports as above. The runner
calls `osv-scanner scan source -r` for source or `-L` for an explicit SBOM.
Security is opt-in and is not included in `--suite all`.
Keep the actual exit code, diagnostics, scanner version, UTC scan time, package
coverage and advisory IDs. Distinguish findings, scan errors and no packages
discovered; none should become a clean security pass by omission. Do not change
the corpus just to remove expected findings.
The runner also fails a zero-exit scan if no versioned packages were found or
any discovered package lacks a version/commit. Review package coverage against
the effective build even when the runner passes. An inherited-version POM can
produce exit 0 with only unresolved entries; the Boot fixture did exactly this.

For Maven, OSV can resolve `pom.xml` transitives using public services; that graph
can differ from the effective build and omit test dependencies. For managed/BOM,
private, Gradle or test graphs, also scan a build-generated CycloneDX/SPDX SBOM or
supported resolved lockfile, and compare package coverage. Merely parsing
`build.gradle` or `build.gradle.kts` does not establish resolved dependency coverage.
Online scans may send dependency coordinates to OSV/deps.dev or configured registries;
honor organization policy before scanning private projects.

Use the existing organization scanner when required. OSV is an additional SCA
signal, not a replacement for license review, TLS/identity tests, container/JDK
scans or organization approval. `--offline` requires a separately retained OSV
database snapshot and disables Maven transitive resolution; the build-cache
`offline` profile does not populate this advisory database. Record the database
date/hash when replaying offline security checks.

See the official [source scan](https://google.github.io/osv-scanner/usage/scan-source),
[Java coverage](https://google.github.io/osv-scanner/supported-languages-and-lockfiles/),
[offline mode](https://google.github.io/osv-scanner/usage/offline-mode/) and
[pinned release](https://github.com/google/osv-scanner/releases/tag/v2.7.0).

## Single image and editor use

Compose is optional:

```bash
docker build -t modernize-java-checks:local .
docker run --rm modernize-java-checks:local
docker run --rm modernize-java-checks:local with-java 17 java -version
```

The image contains the repository snapshot from build time, so it can run without
a host source mount. Rebuild after code changes. Use a named `/reports` volume
if results must survive `docker run --rm`; Compose configures persistence already.
`.devcontainer/devcontainer.json` reuses the same Dockerfile for an editor.

Update pinned inputs deliberately: resolve new immutable image digests, obtain
the matching published archive checksums, review compatibility, rebuild and run
the complete matrix. Changing a download version without its checksum fails the
build. Build arguments allow explicitly supplied base/JDK image replacements;
record those overrides together with the final image digest when comparing runs.
