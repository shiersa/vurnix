#!/usr/bin/env bash
# Vurnix honest gate — deterministic three-state verdict for Spec Kit workflows.
#
# The verdict is computed by executable checkers (github.com/shiersa/vurnix),
# not by agent judgment: exit 0 = PASS, 1 = BLOCK, 3 = UNPROVEN, 2 = usage.
# An agent may relay this verdict; it may not override it.
#
# Usage: vurnix-gate.sh [<dir>] [extra vurnix gate args, e.g. --min-tests N]

TARGET="${1:-.}"
if [ "$#" -gt 0 ]; then shift; fi

if command -v vurnix >/dev/null 2>&1; then
  run_gate() { vurnix gate "$TARGET" "$@"; }
elif python3 -c "import vurnix" >/dev/null 2>&1; then
  run_gate() { python3 -m vurnix.cli gate "$TARGET" "$@"; }
else
  echo "vurnix-gate: UNPROVEN — vurnix is not installed, so nothing was checked."
  echo "vurnix-gate: a gate that cannot run is not a gate that passed."
  echo "vurnix-gate: install it first:  pip install vurnix   (zero runtime dependencies)"
  exit 3
fi

run_gate "$@"
rc=$?
case "$rc" in
  0)
    echo "vurnix-gate: PASS — everything measured, everything green."
    ;;
  1)
    echo "vurnix-gate: BLOCK — a deterministic check failed. Fix the code or add real tests;"
    echo "vurnix-gate: never weaken tests to go green (that is exactly what this gate catches)."
    ;;
  3)
    echo "vurnix-gate: UNPROVEN — the gate could not measure (missing toolchain or zero"
    echo "vurnix-gate: non-trivial tests). Not a failure — but never a pass."
    ;;
  *)
    echo "vurnix-gate: usage error (rc=$rc)." >&2
    ;;
esac
exit "$rc"
