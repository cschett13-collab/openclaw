#!/bin/bash
# SessionStart hook for Claude Code on the web.
# Installs the pnpm workspace so tests, linters, type checks, and builds work
# in remote (cloud) sessions. Safe to run repeatedly (idempotent).
set -euo pipefail

# Only run in Claude Code's remote (web) environment. Local sessions manage
# their own dependencies and should not be slowed down by this hook.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-.}"

# Ensure the repo-pinned pnpm (packageManager field) is available.
corepack enable >/dev/null 2>&1 || true

# Sharp tries to source-build against a global libvips on some hosts and fails;
# force its prebuilt binary so install stays non-interactive and reliable.
export SHARP_IGNORE_GLOBAL_LIBVIPS=1

# Install the full pnpm workspace (core + bundled extensions). `install` (not
# `--frozen-lockfile`/`ci`) is used so the warmed container cache is reused on
# later runs and a drifting lockfile does not hard-fail the session.
pnpm install

echo "session-start: pnpm workspace install complete"
