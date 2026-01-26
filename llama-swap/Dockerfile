FROM alpine AS downloader
ARG PODMAN_VERSION=v5.7.1
ARG DOCKER_COMPOSE_VERSION=v5.0.2
ADD --link https://github.com/containers/podman/releases/download/${PODMAN_VERSION}/podman-remote-static-linux_amd64.tar.gz /tmp
ADD --chmod=755 --link https://github.com/docker/compose/releases/download/${DOCKER_COMPOSE_VERSION}/docker-compose-linux-x86_64 /usr/local/bin/
RUN <<-EOF
    set -eux
    mv /usr/local/bin/docker-compose-linux-x86_64 /usr/local/bin/docker-compose
    cd /tmp
    tar tf podman-remote-static-linux_amd64.tar.gz
    ls -la
    tar xf podman-remote-static-linux_amd64.tar.gz bin/podman-remote-static-linux_amd64
    ls -la
    mv bin/podman-remote-static-linux_amd64 bin/podman
    ls -la bin/podman
EOF

FROM ghcr.io/mostlygeek/llama-swap:vulkan-non-root
ARG UID=1000
ARG GID=1000
ARG USER=bdawg
ARG GROUP=bdawg
# `ADD --unpack` isn't supported by Podman
#ADD --unpack https://github.com/containers/podman/releases/download/v5.7.1/podman-remote-static-linux_amd64.tar.gz /home/ubuntu/
# Keeping the COPY commands separate to keep layers independent
COPY --from=downloader --link /tmp/bin/podman /usr/local/bin/
COPY --from=downloader --link /usr/local/bin/docker-compose /usr/local/bin/
USER root
RUN <<-EOF
    set -eux
    # Setup user/group
    echo "= Setting up user/group"
    echo "== users"
    getent passwd
    echo "== groups"
    getent group

    echo "= Removing user ubuntu (uid: 1000) and group (gid: 1000)"
    # remove home directory and mail spool
    userdel --remove ubuntu
    echo "== users"
    getent passwd
    echo "== groups"
    getent group

    echo "= Creating group"
    groupadd -g $GID $GROUP
    echo "= Creating user"
    useradd -u $UID -g $GID --create-home $USER
    echo "== users"
    getent passwd
    echo "== groups"
    getent group

    echo "= Testing"
    id $USER
EOF
USER $USER
