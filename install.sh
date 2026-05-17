#!/usr/bin/env bash
# Install the CSL skills into Claude Code's user skills directory by symlink,
# so edits in this repo apply immediately without re-running install.
set -euo pipefail

REPO_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
TARGET_DIR="${HOME}/.claude/skills/csl"

mkdir -p "${HOME}/.claude/skills"

if [ -e "${TARGET_DIR}" ] || [ -L "${TARGET_DIR}" ]; then
  if [ -L "${TARGET_DIR}" ] && [ "$(readlink "${TARGET_DIR}")" = "${REPO_DIR}" ]; then
    echo "Already linked: ${TARGET_DIR} -> ${REPO_DIR}"
    exit 0
  fi
  echo "ERROR: ${TARGET_DIR} already exists and is not the expected symlink." >&2
  echo "Remove it (rm -i \"${TARGET_DIR}\") and re-run." >&2
  exit 1
fi

ln -s "${REPO_DIR}" "${TARGET_DIR}"
echo "Linked: ${TARGET_DIR} -> ${REPO_DIR}"
echo "Claude Code will discover the skill on next launch."
