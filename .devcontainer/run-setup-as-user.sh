#!/usr/bin/env bash
set -euo pipefail

TARGET_USER="${REMOTE_USER:-vscode}"
TARGET_UID="${REMOTE_UID:-1000}"
TARGET_GID="${REMOTE_GID:-1000}"
TARGET_HOME="/home/${TARGET_USER}"
WORKDIR="$(pwd)"

if [ "$(id -u)" -eq 0 ]; then
  install -d -m 0755 -o "${TARGET_UID}" -g "${TARGET_GID}" "${TARGET_HOME}"
fi

if [ "$(id -un)" = "${TARGET_USER}" ]; then
  HOME="${TARGET_HOME}" bash -lc "cd '${WORKDIR}' && .devcontainer/setup-bd.sh"
else
  runuser -u "${TARGET_USER}" -- bash -lc "cd '${WORKDIR}' && HOME='${TARGET_HOME}' .devcontainer/setup-bd.sh"
fi
