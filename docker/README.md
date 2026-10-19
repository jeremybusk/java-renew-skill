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

- Installed versions of all five JDKs, Maven and both Gradle distributions.
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
