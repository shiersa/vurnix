"""Composite honest gate: run the deterministic checkers and refuse to lie about the result.

Composes, in order: compile (does it build?), phantom (does every import resolve?), and
coverage (how many distinct non-trivial tests exist — with an optional ``--min-tests``
floor). Any failing checker is a BLOCK and the exit code is non-zero; there is no "mostly
green". Checkers that need extra inputs are reported SKIP with instructions rather than
silently omitted:

- integrity needs a before/after pair (``vurnix integrity snapshot`` first)
- mutation needs your test command (``vurnix mutation run <dir> -- <test-cmd>``)

Usage::

    vurnix gate <dir> [--min-tests N]     # exit 0 = PASS, 1 = BLOCK, 2 = usage
"""

import os
import sys

from . import compilegate, coverage, phantom


def run(args):
    nonflag = [a for a in args if not a.startswith('--')]
    if len(nonflag) != 1:
        sys.stderr.write("usage: vurnix gate <dir> [--min-tests N]\n")
        return 2
    root = os.path.abspath(nonflag[0])
    if not os.path.isdir(root):
        sys.stderr.write("gate: not a directory: %s\n" % root)
        return 2
    min_tests = 0
    if '--min-tests' in args:
        try:
            min_tests = int(args[args.index('--min-tests') + 1])
        except (IndexError, ValueError):
            sys.stderr.write("gate: --min-tests needs an integer\n")
            return 2

    blocks = []
    print("vurnix gate: %s" % root)

    lines, compile_failures = compilegate.check(root)
    for ln in lines:
        print("  %s" % ln)
    if compile_failures:
        blocks.append("compile: %d failure(s)" % compile_failures)

    phantoms = phantom.find_phantoms(root, os.path.join(root, '.deps'))
    if phantoms:
        print("  phantom: BLOCK — %d unresolvable import(s):" % len(phantoms))
        for rel, name in phantoms:
            print("    %s\t%s" % (rel, name))
        blocks.append("phantom: %d unresolvable import(s)" % len(phantoms))
    else:
        print("  phantom: OK — every import resolves")

    n_tests = coverage.count_all(root)
    if min_tests and n_tests < min_tests:
        print("  coverage: BLOCK — %d distinct non-trivial test(s) < floor %d" % (n_tests, min_tests))
        blocks.append("coverage: %d < %d" % (n_tests, min_tests))
    else:
        print("  coverage: %d distinct non-trivial test(s)%s"
              % (n_tests, " (floor %d met)" % min_tests if min_tests else ""))

    print("  integrity: SKIP (needs a before/after pair — `vurnix integrity snapshot` first)")
    print("  mutation: SKIP (needs your test command — `vurnix mutation run %s -- <test-cmd>`)"
          % nonflag[0])

    if blocks:
        print("RESULT: BLOCK")
        for b in blocks:
            print("  BLOCK %s" % b)
        return 1
    print("RESULT: PASS")
    return 0
