# science.me

A repository where a theory is a program, and the only evidence that counts is data published after the program was frozen.

A theory here is a frozen program that outputs a probability distribution for an observation that does not exist yet. When the observation is published, the program is scored on it with a floored log score. Programs are combined into a mixture weighted by their track record. A claim ("closing schools lowers admissions") is tested by matched pairs of programs that differ only in their stance on it. Where the programs disagree most is where an observation would tell them apart, so the mixture's disagreement ranks a wanted list of what to observe next. Agents write the programs. A small, deliberately dumb kernel freezes them, runs them in a sandbox, and scores them.

I built this to find out how much of the scientific method can be industrialized once theories are cheap to write and observations are the scarce thing.

## Status

Tier 1 pilot. The kernel works and is tested. Its data comes from synthetic epidemic worlds that publish weekly vintages on demand. The generator lives in a private companion repository, so programs cannot be fit to it. The pre-registered tier 1 evaluation has not been run yet. Of the two pilot experiments run so far, the read-back test passed (a blind reader caught a program whose description did not match its code) and the lens swap failed its criterion (adding a second observation channel did not leave the ranking of theories intact).

The design, including what is still open, is in [the design doc](docs/superpowers/specs/2026-10-23-science-me-design.md).

## Getting started

```
uv sync
uv run pytest -q
uv run scienceme check
```

Prospective forecasts run each program in a container with no network:

```
docker build -f scorer/Dockerfile -t scienceme-worker:latest .
```

Forecasts are not kept in git. Each one is a pure function of the registry and the archive, so `uv run scienceme predict --mission M --all` rebuilds them, after which `uv run scienceme standings --check` verifies the committed standings.

To contribute a program, agent or human, start with [SKILL.md](SKILL.md).

## Layout

| Path | What |
|---|---|
| `src/scienceme/` | The kernel: freezing, the as-of archive, the sandboxed worker, scoring, the mixture, claims, the wanted list |
| `programs/` | Programs: theories, observation lenses, baselines |
| `missions/` | What each mission forecasts, its claims, and its wanted list |
| `archive/` | Every published vintage, write-once |
| `registry/freezes.jsonl` | Every freeze and withdrawal, with its time |
| `standings.json`, `STANDINGS.md` | Where each mission stands, generated |

## License

MIT
