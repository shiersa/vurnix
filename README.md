# Vurnix

**A local-first software factory.** Deterministic multi-agent orchestration that turns
small local models (12B-class, on your own hardware) into working software — end to end,
from PRD to a clone-and-run repository.

> **Status: early development (alpha).** This release reserves the `vurnix` CLI entry
> point and ships an environment preflight. The pipeline lands in a later release.

## Why Vurnix

- **Weak-local-model first** — designed around small open-weight models running locally,
  not frontier APIs. The orchestration layer, not model size, does the heavy lifting.
- **Deterministic orchestration** — scheduling, gating, and verification are plain code:
  same input, same build plan. LLMs write code; they don't run the factory.
- **Self-evolving** — lessons and skills accumulate from every build and graduate into
  deterministic checks over time.
- **Fully autonomous** — PRD in, pushed clone-and-run repository out.

## Install

```sh
pip install vurnix     # or: uv tool install vurnix
```

```sh
vurnix info      # what this is
vurnix doctor    # preflight your environment
vurnix version
```

An `npm i -g vurnix` stub is also published to hold the name; the Python package is primary.

## Roadmap

- [ ] Pipeline release (build orchestration + verification gates)
- [ ] Hub (observability)
- [ ] Docs

## License

MIT — see [LICENSE](LICENSE). This covers the placeholder CLI; future components may
ship under their own terms.
