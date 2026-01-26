FROM python:alpine
ARG UID=1000
ARG GID=1000
ARG USER=bdawg
RUN <<-EOF
    set -eux
    apk add bat fd file jq ripgrep tree vim xh uv
    adduser -D -u $UID -g $GID $USER
EOF
USER $USER
ENV PATH="/usr/local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/home/$USER/.local/bin"
RUN <<-EOF
    uv tool install mistral-vibe
EOF
COPY --chown=$UID:$GID config.toml /home/$USER/.vibe/
WORKDIR /home/$USER
CMD vibe
