## vim: ts=4 sw=4 et
#
# unslothai/llama.cpp `mix` prebuilt build for gfx1151 (Strix Halo) — an
# inference engine to use instead of `berne/amd-strix-halo-toolboxes` whenever a
# model wants MTP speculative decoding.
#
# Why a separate engine exists: upstream llama.cpp knows the arch (`qwen4exp`)
# and the `nextn.*` MTP tensors, but it cannot borrow tensors across models
# (`grep -a -c borrow_shared libllama.so.0` -> 0 at b10950), and unsloth's MTP
# heads ship a single draft block and borrow `token_embd.weight`,
# `output.weight` and `output_hc_norm.weight` from the target. So on the toolbox
# build *no* MTP head loads (`check_tensor_dims: tensor 'token_embd.weight' not
# found` -> `failed to load draft model`). The `mix` branch adds the borrowing,
# so `--spec-type draft-mtp` works: +57 % decode on Qwen3.8-Flash-Next-IQ4 with
# byte-identical output (kv-bench Part 2).
#
# The release tarball is a self-contained ROCm *userspace* stack: one flat
# directory of binaries plus hsa/hip/rocblas/hipblaslt and their Tensile kernel
# dirs, and the executables carry `RUNPATH=$ORIGIN`. Hence no ROCm install and no
# LD_LIBRARY_PATH, so a slim base is enough (1.7 GB image instead of the 6 GB
# toolbox image): the NEEDED closure outside the bundle is only
# libstdc++/libm/libgcc_s/libc (max requirement GLIBC_2.34 + GLIBCXX_3.4.30).
# Still needs, at run time, `/dev/kfd` + `/dev/dri` with the `render`/`video`
# groups, which compose's `x-engine` provides.
#
#   docker compose build qwen3.8-Flash-Next-IQ4-MTP
#   docker compose run --rm --no-deps qwen3.8-Flash-Next-IQ4-MTP llama-server --version
#   docker compose run --rm --no-deps -T qwen3.8-Flash-Next-IQ4-MTP \
#       sh -c 'grep -ac borrow_shared /opt/llama.cpp/libllama.so.0'      # -> 3
#
# Two stages because `ADD --checksum` (the integrity check) cannot unpack for us:
# buildah's ADD whitelist is chmod/chown/checksum/link/keep-git-dir/exclude (no
# `--unpack`/`--no-unpack`, those are BuildKit-only), and a URL archive lands as a
# 0600 file inside a directory named after the destination - verified identical
# with `--format oci` and `--format docker`: /opt/llama.cpp/app-*.tar.gz.
# Unpacking in the last stage would ship that 337 MB in a layer, so `fetch`
# downloads, verifies and extracts (tar + gzip, absent from the base and kept out
# of the result), and only the extracted tree is copied forward.

# Fedora, like the toolbox engines: `x-engine` asks for `group_add: render,video`
# and podman resolves those names in the *image's* /etc/group. Ubuntu fails that
# lookup outright (`Unable to find group render: no matching entries in group
# file`, and its `video` is GID 44, not the host's 39). fedora-minimal ships
# render 105 + video 39, matching this host, plus /lib64/libstdc++.so.6.0.35
# (GLIBCXX_3.4.33 >= the 3.4.30 the tarball needs) and glibc 2.43 (needs >= 2.34).
ARG BASE=registry.fedoraproject.org/fedora-minimal:44
# unslothai/llama.cpp release tag; `-mix` is the fork branch with draft-head
# tensor borrowing. Asset: app-${VERSION}-linux-x64-rocm-${GPU}.tar.gz
ARG VERSION=b10909-mix-bea84f7
ARG GPU=gfx1151
# sha256 of the asset, so a re-tagged or rotated release fails the build instead
# of silently becoming a different binary. GitHub publishes it:
#   curl -s https://api.github.com/repos/unslothai/llama.cpp/releases/tags/${VERSION} \
#       | jq -r '.assets[] | select(.name | contains("gfx1151")) | "\(.name) \(.digest)"'
ARG CHECKSUM=sha256:cec6a1ac7fdeb205e46172525189d0f3789613afff58a8fe2b39cb6e4ca94305

FROM ${BASE} AS fetch
ARG VERSION
ARG GPU
ARG CHECKSUM
RUN microdnf install -y --setopt=install_weak_deps=False tar gzip \
    && microdnf clean all
ADD --checksum=${CHECKSUM} \
    https://github.com/unslothai/llama.cpp/releases/download/${VERSION}/app-${VERSION}-linux-x64-rocm-${GPU}.tar.gz \
    /tmp/app.tar.gz
# The archive is flat (`./llama-server`, `./libllama.so.0`, `./rocblas/`, ...).
RUN mkdir -p /opt/llama.cpp \
    && tar -xzf /tmp/app.tar.gz -C /opt/llama.cpp \
    && chmod -R a+rX /opt/llama.cpp \
    && rm -f /tmp/app.tar.gz

FROM ${BASE}

# Only the extracted tree is shipped: 137 entries, 1.6 GB, self-describing via
# RUNPATH=$ORIGIN, including the gfx1151 Tensile kernels under rocblas/library.
COPY --link --from=fetch /opt/llama.cpp /opt/llama.cpp

# ${PATH} is not expanded from the base image inside a Dockerfile, so write it
# out; /opt/llama.cpp goes first so it wins over any other llama-server.
ENV PATH=/opt/llama.cpp:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

# Same helper as the toolbox engine: `llama-bench` cannot read LLAMA_ARG_MODEL,
# which is how the compose model services name their model.
COPY --link llama-bench-wrapper /usr/local/bin/

# Fails the build if the asset is not runnable on this base (missing libstdc++
# or glibc) rather than at the first `compose up`. No GPU during the build, so
# the "failed to initialize ROCm: no ROCm-capable device" line is expected.
RUN llama-server --version
