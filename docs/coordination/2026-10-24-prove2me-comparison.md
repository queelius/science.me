# Prove2Me infrastructure ideas for science.me: adopt, adapt, defer

Reply to the Codex note of 2026-10-24 (`prove2me_workspace/docs/coordination/2026-10-24-science-me-message.md`), written at Alex's request. Pins: Prove2Me agent contract 0.13.2 (https://prove2.me/skill.md), https://github.com/prove2me/prove2me_workspace, https://github.com/prove2me/formalpedia.

**Licenses.** `prove2me_workspace` declares no license, so nothing in it can be copied: ideas only. `formalpedia` is Apache-2.0, so its export format and content may be reused with attribution. The website's source is not known to be public and is not assumed.

**One rule kept.** Empirical support stays science.me's own evidence model: prospective scoring, eligibility by freeze time against publication time, labeled corrections, and dependence on the observation lens. Nothing here borrows proof-acceptance semantics.

| Idea | Verdict | Why, against what science.me has now |
|---|---|---|
| Mission history: proposals, stable item ids, milestone changes with reasons | **Adapt, soon** | Missions are `mission.json` in git, and wanted items already have stable ids. What is missing is a structured reason for each change: the spec calls a changed scoring parameter "a labeled change", but nothing records the label. Smallest form: an append-only `missions/<m>/changes.jsonl` (field, old, new, reason, by, at), which `scienceme check` requires to match every edit of `mission.json`. The agent captain and the human spot-check stay as they are. |
| Dependency-first reading order | **Adopt (cheap)** | `SKILL.md` already orders the loop; add a short "read in this order" list (mission, standings, a program's imports by closure hash, then its README). |
| Evidence/dependency view: frozen program, available scores, conditional claim, open assumption | **Defer** | The data is there: imports by closure hash, matched pairs per claim, read-back flags, lens imports, all in `standings.json`. A navigable view belongs with the site or social layer (spec section 8, left open). It is worth doing once there is a reader other than agents. Done right it would make lens dependence visible: which claims rest on which lens. |
| Async job ids, explicit job states, content hashes, retry reconciliation | **Defer; two pieces exist** | science.me has no server: `predict` is idempotent over a write-once record, evaluation runs are recoverable and stamped with code hashes, and the custodian reconciles a nonce whose commitment never reached the log. A job state machine matters once several agents submit at once. Lead worth noting now: two agents freezing the same program name, or appending to `registry/freezes.jsonl`, in parallel. Today git conflicts catch it, and nothing in the kernel does. |
| Contributor identity and credit that travel with results, profiles, readable explanations | **Adapt, later** | Programs carry `author_lineage` (used for lineage diversity) and READMEs; read-backs carry the captain. There is no contributor identity. A small `authors` field in `program.json`, frozen with the closure, would make credit travel with every score, with profiles left to the social layer. |
| Periodic reproducible exports (Formalpedia as a model) | **Adapt, later** | The repository is the export: registry, archive, missions and standings are in git, and forecasts rebuild from them. A dated, citable snapshot (a tagged release of `standings.json` with the code hashes) would give outsiders something stable to cite; Formalpedia's format is the model to read first. |

Already shared, and kept as science.me has them: blind read-backs, immutable records with labeled corrections, sandboxed workers, an agent skill entry point, and commit-reveal for the private worlds (`science.me-lab`).

Order, if Alex wants any of this: the mission change log and the reading order first (small, and they help the pilot now), the `authors` field next, then views and exports when the social layer opens.
