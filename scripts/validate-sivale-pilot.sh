#!/usr/bin/env bash
#
# validate-sivale-pilot.sh — Real SiVale pilot evidence run (E8-S1 / E8-S2).
#
# WHY THIS EXISTS
# ---------------
# The deterministic conformance suite (tests/conformance/*) proves the invariants
# with faked external tools so it can run in CI. It deliberately uses
# `runtime = "none"`, an always-free port probe and no real tmux/Kiro, and it
# does NOT spawn concurrent processes. That is valid conformance, but E8-S1
# requires *operational* evidence over the REAL SiVale lifecycle: real
# docker-compose runtime, real ports, tmux/Kiro when enabled and genuinely
# concurrent worktrees. Partial-failure/rollback is NOT part of this operational
# pilot (see SCOPE below): it is covered deterministically by the E7 conformance
# suite because a real partial failure is not reproducible.
#
# This script is that real pilot. It is NOT run in CI. Run it on the real SiVale
# environment (e.g. the SiVale EC2) against a checkout that has the real
# `.ramalio.toml`. It captures structured evidence under
# docs/evidence/ so the E8 closure has real proof, not a simulation.
#
# SCOPE: this script exercises the real lifecycle end to end (init, concurrent
# isolation, real runtime/ports, tmux/Kiro as configured, branch-only adopt,
# destroy cleanup). It does NOT deliberately sabotage Docker to fabricate a
# partial failure; partial-failure/rollback is covered deterministically by the
# E7 conformance suite (tests/conformance + tests/unit/test_hook_transaction_journal).
# If you want a real partial-failure sample here, induce it manually (e.g. an
# invalid compose file for one target) and record the outcome.
#
# It fails closed: if a required tool is missing it aborts instead of pretending
# success (INV-05 / E9-S0: no silent workaround).
#
# USAGE
# -----
#   scripts/validate-sivale-pilot.sh <repo-path> <target-A> <target-B>
#
# Requirements on the host: git, docker + docker compose, tmux (if the config
# enables the tmux capability), and ramalio installed (pip install -e .).
#
set -euo pipefail

REPO="${1:?repo path required}"
TARGET_A="${2:?first target required}"
TARGET_B="${3:?second target required}"

EVIDENCE_DIR="$(cd "$(dirname "$0")/.." && pwd)/docs/evidence"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="${EVIDENCE_DIR}/sivale-pilot-${STAMP}.md"
mkdir -p "${EVIDENCE_DIR}"

fail() { echo "FATAL: $*" >&2; exit 1; }

require() {
  command -v "$1" >/dev/null 2>&1 || fail "required tool '$1' not found on PATH; \
this is a REAL pilot and must not be faked"
}

require git
require ramalio
require docker
docker compose version >/dev/null 2>&1 || fail "'docker compose' not available"
# tmux is only required if the project's config enables the tmux capability.
if grep -q '\[capabilities.tmux\]' "${REPO}/.ramalio.toml" 2>/dev/null; then
  require tmux
fi

run() {
  # Run an ramalio command inside the repo, echo it and append to evidence.
  echo "### \$ ramalio $*" | tee -a "${OUT}"
  ( cd "${REPO}" && ramalio "$@" ) 2>&1 | tee -a "${OUT}"
  echo "" | tee -a "${OUT}"
}

{
  echo "# SiVale real pilot evidence (E8-S1 / E8-S2)"
  echo ""
  echo "- timestamp (UTC): ${STAMP}"
  echo "- repo: ${REPO}"
  echo "- targets: ${TARGET_A}, ${TARGET_B}"
  echo "- host git: $(git --version)"
  echo "- host docker: $(docker --version)"
  echo "- host compose: $(docker compose version | head -1)"
  echo ""
  echo "> This evidence was produced by scripts/validate-sivale-pilot.sh against"
  echo "> the REAL SiVale configuration (docker-compose runtime, ports, tmux/Kiro"
  echo "> as configured). It is the operational counterpart to the deterministic"
  echo "> conformance suite, not a substitute for it."
  echo ""
} > "${OUT}"

echo ">>> doctor (readiness with real tools)"
run doctor

echo ">>> two genuinely concurrent inits (E8-S1 R6 / AC-03)"
# Concurrency via real background processes, not sequential calls.
# NOTE: `wait` is run with `set +e` so a non-zero child does not abort the
# script before we capture BOTH return codes and logs (this script exists to
# record evidence of failures too, not only success).
( cd "${REPO}" && ramalio init "${TARGET_A}" ) >"${OUT}.a" 2>&1 &
PID_A=$!
( cd "${REPO}" && ramalio init "${TARGET_B}" ) >"${OUT}.b" 2>&1 &
PID_B=$!
set +e
wait "${PID_A}"; RC_A=$?
wait "${PID_B}"; RC_B=$?
set -e
{
  echo "### concurrent init ${TARGET_A} (rc=${RC_A})"; cat "${OUT}.a"
  echo "### concurrent init ${TARGET_B} (rc=${RC_B})"; cat "${OUT}.b"
  echo ""
} >> "${OUT}"
rm -f "${OUT}.a" "${OUT}.b"
[ "${RC_A}" -eq 0 ] && [ "${RC_B}" -eq 0 ] || fail "concurrent init failed (rc ${RC_A}/${RC_B})"

echo ">>> list / status (real runtime + ports)"
run list
run status "${TARGET_A}"
run status "${TARGET_B}"

echo ">>> start/stop with real runtime + tunnel/tmux ordering"
run start "${TARGET_A}"
run status "${TARGET_A}"
run stop "${TARGET_A}"

echo ">>> Kiro integration (only if enabled in the config)"
# E8-S1 R10: exercise --open kiro when the config enables it. Opening a real
# interactive tool is not always automatable; when the integration is enabled we
# attempt it and record the outcome, otherwise we mark it as a manual step.
if grep -q '\[integrations.kiro\]' "${REPO}/.ramalio.toml" 2>/dev/null; then
  echo "### \$ ramalio start ${TARGET_A} --open kiro" | tee -a "${OUT}"
  if ( cd "${REPO}" && ramalio start "${TARGET_A}" --open kiro ) >>"${OUT}" 2>&1; then
    echo "(kiro opened; verify the session was created from the worktree)" | tee -a "${OUT}"
  else
    echo "MANUAL: --open kiro could not be automated here; open Kiro manually" \
      "from the worktree and record the result." | tee -a "${OUT}"
  fi
  echo "" | tee -a "${OUT}"
else
  echo "(kiro integration not enabled in this config; skipped)" | tee -a "${OUT}"
fi

echo ">>> adopt branch-only (E8-S1: incorporate existing work)"
# Create a genuine branch-only scenario: destroy B's worktree while preserving
# its branch (SiVale sets delete_on_destroy=false), then adopt B so the worktree
# is recreated for the preexisting branch. This exercises real branch-only
# adoption, not merely re-adopting a compatible existing workspace.
run destroy "${TARGET_B}"
run adopt "${TARGET_B}"

echo ">>> destroy both (real cleanup: tunnel before port/worktree)"
run destroy "${TARGET_A}"
run destroy "${TARGET_B}"

echo ">>> final doctor (no stale locks / leftover runtime)"
run doctor

{
  echo "## Result"
  echo ""
  echo "Fill in the parity verdict per E8-S1 R1/R12 after reviewing the captured"
  echo "output: init, concurrent isolation, runtime identities, ports, tmux/Kiro,"
  echo "branch-only adopt, destroy cleanup. Partial-failure/rollback is covered"
  echo "deterministically by the E7 conformance suite; if a real partial-failure"
  echo "sample is needed, induce it manually and record it here. Classify any gap"
  echo "as CORE_GAP / CONFIG_GAP / CAPABILITY_GAP / INTEGRATION_GAP / PROJECT_LOCAL"
  echo "/ OUT_OF_SCOPE."
} >> "${OUT}"

echo "Evidence written to: ${OUT}"
