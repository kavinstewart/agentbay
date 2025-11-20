FROM golang:1.24-bullseye AS bd-builder

WORKDIR /src

RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    go install github.com/steveyegge/beads/cmd/bd@latest

FROM mcr.microsoft.com/devcontainers/base:debian

ARG NODE_VERSION=20.19.5

ENV NODE_VERSION=${NODE_VERSION} \
    NODE_ROOT=/opt/node \
    TOOLS_PREFIX=/opt/tools \
    PATH=/opt/node/bin:/opt/tools/bin:/home/vscode/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    NPM_CONFIG_PREFIX=/opt/tools

RUN apt-get update -y \
 && apt-get install -y --no-install-recommends \
      ca-certificates \
      curl \
      git \
      jq \
      python3 \
      python3-dev \
      python3-pip \
      python3-venv \
      pipx \
      tar \
      xz-utils \
 && rm -rf /var/lib/apt/lists/*

RUN set -euxo pipefail; \
    arch="$(dpkg --print-architecture)"; \
    case "$arch" in \
      amd64) node_arch="linux-x64";; \
      arm64) node_arch="linux-arm64";; \
      armhf) node_arch="linux-armv7l";; \
      *) echo "Unsupported architecture: $arch" >&2; exit 1;; \
    esac; \
    tmpdir="$(mktemp -d)"; \
    cd "$tmpdir"; \
    curl -fsSLO "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-${node_arch}.tar.xz"; \
    curl -fsSLO "https://nodejs.org/dist/v${NODE_VERSION}/SHASUMS256.txt"; \
    grep " node-v${NODE_VERSION}-${node_arch}.tar.xz" SHASUMS256.txt | sha256sum -c -; \
    rm -rf "${NODE_ROOT}"; \
    tar -xJf "node-v${NODE_VERSION}-${node_arch}.tar.xz" -C /opt; \
    mv "/opt/node-v${NODE_VERSION}-${node_arch}" "${NODE_ROOT}"; \
    ln -sf "${NODE_ROOT}/bin/node" /usr/local/bin/node; \
    ln -sf "${NODE_ROOT}/bin/npm" /usr/local/bin/npm; \
    ln -sf "${NODE_ROOT}/bin/npx" /usr/local/bin/npx; \
    rm -rf "$tmpdir"

RUN mkdir -p "${TOOLS_PREFIX}/bin" \
 && npm install --global @openai/codex@latest @anthropic-ai/claude-code@latest \
 && find "${TOOLS_PREFIX}/bin" -maxdepth 1 -type f -exec chmod +x {} \;

COPY --from=bd-builder /go/bin/bd "${TOOLS_PREFIX}/bin/bd"

# Symlink /etc/environment to a writable tmpfs location mounted at runtime
RUN ln -sf /run/etc-environment /etc/environment
