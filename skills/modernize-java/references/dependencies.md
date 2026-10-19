# Dependency and framework decisions

Research baseline: 2026-10-19. Resolve concrete versions during each migration;
this file is a decision map, not a global version catalog. For every changed
platform record the exact version, Java/compiler/runtime ranges, support/EOL
status, primary URL and access date. Organization policy may require paid vendor
support or a specific certified distribution. A public support table cannot
prove a customer's entitlement.

## Version selection

1. Obtain the effective Maven dependency/plugin trees or Gradle configurations
   for affected modules and active production/test profiles. Include parents,
   BOM imports, dependency management, catalogs, lockfiles, substitutions,
   enforced platforms, processors, test fixtures, plugins and agents.
2. Choose a framework/platform that explicitly supports the target Java runtime,
   then use its managed dependency set. Check the intersection with the build
   launcher and deployment server. Honor explicit pins; surface incompatible
   combinations before changing source.
3. Distinguish a technical minimum from a maintained secure patch. Check current
   advisories and vendor release/support information; do not copy old patch
   versions from examples. Use exact reproducible versions and approved mirrors.
4. Investigate transitive vulnerability fixes at the owning BOM first. A forced
   transitive upgrade may break binary compatibility; prove it before retaining
   it. Compare resolved graphs, not just POM edits or version strings.

## Stack map

| Detected component | Required decision and validation |
| --- | --- |
| Spring Boot/Spring | Identify the actual Boot line and Java support matrix. A common route from Boot 1/2 is through a compatible 2.7 checkpoint, then the documented Boot 3 migration; checkpoints need not be final supported deployments. Boot 3 introduces Spring 6/Jakarta changes. Boot 4 is a separate major decision with its own modularization and serialization/test changes. Java 25 alone does not mandate Boot 4. Use the matching migration guide for each major. |
| Servlet/Jakarta EE | Align API, app server, WAR provided scope, deployment descriptors and integrations. Tomcat 9 (`javax`) and 10+ (`jakarta`) boundaries matter. Verify the **specific release's** Java 25 certification for Tomcat/Jetty, WildFly/JBoss EAP, WebLogic, WebSphere/Liberty or Payara; installing a newer JVM does not certify the server. An unsupported proprietary server is a migration blocker with alternatives. |
| Hibernate/JPA/Validation | Align Jakarta versus Java EE namespace, ORM provider, enhancement plugin, dialects, Hibernate Types/integrators, query behavior, identifier generation, pagination, fetch plans and validation provider. Hibernate 5→6+ can change SQL and schema expectations; preserve production data and test query results/performance. Do not auto-run destructive schema updates. |
| Jackson/Gson/JSON-B | Stay on the framework-managed major; validate records, constructor discovery, Java time, nullability, polymorphic typing and wire fixtures. Jackson 2→3 is a distinct major migration; align integration modules and package changes. Avoid changing serialized contracts as a side effect. |
| Logging | Align SLF4J API and exactly one provider, Logback/Log4j2, bridges, async behavior and structured log contracts. SLF4J 1.x→2.x changes provider discovery. Check for bridge loops, multiple bindings and lost MDC context. |
| Bytecode/instrumentation | ASM, Byte Buddy, Javassist, CGLIB, JaCoCo, Mockito, PowerMock, agents and framework-shaded copies must read the emitted classfiles. Upgrade the dependency embedding old tooling; overriding one top-level ASM cannot fix every shaded copy. PowerMock may need replacement and test refactoring rather than module-access flags. |
| Annotation processors | Lombok, MapStruct, QueryDSL, Dagger, AutoValue, Error Prone, Immutables, JPA metamodel, kapt/KSP: declare processor paths/configurations explicitly and align compiler/processor versions. Lombok + MapStruct may require `lombok-mapstruct-binding`. Test generated symbols from clean builds, not cached IDE output. |
| Tests | Preserve JUnit 4 coverage through a supported Vintage engine when needed; migrate deliberately to Jupiter. Match JUnit Platform engines/launcher, Surefire/Failsafe, Gradle Test, Mockito/Byte Buddy and Testcontainers. Use a supported startup Mockito agent where required, preserving coverage agent arguments. Verify counts and integration test discovery. |
| Network and messaging | Netty/Reactor, Apache HttpClient, OkHttp, gRPC/protobuf, Kafka, JMS/AMQP: align BOMs and shaded/native transports, protocol/schema compatibility, TLS, backpressure, shutdown and load behavior. HttpClient 4→5 changes packages/APIs; do not just edit coordinates. |
| Data and migrations | Verify JDBC/R2DBC driver support for Java 25 **and** the server/database version, dialects, HikariCP, Flyway/Liquibase modules, stored procedures and transaction isolation. Modern Flyway may require database-specific modules. Replay migrations against a disposable production-like copy, never live data without explicit scope. |
| Utilities/security | Guava, Commons libraries, Bouncy Castle, XML parsers, template/script engines and compression libraries: inspect removed APIs, transitive dependencies and provider changes. Keep crypto provider artifacts from one compatible family; a family name such as `jdk18on` is not a promise about the latest JDK. |
| Other frameworks | For Quarkus/Micronaut/Helidon/Dropwizard/Vert.x/Camel, follow the platform BOM and matching major migration guide, extensions, build plugins and native-image support. Do not impose Spring dependencies on another stack. |
| Mixed languages/builds | Kotlin/Groovy/Scala compiler, stdlib, Gradle DSL, compiler plugins, kapt/KSP and bytecode targets form another compatibility matrix. A runtime supporting Java 25 need not emit JVM target 25. Keep compatible older bytecode targets where required and test Java↔language interoperability. |
| OSGi/JPMS/plugins | Check split/sealed packages, automatic module names, exported/opens clauses, OSGi manifests, service loaders, relocated/shaded code and signed JARs. Do not introduce JPMS as a mandatory upgrade step. Regenerate vendor code or plugin bundles using compatible tooling. |

## Verified examples, not default pins

- [Gradle's matrix](https://docs.gradle.org/current/userguide/compatibility.html)
  identifies 9.1.0 as the start of Java 25 launcher and toolchain support. A
  framework can impose a different Gradle range, so consider a separate launcher
  JDK and verify whether that toolchain combination is supported by both parties.
- The versioned [Boot 3.5 requirements](https://docs.spring.io/spring-boot/3.5/system-requirements.html)
  explicitly cover Java 25 in the current 3.5 documentation. Earlier 3.5 patches
  do not inherit a later patch's support statement; use exact release evidence.
- [Lombok's changelog](https://projectlombok.org/changelog) introduces JDK 25
  support at 1.18.40; later patches include additional fixes. This is a technical
  floor, not a maintained-version recommendation.
- [JaCoCo's history](https://www.jacoco.org/jacoco/trunk/doc/changes.html) gives
  0.8.14 official Java 25 support; 0.8.13 lists experimental support. Choose an
  approved maintained compatible release, including embedded ASM compatibility.

Use [Boot 3 migration guidance](https://github.com/spring-projects/spring-boot/wiki/Spring-Boot-3.0-Migration-Guide)
for the Boot 2→3 boundary and the selected release's official upgrade guide for
later majors. `javax.sql`, `javax.transaction.xa`, `javax.annotation.processing`,
`javax.crypto`, `javax.net`, `javax.naming`, `javax.management`,
`javax.xml.parsers` and other Java SE packages remain `javax`; namespace changes
apply to the relevant Jakarta specifications, including generated sources,
service descriptors, persistence/validation config and reflection strings.
