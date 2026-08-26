---
description: "Execute the deterministic Vurnix honest gate (compile +
phantom-import + honest test count) over the implementation directory and
relay its machine verdict verbatim: PASS (exit 0) / BLOCK (exit 1) /
UNPROVEN (exit 3). The script judges; the agent does not."
---

# Vurnix Honest Gate

This command is deliberately small. Most quality gates in this ecosystem ask
an agent to *reason about* whether the tests are honest. This one does not:
the judgment is executable code with a three-state exit contract, and your
only job is to run it and act on the result. You never grade the code
yourself, and you never soften the verdict.

## Workflow

1. Determine the implementation directory for the current feature (default:
   the repository root, or the directory the user names).
2. Run the provided script:

   ```sh
   .specify/extensions/vurnix/scripts/bash/vurnix-gate.sh <dir>
   ```

   Pass `--min-tests N` after the directory if the feature's plan declares a
   test floor.
3. Act on the exit code — these rules are not negotiable:
   - **0 (PASS)** — report the gate summary and continue the workflow.
   - **1 (BLOCK)** — the implementation or its tests failed a deterministic
     check. Fix the *cause* named in the output. Never delete, skip, or
     weaken a test to clear a BLOCK; the gate's anti-weakening posture exists
     precisely to catch that move.
   - **3 (UNPROVEN)** — the gate measured nothing (missing toolchain, zero
     non-trivial tests, or vurnix itself not installed). Treat this exactly
     like "not done": add real tests or install the missing tool, then re-run.
     UNPROVEN is never reported as success. A check that cannot run is not a
     check that passed.
   - **2 (usage)** — fix the invocation and re-run.
4. Relay the gate's own output (including every `BLOCK`/`UNPROVEN` reason
   line) to the user verbatim. Do not summarize a red verdict into a softer
   sentence.

## Hard rules

- The exit code is the verdict. If your reading of the code disagrees with
  the gate, the gate wins and the disagreement goes to the user.
- Never mark a feature complete while the latest gate run is BLOCK or
  UNPROVEN.
- Re-run the gate after every fix round; only a fresh exit 0 counts.
