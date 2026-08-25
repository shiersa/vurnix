"""Vurnix command-line interface.

This 0.1.x release reserves the ``vurnix`` entry point and ships an
environment preflight; the pipeline lands in a later release.
"""

import argparse
import shutil
import sys

from . import __version__

REPO_URL = "https://github.com/shiersa/vurnix"

INFO = f"""\
Vurnix v{__version__} — the honest gate for AI-written code.

Deterministic, zero-dependency checkers that catch how AI agents game
test suites. A check that cannot run is not a check that passed.

  vurnix gate <dir>          compile + phantom-import + honest test count
  vurnix integrity ...       anti-weakening guard (snapshot | compare)
  vurnix coverage <dir>      distinct non-trivial test count
  vurnix mutation ...        test strength via mutation (mutants | run)
  vurnix phantom <dir>       imports that exist nowhere
  vurnix compile <dir>       four-language compile gate (py/js/go/java)

Verdicts are three-state — enforced by exit code, because
a check that cannot run is not a check that passed:

  0 PASS      everything measured, everything green
  1 BLOCK     a check failed (fail-dominant: beats UNPROVEN)
  2 usage     bad invocation
  3 UNPROVEN  nothing was actually measured (missing toolchain,
              zero tests, zero mutants, red baseline)

Extracted from the gate of a local-first autonomous coding pipeline;
usable with any agent, harness, or CI.

  Home: {REPO_URL}
"""


def doctor() -> int:
    """Preflight the environment for the upcoming pipeline."""
    git = shutil.which("git")
    docker = shutil.which("docker")
    checks = [
        ("python >= 3.10", sys.version_info >= (3, 10), sys.version.split()[0]),
        ("git", git is not None, git or "not found"),
        ("docker (optional)", True, docker or "not found"),
    ]
    failed = False
    for name, ok, detail in checks:
        print(f"  [{'ok' if ok else 'MISSING':>7}] {name}: {detail}")
        failed = failed or not ok
    return 1 if failed else 0


def _gate_dispatch(command, rest) -> int:
    """The honest-gate toolset. Dispatched before argparse: each subcommand owns its own
    argument contract (including `--`-separated test commands argparse would mangle)."""
    from . import compilegate, coverage, gate, integrity, mutation, phantom

    table = {
        "integrity": integrity.run,
        "coverage": coverage.run,
        "mutation": mutation.run,
        "phantom": phantom.run,
        "compile": compilegate.run,
        "gate": gate.run,
    }
    return table[command](rest)


GATE_COMMANDS = ("integrity", "coverage", "mutation", "phantom", "compile", "gate")


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in GATE_COMMANDS:
        return _gate_dispatch(argv[0], argv[1:])

    parser = argparse.ArgumentParser(
        prog="vurnix",
        description="Vurnix — the honest gate for AI-written code.",
    )
    parser.add_argument("--version", action="version", version=f"vurnix {__version__}")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("version", help="print the version")
    sub.add_parser("info", help="what Vurnix is and where it lives")
    sub.add_parser("doctor", help="preflight checks")
    sub.add_parser("gate", help="composite honest gate: compile + phantom + coverage")
    sub.add_parser("integrity", help="anti-weakening test guard (snapshot | compare)")
    sub.add_parser("coverage", help="count distinct non-trivial test functions")
    sub.add_parser("mutation", help="mutation testing (mutants | run)")
    sub.add_parser("phantom", help="find phantom imports (referenced but existing nowhere)")
    sub.add_parser("compile", help="four-language compile gate (py/js/go/java)")
    args = parser.parse_args(argv)

    if args.command == "version":
        print(f"vurnix {__version__}")
        return 0
    if args.command == "doctor":
        print(f"vurnix {__version__} preflight:")
        return doctor()
    print(INFO)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
