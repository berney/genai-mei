FROM docker.io/kyuz0/amd-strix-halo-comfyui
ARG UID=1000
ARG GID=1000
ARG USER=bdawg
ARG GROUP=bdawg
RUN <<-EOF
	groupadd --gid "$GID" "$GROUP"
	useradd --uid "$UID" --gid "$GID" --create-home "$USER"
EOF
USER "$USER"
COPY ./extra_model_paths.yaml /opt/ComfyUI/
#USER "$UID:$GID"
