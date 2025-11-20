#!/usr/bin/env bash
set -euo pipefail

say() { printf "\033[1;32m==>\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33m==>\033[0m %s\n" "$*"; }
err() { printf "\033[1;31m==>\033[0m %s\n" "$*"; }

say "Base packages installed during image build; skipping apt-get."

NPM_PREFIX="${HOME}/.npm-global"
LOCAL_BIN="${HOME}/.local/bin"
PIPX_HOME="${HOME}/.local/pipx"
PIPX_BIN_DIR="${LOCAL_BIN}"
GOPATH="${HOME}/go"
GOCACHE="${HOME}/.cache/go-build"

export PATH="${NPM_PREFIX}/bin:${LOCAL_BIN}:$PATH"
export PIPX_HOME PIPX_BIN_DIR GOPATH GOCACHE

mkdir -p "${NPM_PREFIX}/bin" "${LOCAL_BIN}" "${PIPX_HOME}" "${GOPATH}/bin" "${GOCACHE}"
if ! command -v npm >/dev/null 2>&1; then
  err "npm not found; rebuild the devcontainer image."
  exit 1
fi
npm config set prefix "${NPM_PREFIX}" >/dev/null 2>&1 || true
pipx ensurepath >/dev/null 2>&1 || true

touch "${HOME}/.bashrc"
if ! grep -q '.npm-global/bin' "$HOME/.bashrc" 2>/dev/null; then
  printf '\n# ensure npm global installs are on PATH\nexport PATH="$HOME/.npm-global/bin:$PATH"\n' >> "$HOME/.bashrc"
fi

mkdir -p "${HOME}/.codex"
if [ -n "${OPENAI_API_KEY:-}" ]; then
  cat >"${HOME}/.codex/config.toml" <<'TOML'
preferred_auth_method = "apikey"
TOML
fi

if ! command -v poetry >/dev/null 2>&1; then
  say "Installing Poetry via pipx…"
  pipx install poetry
else
  say "Poetry already installed."
fi

if ! grep -q '.local/bin' "$HOME/.bashrc" 2>/dev/null; then
  printf '\n# ensure local bin is on PATH\nexport PATH="$HOME/.local/bin:$PATH"\n' >> "$HOME/.bashrc"
fi

hash -r || true

grep -q 'alias oai=' "${HOME}/.bashrc" 2>/dev/null || echo 'alias oai="openai"' >> "${HOME}/.bashrc" || true

say "Sanity checks for baked-in toolchain…"
if ! command -v node >/dev/null 2>&1; then
  err "node not found; rebuild the devcontainer image."
  exit 1
fi
node --version >/dev/null 2>&1 || { err "node failed to report a version."; exit 1; }

if ! command -v codex >/dev/null 2>&1; then
  err "codex CLI not found; rebuild the devcontainer image."
  exit 1
fi
codex --help >/dev/null 2>&1 || { err "codex CLI failed to respond."; exit 1; }

if ! command -v claude >/dev/null 2>&1; then
  err "claude CLI not found; rebuild the devcontainer image."
  exit 1
fi
claude --help >/dev/null 2>&1 || { err "claude CLI failed to respond."; exit 1; }

if ! command -v bd >/dev/null 2>&1; then
  err "bd CLI not found; rebuild the devcontainer image."
  exit 1
fi
bd --help >/dev/null 2>&1 || { err "bd CLI failed to respond."; exit 1; }

say "Toolchain ready."
