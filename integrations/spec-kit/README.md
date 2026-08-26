# Vurnix Honest Gate — Spec Kit extension

**The deterministic counterpart to LLM self-review.** Other quality
extensions ask the agent to audit its own tests with a rubric. This one
hands the judgment to executable code: [Vurnix](https://github.com/shiersa/vurnix)'s
zero-dependency checkers run compile + phantom-import + honest test count
and return one machine verdict, enforced by exit code:

| Exit | Verdict | Meaning |
|---|---|---|
| 0 | `PASS` | everything measured, everything green |
| 1 | `BLOCK` | a check failed — fix the cause, never the test |
| 3 | `UNPROVEN` | nothing was actually measured — never reported as success |

**A check that cannot run is not a check that passed** — a missing
toolchain, an empty test suite, or a missing `vurnix` install all exit 3
(`UNPROVEN`), not 0. The agent's role is reduced to running the script and
relaying the verdict verbatim; it cannot soften, reinterpret, or override it.

## Install

```sh
pip install vurnix    # the checkers (zero runtime dependencies)
specify extension add vurnix --from <release-zip-url>
```

The `after_implement` hook then offers the gate after every implementation
phase; you can also invoke it any time with `/speckit.vurnix.gate`.

## What it catches

- tests **weakened** to go green — via the honest test count (only distinct,
  non-trivial tests count; `assert True` and copy-paste padding don't)
- **invented imports** — modules referenced but existing nowhere
- code that **doesn't even build** — per file, four languages (py/js/go/java)
- **false "verified"** — a gate that measured nothing says so, with exit 3

For the full toolset (anti-weakening snapshots, mutation testing with a red
baseline guard), see [`vurnix`](https://github.com/shiersa/vurnix) itself.

## License

MIT
