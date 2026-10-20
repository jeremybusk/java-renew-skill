# JDK migration decisions

Reference baseline checked 2026-10-19. Recheck the target vendor's release notes
and security defaults for the exact patch. Use
[Oracle's JDK 8 migration guide](https://docs.oracle.com/en/java/javase/25/migrate/migrating-jdk-8-later-jdk-releases.html)
and [removed tools/components](https://docs.oracle.com/en/java/javase/25/migrate/removed-tools-and-components.html)
as entry points, then investigate applicable changes below. These are triage
categories; a lexical finding does not prove the application uses the behavior.

## Version boundaries

| Boundary | Migration decision and observable check |
| --- | --- |
| 8 → 9/11 | JPMS changes JDK layout and classloaders; remove assumptions about `rt.jar`, `tools.jar`, extension/endorsed directories, JRE subdirectories, and system loader being a `URLClassLoader`. Libraries may remain on the classpath; modularizing the application is optional. |
| 11 | JAXB, JAX-WS, activation, CORBA and associated tools leave the JDK. Add compatible external API **and implementation** dependencies where needed. Separate JavaFX, Web Start/applets and other removed distribution features from Java SE. |
| 11–17 | Replace removed CMS/ParNew flags, Pack200, Nashorn and RMI activation where present. Search generated launch scripts, service units, vendor installers, shell flags, `JAVA_TOOL_OPTIONS`, `JDK_JAVA_OPTIONS`, and CI injection. |
| 16/17 | Strong encapsulation exposes unsupported reflection/internal API access. Upgrade the owning dependency; `--illegal-access=permit` is not a Java 17+ solution. A temporary `--add-opens`/`--add-exports` needs a precise package, caller, rationale, owner and exit test. |
| 18+ | Default encoding is UTF-8. Make encodings explicit at file/protocol boundaries and test legacy text; globally changing encoding is not a substitute for preserving external contracts. See [JEP 400](https://openjdk.org/jeps/400). |
| 21+ | Dynamic agent loading produces warnings; validate test mocking, coverage, profilers and APM agents. Prefer supported startup agent configuration where applicable. Do not assume warnings already mean agents are forbidden. See [JEP 451](https://openjdk.org/jeps/451). |
| 23+ | Explicitly configure annotation processors and their dependencies. JDK 23 changes implicit processing discovery. Rebuild generated sources from a clean checkout. Legacy `JRE`/`COMPAT` locale data is also gone; test CLDR output rather than relying on that provider switch. |
| 24+ | Security Manager is permanently disabled. If security depends on in-process sandboxing, design and verify an external isolation replacement; deleting permission checks is not equivalent. JNI/native access and Unsafe memory access warnings also expose dependencies requiring attention. See [JDK 24 migration changes](https://docs.oracle.com/en/java/javase/24/migrate/removed-tools-and-components.html). |
| 25 | Validate all intermediate changes and target patch notes. Java 25 classfile major is 69: every parser, agent, instrumenter, compiler and deployment scanner that reads it must support it. Preview features remain release-specific and opt-in. |

Do not enable virtual threads, preview APIs, the Vector API, a different collector,
or broad code-style refactors merely to change JDK. They need an explicit benefit
and their own concurrency/performance tests.

## Runtime behavior requiring targeted tests

- **Text, locale, time:** UTF-8 defaults, CLDR punctuation/date/currency changes,
  timezone database/DST changes, regex Unicode behavior, resource bundle loading,
  default locale, database encodings, and byte-sensitive signatures. Assert external
  bytes and parsed values. Prefer explicit formats for persisted/wire data.
- **Security and identity:** truststores/custom CAs, certificate path validation,
  disabled algorithms, TLS versions/ciphers, keystore type/provider changes,
  PKCS#11/HSM integration, Kerberos/JAAS/LDAP/JNDI, XML parser defaults and
  serialization filters. Test real protocol handshakes. Do not re-enable weak
  algorithms or trust all certificates to pass a test.
- **Persistence/contracts:** Java serialization UIDs and class evolution, JSON/XML
  shapes, Jackson modules/date types, protobuf/Avro schemas, REST error responses,
  validation messages, messaging headers, cache/session objects and mixed-version
  cluster traffic. Keep explicit compatibility fixtures for readers and writers.
- **Collections/concurrency:** reflection of implementation classes, iteration
  order assumptions, concurrent map semantics, timing-sensitive tests, executor
  shutdown, interrupt handling and thread-local context. Newly inherited methods
  can collide with user APIs when recompiling (for example Java 21 sequenced
  collections). Check source as well as binary compatibility.
- **OS/network/files:** DNS caching, proxies, IPv4/IPv6, filesystem case/symlinks,
  temporary directory permissions, subprocess argument handling, sockets, headless
  fonts/rendering, printing and desktop integration. Test the actual deployment OS.
- **Resource management:** G1/default collector and unified GC logging, heap versus
  total RSS, direct memory, metaspace, thread stacks, cgroup CPU/memory limits,
  startup/warmup, graceful shutdown and leak behavior. Finalization is deprecated
  for removal; migrate owned cleanup to explicit lifecycles with tests. Do not
  assume it has already been removed in Java 25.
- **Native/agents:** JNA/JNI classifiers, libc (musl versus glibc), CPU architecture,
  FIPS providers, startup `-javaagent` order, agent attachment privileges and
  module/native access flags. Build a separate compatibility lane for native image
  or custom runtime images; a JVM pass does not validate them.

## Binary analysis

Run the **target JDK's** tools on built/extracted application classes with the
complete resolved classpath. For example (Unix classpath separator shown):

```bash
"$TARGET_JDK/bin/jdeps" --multi-release 25 --jdk-internals --recursive \
  --class-path 'lib/*' app.jar
"$TARGET_JDK/bin/jdeprscan" --release 25 --for-removal \
  --class-path 'lib/*' app.jar
```

These are diagnostics, not launch commands. Set the release to the actual target
when overridden. Analyze dependency JARs too. Extract nested/fat WAR/JAR libraries
to a temporary directory using trusted archive handling; ordinary `jdeps app.jar`
does not resolve every nested Spring Boot dependency. Keep missing dependencies
visible; never declare success from `--ignore-missing-deps`. Neither tool discovers
all reflective strings, native code or runtime-loaded plugins. For libraries,
use API/binary compatibility tools (Revapi/japicmp or the existing equivalent),
run consumers at the minimum supported runtime and Java 25, and inspect
multi-release JAR entries, service descriptors and shaded packages.
