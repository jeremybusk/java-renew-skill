ARG BASE_IMAGE=mcr.microsoft.com/devcontainers/python:3.12-bookworm@sha256:589b65db720b03c96d721706005f176ff467ee879f92c2d137c04a537feffa56
ARG JDK8_IMAGE=eclipse-temurin:8-jdk-jammy@sha256:185d4ef919b98cd195690c33f3fd93bd49c66c70f0b662e54566c0dbaebea6ce
ARG JDK11_IMAGE=eclipse-temurin:11-jdk-jammy@sha256:20c779c3af556eea5bde117c45e80406a299a52ddd39c8630162126a7d8153fd
ARG JDK17_IMAGE=eclipse-temurin:17-jdk-jammy@sha256:73ed442231ec66cfe48cae0b263ce619a75ab96d162ab325f38fc0a269ee3aab
ARG JDK21_IMAGE=eclipse-temurin:21-jdk-jammy@sha256:742daacb9316be4b6fc60258f6e4ac2a11882f6c597373c92290a57bfad0d2e0
ARG JDK25_IMAGE=eclipse-temurin:25-jdk-jammy@sha256:07a4ee373cd86f337e62cb8149f1e0a9f08aaf3a18c27509a493dda119fb480c

FROM ${JDK8_IMAGE} AS jdk8
FROM ${JDK11_IMAGE} AS jdk11
FROM ${JDK17_IMAGE} AS jdk17
FROM ${JDK21_IMAGE} AS jdk21
FROM ${JDK25_IMAGE} AS jdk25
FROM ${BASE_IMAGE}

USER root
COPY --from=jdk8 /opt/java/openjdk /opt/jdks/8
COPY --from=jdk11 /opt/java/openjdk /opt/jdks/11
COPY --from=jdk17 /opt/java/openjdk /opt/jdks/17
COPY --from=jdk21 /opt/java/openjdk /opt/jdks/21
COPY --from=jdk25 /opt/java/openjdk /opt/jdks/25

ENV JAVA_HOME_8=/opt/jdks/8 JAVA_HOME_11=/opt/jdks/11 \
    JAVA_HOME_17=/opt/jdks/17 JAVA_HOME_21=/opt/jdks/21 JAVA_HOME_25=/opt/jdks/25 \
    JAVA_HOME=/opt/jdks/21 MAVEN_HOME=/opt/tools/maven \
    GRADLE_USER_HOME=/home/vscode/.gradle \
    PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
ENV PATH="/opt/jdks/21/bin:/opt/tools/maven/bin:/opt/tools/gradle8/bin:${PATH}"

COPY docker/toolchains.lock.json docker/install_tools.py /opt/modernize/
RUN python3 /opt/modernize/install_tools.py \
    && mkdir -p /reports /home/vscode/.m2 /home/vscode/.gradle \
    && chown -R vscode:vscode /reports /home/vscode/.m2 /home/vscode/.gradle
COPY --chmod=755 docker/with-java /usr/local/bin/with-java

WORKDIR /workspace
COPY --chown=vscode:vscode . /workspace
USER vscode
RUN python3 scripts/checks.py --suite versions --output /tmp/image-toolchain-check
CMD ["python3", "scripts/checks.py"]
