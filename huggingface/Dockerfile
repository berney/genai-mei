FROM python:alpine
# export PATH="$PATH:$HOME/.local/bin"
# `HF_HUB_ENABLE_HF_TRANSFER` is deprecated, replaced by XET
#ENV HF_HUB_ENABLE_HF_TRANSFER=1
# `hf-xet` is dynamically linked against glibc so doesn't work in Alpine.
ARG UID=1000
ARG USER=bdawg
RUN <<-EOF
    set -eux
    apk add bat fd file jq ripgrep tree vim xh uv
    adduser -D -u $UID $USER
EOF
USER $USER
ENV PATH="/usr/local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/home/$USER/.local/bin"
RUN <<-EOF
    uv tool install huggingface_hub
    # test installation is working
    #python -c "from huggingface_hub import model_info; print(model_info('gpt2'))"
    # equivalent `hf` command of the python code above
    hf models info gpt2 | jq keys
    hf version
    hf env
EOF
ENTRYPOINT ["hf"]
CMD ["--help"]
