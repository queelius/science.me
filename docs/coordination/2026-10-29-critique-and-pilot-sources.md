# Design critique and real-data sources, 2026-10-29

Two reviews by Codex (`gpt-6-astra`, maximum reasoning effort, read-only, no access to the private worlds or the plans), written at Alex's request: how to improve science.me, and which public data sets would make good pilots. Claude checked the code citations against the source and the license claims against the publishers' pages before writing this. The verdicts below are Claude's.

## Critique

### Acted on

- **The container's `/out` had no quota.** It was a writable host bind mount, so a program could fill the host disk; the result-size cap bounded only what the host read. It is now a tmpfs inside the container's memory limit, and the result comes back on stdout, bounded (`1cd9a57`).
- **The worker image was a mutable tag.** A container origin now resolves `scienceme-worker:latest` (or `$SCIENCEME_WORKER_IMAGE`) once to its content id, runs every program on that id, and stamps it on each record as `image` (`1cd9a57`).
- **A Codex review of those fixes found two older gaps.**
  - A result under the 64 MiB cap could still cost the host far more memory while it was validated. A result is now capped by what its order can need, and must list one entry per target before it is validated.
  - Docker's default log has no rotation, so a program writing to stderr could fill the host disk. Containers now keep no Docker log (`f28c424`).
- **The tier 1 write-up overstated two things.** Coverage on the two channels was similar, but far below nominal on both, so "absorbed in the calibration sense" claimed too much. The power analysis is a sensitivity analysis, not proof the order test could not pass. `docs/tier1-results.md` now says both.

### Agreed, not yet done

1. **Forecasts as durable evidence.** "Forecasts are a rebuildable cache" holds only if programs are pure functions of the archive view and the seed. Nothing enforces that: a program can read the clock or OS randomness. Also, `ArchiveView` carries the current stream specs (`archive.py`), so adding a stream later changes what an old origin sees on a rebuild. The proposed fix: keep the first accepted forecast's work order, output digest and image id, and treat later runs as reproductions checked against it. This needs a design decision on what lives in git.
2. **One predictive object.** Scoring uses the floored pmf `q = (1 - ε)p + ε/K`; the wanted list uses the raw `p` (`gain.py`). Pick `q` and use it everywhere.
3. **Clones escape their losses.** A new program starts at zero cumulative advantage (`weights.py`), so re-freezing a losing program sheds its record, and many near-variants gain initial mass together. This needs an admission budget before outside contributors arrive. Lineage declarations cannot enforce one against an adversary.
4. **The wanted list double-counts.** It sums information target by target (`gain.py`). Ten targets that each separate the same two programs score ten bits; the bundle holds one. Measure it jointly or call it "summed marginal discrimination".
5. **Verdicts should carry their tested scope.** Claim verdicts compare packages, not mechanisms, and two programs covering one jurisdiction can support a verdict on a broader claim. Show the jurisdictions, weeks and channels actually tested beside each verdict.
6. **Replication is counted in worlds, not runs.** The 80 pending runs are 20 worlds, with the policies paired within each. Analyze them as paired comparisons, with uncertainty across worlds. The registered analysis stays as registered; this would be supplementary.
7. **Read-back needs more controls.** One planted liar caught is one positive control. Before relying on read-back, add several blinded positive and negative controls.
8. **Freeze times are self-reported.** Before outsiders contribute, accepted freezes need operator-issued receipts, or the external anchoring of spec 4.9.
9. **The Docker integration suite is optional.** It should be required before admitting outside programs.

### Noted, not adopted now

- Moving analysis policies (weights, verdicts, wanted list) out of the trusted kernel into versioned analysis over the record. It is probably right, but it is a restructuring with no forcing problem yet.
- Dropping rank preservation as a lens-transfer criterion. The tier 1 criterion stays as registered; this is a question for whatever replaces it.

## Real-data sources

Ranked by Codex for prospective scoring, revision handling, redistribution rights, informative matched pairs, and the work one person can sustain. The links were checked on 2026-10-28.

| Rank | Source | Cadence | License | A matched pair it could test |
|---|---|---|---|---|
| 1 | [CDC NHSN hospital respiratory data](https://data.cdc.gov/Public-Health-Surveillance/Weekly-Hospital-Respiratory-Data-HRD-Metrics-by-Ju/ua7e-t2fy) | weekly, preliminary Wednesday, final Friday | U.S. government work | humidity-dependent vs fixed transmission, same reporting lens |
| 2 | [EIA-930 hourly electricity demand](https://www.eia.gov/opendata/documentation.php) | hourly | redistribution permitted | thermal memory vs memoryless temperature response, on weekly counts of hours over a threshold (support 0 to 168) |
| 3 | [USGS daily streamflow](https://api.waterdata.usgs.gov/ogcapi/v1/collections/daily) | daily | public domain | catchment storage vs no carry-over |
| 4 | [NOAA USCRN](https://www.ncei.noaa.gov/access/crn/) | daily | public domain | wet/dry persistence vs independent days |
| 5 | [DOL ETA 539 unemployment claims](https://oui.doleta.gov/unemploy/DataDownloads.asp) | weekly | public domain, some exceptions | shared national layoff pressure vs independent states |
| 6 | [NOAA CO-OPS tides](https://api.tidesandcurrents.noaa.gov/api/prod) | six-minute | public domain unless annotated | correct vs displaced astronomical phase: a positive control, since the right answer is known |
| 7 | [BLS CES vintages](https://www.bls.gov/web/empsit/cesvininfo.htm) | monthly | public domain | lagged vs contemporaneous adjustment |
| 8 | [MTA daily ridership](https://data.ny.gov/Transportation/MTA-Daily-Ridership-and-Traffic-Beginning-2020/sayj-mze2) | daily | OPEN-NY terms | holiday displacement and rebound vs plain calendar |
| 9 | [RIVM wastewater](https://data.overheid.nl/dataset/80756-covid-19-nationale-sars-cov-2-afvalwatersurveillance) | weekly | CC BY 4.0 | seasonal transmission, same shedding and dilution |
| 10 | [arXiv first announcements](https://info.arxiv.org/help/rss.html) | daily | metadata CC0 | short-memory self-excitation vs calendar and trend |

Excluded:
- **FRED and ALFRED.** Their [terms](https://fred.stlouisfed.org/legal/) forbid use "in connection with the development or training of any software program or system or machine learning ... artificial intelligence". Economic series should come from BLS or DOL directly.
- **ENTSO-E.** No blanket reuse right for load and price data.
- **ERCOT.** Its access constraints are heavy beside EIA.
- **CDC wastewater.** Its providers have mixed terms.
- **OpenAlex and PyPI.** Not verified far enough.

Two cautions:
- Several jurisdictions are not several independent epidemics, as tier 1 showed. Comparisons need to plan for shared weather and shared seasons.
- The wanted-item schema requires an intervention, but public feeds have no controllable arms. Ranking them needs an explicit extension to the schema, not invented intervention labels.

### Capture started

Raw capture of both NHSN datasets started on 2026-10-29 in [science.me-sources](https://github.com/queelius/science.me-sources). An hourly puller stores each new version untouched, with its headers, hashes, retrieval time and the publisher's own update time. It refuses a capture whose rows, count and metadata do not agree on one version (checks added after the same Codex review). This is capture only. Spec 7.3 says tier 2 is not planned on the mechanism as built, and nothing here builds on it: no streams, no transforms, no missions. The data stays useful whatever the mechanism becomes, and a version not captured when it was current can only be recovered from someone else's archive (Delphi's, for NHSN).
