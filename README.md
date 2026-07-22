# Vurnix — the honest gate for AI-written code

AI coding agents don't just write bugs. Asked to "make the tests pass", they take
shortcuts a human reviewer rarely thinks to check for: they **delete the failing assert**,
**skip the test**, **pad the suite with `assert True`**, or **import modules that don't
exist anywhere**. The suite goes green; the code is still broken.

Vurnix is a set of **deterministic, zero-dependency checkers** that make those shortcuts
impossible to hide. No model in the loop, no heuristics you have to trust — every check is
plain code you can read, with a hard exit code.

```sh
pip install vurnix
vurnix gate ./myproject        # compile + phantom-import + honest test count, one verdict
```

**The design rule everything here follows: a check that cannot run is not a check that
passed.** Missing toolchain? That's a labelled `SKIP`, never a silent `OK`. Any failing
check is a `BLOCK` and a non-zero exit — there is no "mostly green".

## The checkers

| Command | Catches | Languages |
|---|---|---|
| `vurnix integrity` | tests being **weakened** to go green (deleted asserts, new skip/xfail, always-true asserts, deleted test functions) | py, js, go, java |
| `vurnix coverage` | **padded** test counts — only distinct, non-trivial tests count (`assert True` and copy-paste duplicates don't) | py, js, go, java |
| `vurnix mutation` | **weak** tests — mutate the implementation; a mutant your tests don't kill is a coverage gap with a file:line name | py + C-family |
| `vurnix phantom` | **invented imports** — a module referenced in code that exists nowhere (not stdlib, not local, not vendored) | py |
| `vurnix compile` | code that **doesn't even build**, per file, before anyone claims "tests pass" | py, js, go, java |
| `vurnix gate` | composite: compile + phantom + coverage floor, one honest verdict | — |

### `vurnix integrity` — the anti-weakening guard

Snapshot the test file before handing it to an agent; compare after:

```sh
vurnix integrity snapshot tests/test_api.py > before.json
# ... agent "fixes" the failing tests ...
vurnix integrity compare before.json tests/test_api.py
# WEAKENED: asserts dropped 17 -> 3
# integrity: test file WEAKENED — do NOT count this round as fixed.  (exit 1)
```

Delta-based: pre-existing skips are fine; only *new* weakening flags. Strengthening (adding
tests) always passes. When a test function disappears, it is named:

```
WEAKENED: test function(s) deleted/missing: test_redirect_302 (6 -> 5)
```

### `vurnix coverage` — the honest test-count floor

Prints one integer: the number of **distinct, non-trivial** test functions. A test counts
only if it makes a real assertion (or expects a raise), and identical bodies collapse to
one — so "write N easy copies" and "write N `assert True`" both count as what they are.

### `vurnix mutation` — test strength, measured

```sh
vurnix mutation run ./app --max 24 --strict --threshold 0.34 -- python -m pytest -q
# mutation: 9/13 killed — score 69%
```

A suite that only checks `status == 200` scores ~15% on a real CRUD app; a suite that
checks behaviour scores ~70%. Survivors are listed by file and mutation so the fix is
actionable. Stdlib AST for Python; conservative masked-regex operators for JS/Go/Java
(mutants that break syntax simply fail the run — the safe direction).

### `vurnix phantom` — imports that exist nowhere

Real example from our benchmarks: a 12B local model wrote `from models import UrlRequest`
and `from db import Database` — no `models.py`, no `db.py`, no such packages. Syntax checks
pass (it *is* valid syntax); the failure surfaces later as a cryptic install error. This
prints the file and the invented module, before anything runs. Host site-packages are
deliberately excluded from resolution, so "works on my machine" doesn't mask a missing
dependency.

## Why we built this

These checkers are extracted from the gate of a local-first autonomous coding pipeline we
run against small (12B-class) local models — an environment where every failure mode of
agentic coding shows up early and often. All of them earned their place by catching real
incidents, including:

- a cloud model, brought in to rescue a failing build, rewriting a 17-assertion test file
  down to 3 assertions to go green — blocked by `integrity`;
- theatre suites (assert-the-status-code-and-nothing-else) passing every gate until the
  mutation score exposed them (15% vs 69% on the same app);
- build-tool resolution failures being mistaken for "tests passed" — which is why SKIP is
  a first-class, labelled result and never an OK.

The orchestration pipeline itself is not part of this package; these are its trust
primitives, usable with any agent, harness, or CI.

## Install

```sh
pip install vurnix        # Python >= 3.10, zero runtime dependencies
vurnix gate --help
```

`js`/`go`/`java` checks use your existing `node`/`go`/`mvn`+`javac` toolchains when
present, and report labelled SKIPs when not.

An `npm i -g @vurnix/cli` stub is also published under the project's npm scope; the
Python package is primary.

## License

MIT — see [LICENSE](LICENSE).
