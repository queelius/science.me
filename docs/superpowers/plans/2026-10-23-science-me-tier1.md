# science.me Tier 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the science.me kernel and the private synthetic worlds, then run tier 1's pre-registered success criteria (spec 7.3, criterion 1).

**Architecture:** Two repositories. The public repository `science.me` holds the `scienceme` package (the kernel), the program library, missions, the as-of archive, the append-only registry and prospective record, and the generated standings. The private repository `science.me-worlds` holds the generators, the custodian that releases vintages into the public archive, and the tier 1 evaluation harness, which alone knows ground truth. Programs run in a worker that sees only the archive as of the origin and the program's dependency closure: a Docker container with no network for prospective missions, in-process for simulation studies.

**Tech Stack:** Python 3.13, uv, pydantic 2, numpy, scipy, pytest with pytest-cov, Docker.

**Spec:** `docs/superpowers/specs/2026-10-23-science-me-design.md` (0.8.1). Scope is tier 1 only. Tier 2 (NHSN) gets its own plan once criterion 1 passes; the deferred list is at the end.

## Global Constraints

- Python >= 3.13. Runtime dependencies are exactly `pydantic>=2.9`, `numpy>=2.1`, `scipy>=1.14`; dev dependencies `pytest>=8`, `pytest-cov>=5`. uv manages both repositories; `uv.lock` is committed.
- Every persisted object is a pydantic model deriving from `Frozen` (`ConfigDict(frozen=True, extra="forbid")`), stored as JSON or JSONL. No Markdown or regex parsing of structured data. `STANDINGS.md`, READMEs and read-back summaries are output or prose only.
- No library function reads the wall clock. Anything time-dependent takes `now: datetime` (timezone-aware UTC). Only the two CLIs call `datetime.now(UTC)`.
- Append-only stores (registry, archive captures, prospective record, wanted lists, rankings) never rewrite. A write that would overwrite raises.
- Log scores are in nats. The scored distribution is `(1 - eps) * pmf + eps * Uniform{0..support_max}` (spec 4.3 as corrected in 0.8.1).
- Isolation order is `NONE < PROCESS < CONTAINER`. A mission's `required_isolation` is a floor. Public missions require `CONTAINER`.
- Shared vocabulary (Part A seeds and Part B worlds must agree): stream roles `admissions`, `ed-visits`, `covariate-x`, `school-term`; intervention variables `schools_closed`, `vaccinate_fraction`; claim ids `covariate-x`, `covariate-x-flat`, `school`.
- Coverage at the end of Part A: `uv run pytest --cov=scienceme --cov-report=term-missing` reports >= 90% line coverage of `src/scienceme`.
- No U+2014 em-dash characters in any file (a write hook rejects them).
- Commit at least once per task. Every commit message ends with these two lines:
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`
  `Claude-Session: https://claude.ai/code/session_014ysBBpk9BBJvD9JzT1xKWM`
- Part A code never imports `scienceme_worlds` or reads `../science.me-worlds`. Task 17's implementer must not read Part B of this plan or the worlds repository; the seed library is written from general epidemiology, not from the generator.

## Review Focus

1. A program returns a pmf with NaN or negative mass, mass outside `[0, support_max]`, or something that is not a `Pmf`: only that target is unscored and the rest of the origin proceeds (Task 7).
2. A program hangs or exhausts memory in the container: the container is killed, every target in that run is unscored with reason `timeout`, and no container is left running (Task 8).
3. `predict` is re-run after new freezes or new arms: only missing (stream, week, program) files are written, and a program frozen after an origin's publication is never run for it (Task 9).
4. A program directory is edited after freezing: the run is skipped with reason `modified-after-freeze` and never scored under the old hash (Task 9).
5. The resolution vintage is not yet published, or a week is missing from it: the target stays pending, is never scored as zero, and standings report the pending count (Tasks 10 and 15).

---

## Part A: the kernel (public repository, `/home/spinoza/github/science.me`)

```
pyproject.toml  uv.lock  .gitignore
src/scienceme/
  workspace.py     Workspace paths; write-once JSON and JSONL helpers
  pmf.py           Pmf; mix; floored log probability and CDF
  model.py         Frozen; Isolation; Timing; Intervention; StreamKind; StreamSpec; Row; Vintage; Capture; Target; TargetFilter; validate_vintage
  mission.py       Claim; Candidate; WantedItem; Mission; mission_streams; wanted-list IO
  manifest.py      Tag; InterfaceVar; PairDecl; ProgramManifest; closure_hash; supports; in_scope; validate_pair
  registry.py      Freeze; Withdrawal; Registry
  archive.py       Archive; ArchiveView
  sdk.py           Context; imports_of (what program authors import)
  worker_entry.py  WorkOrder; Prediction; Failure; WorkResult; execute; main
  worker.py        build_order; prepare_sandbox; run_order; scorer_hash; worker_image
  record.py        PredictionRecord; UnscoredRecord; RecordStore
  predict.py       Skip; Run; OriginReport; run_origin; run_all
  scoring.py       PointScore; point_score; ResolvedTarget; Resolution; resolve
  weights.py       MixtureStep; Advantages; normalized_weights; run_mixture; regime_tv
  calibration.py   Calibration; calibration
  claims.py        Verdict; PairStanding; ClaimStanding; pair_standing; summarize; find_pairs; claim_standings
  gain.py          information_gain; RankedItem; Ranking; rank_wanted; choose; save_ranking; load_latest_ranking
  readback.py      CaptainVerdict; Readback; ReadbackFlag; load_readback; flags; packet
  standings.py     ProgramStanding; StreamStanding; Indicators; Standings; compute; render; write_all; check_all
  cli.py           main
scorer/Dockerfile  scorer/requirements.lock
tests/             one module per source module; conftest.py
programs/  missions/  archive/  registry/  scores/
SKILL.md  STANDINGS.md  standings.json  .github/workflows/check.yml
```

### Task 1: Project scaffold and Pmf

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `src/scienceme/__init__.py`, `src/scienceme/pmf.py`
- Test: `tests/test_pmf.py`

**Interfaces:**
- Produces:
  ```python
  class PmfError(ValueError): ...
  class Pmf(BaseModel):            # frozen; lo: int; p: tuple[float, ...]
      # invariants: all finite, >= 0, |sum - 1| <= 1e-9, p[0] > 0, p[-1] > 0
      @classmethod
      def from_probs(cls, lo: int, probs: Sequence[float]) -> "Pmf"   # raw |sum - 1| <= 1e-6, trims zero tails, renormalizes
      @classmethod
      def point(cls, value: int) -> "Pmf"
      @classmethod
      def uniform(cls, lo: int, hi: int) -> "Pmf"                     # inclusive
      @classmethod
      def from_samples(cls, samples: Sequence[int]) -> "Pmf"
      @property
      def hi(self) -> int                                             # inclusive
      def prob(self, y: int) -> float
      def cdf(self, y: int) -> float                                  # P(Y <= y)
      def entropy(self) -> float                                      # nats
      def within(self, lo: int, hi: int) -> bool
  def mix(pmfs: Sequence[Pmf], weights: Sequence[float]) -> Pmf
  def floored_log_prob(pmf: Pmf, y: int, eps: float, support_max: int) -> float
  def floored_cdf(pmf: Pmf, y: int, eps: float, support_max: int) -> float
  ```

- [ ] **Step 1: Write `pyproject.toml` and `.gitignore`**

```toml
[project]
name = "scienceme"
version = "0.1.0"
requires-python = ">=3.13"
dependencies = ["pydantic>=2.9", "numpy>=2.1", "scipy>=1.14"]

[project.scripts]
scienceme = "scienceme.cli:main"

[dependency-groups]
dev = ["pytest>=8", "pytest-cov>=5"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra"
markers = ["docker: needs a working docker daemon; run with --docker"]

[tool.coverage.run]
branch = true
source = ["scienceme"]
```

`.gitignore`: `.venv/`, `__pycache__/`, `.coverage`, `.pytest_cache/`.

- [ ] **Step 2: Write the failing tests**

```python
import math
import pytest
from scienceme.pmf import Pmf, PmfError, mix, floored_log_prob, floored_cdf

def test_from_probs_trims_zero_tails():
    p = Pmf.from_probs(3, [0.0, 0.25, 0.75, 0.0])
    assert (p.lo, p.p, p.hi) == (4, (0.25, 0.75), 5)

@pytest.mark.parametrize("probs", [[-0.1, 1.1], [float("nan"), 1.0], [0.5, 0.4]])
def test_from_probs_rejects_invalid(probs):
    with pytest.raises(PmfError):
        Pmf.from_probs(0, probs)

def test_prob_and_cdf_outside_support():
    p = Pmf.from_probs(2, [0.5, 0.5])
    assert (p.prob(1), p.prob(3), p.cdf(1), p.cdf(2), p.cdf(99)) == (0.0, 0.5, 0.0, 0.5, 1.0)

def test_mix_aligns_supports():
    m = mix([Pmf.point(0), Pmf.point(10)], [0.9, 0.1])
    assert (m.lo, m.hi) == (0, 10)
    assert m.prob(0) == pytest.approx(0.9) and m.prob(10) == pytest.approx(0.1)

def test_entropy_in_nats():
    assert mix([Pmf.point(0), Pmf.point(1)], [0.5, 0.5]).entropy() == pytest.approx(math.log(2))

def test_floor_bounds_the_loss():
    assert floored_log_prob(Pmf.point(0), 50, eps=0.01, support_max=99) == pytest.approx(math.log(0.01 / 100))

def test_floored_cdf():
    assert floored_cdf(Pmf.point(0), 0, eps=0.01, support_max=99) == pytest.approx(0.99 + 0.01 / 100)

def test_from_samples_keeps_interior_zeros():
    p = Pmf.from_samples([1, 1, 2, 4])
    assert (p.lo, p.p) == (1, (0.5, 0.25, 0.0, 0.25))

def test_json_round_trip():
    p = Pmf.from_probs(5, [0.2, 0.3, 0.5])
    assert Pmf.model_validate_json(p.model_dump_json()) == p
```

- [ ] **Step 3: Run to verify failure.** `uv sync && uv run pytest tests/test_pmf.py -q` fails with `ModuleNotFoundError: scienceme.pmf`.
- [ ] **Step 4: Implement `src/scienceme/pmf.py`.** Pmf is a frozen pydantic model, so it serializes for free; numeric methods use `np.asarray(self.p)`. `floored_log_prob` is `log((1 - eps) * pmf.prob(y) + eps / (support_max + 1))`, and `floored_cdf` is `(1 - eps) * pmf.cdf(y) + eps * (min(max(y, -1), support_max) + 1) / (support_max + 1)`.
- [ ] **Step 5: Run to verify pass.** `uv run pytest tests/test_pmf.py -q` passes.
- [ ] **Step 6: Commit.** `git add -A && git commit` with subject `feat: project scaffold and Pmf`.

### Task 2: Workspace and data model

**Files:**
- Create: `src/scienceme/workspace.py`, `src/scienceme/model.py`, `tests/conftest.py`
- Test: `tests/test_model.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  ```python
  # workspace.py
  @dataclass(frozen=True)
  class Workspace:
      root: Path
      programs: Path; missions: Path; archive: Path; scores: Path   # properties: root / name
      registry: Path                                                # property: root / "registry" / "freezes.jsonl"
      @classmethod
      def create(cls, root: Path) -> "Workspace"                    # makes the directories
  class WriteOnceError(FileExistsError): ...
  def write_new(path: Path, model: BaseModel) -> None               # creates parents; raises WriteOnceError if it exists
  def read_model[M: BaseModel](path: Path, cls: type[M]) -> M
  def append_jsonl(path: Path, model: BaseModel) -> None
  def read_jsonl[T](path: Path, adapter: TypeAdapter[T]) -> list[T] # [] if absent
  # model.py
  class Frozen(BaseModel): model_config = ConfigDict(frozen=True, extra="forbid")
  class ModelError(ValueError): ...
  class Isolation(StrEnum): NONE = "none"; PROCESS = "process"; CONTAINER = "container"
      def at_least(self, other: "Isolation") -> bool
  class Timing(StrEnum): START_OF_WEEK = "start_of_week"
  class Intervention(Frozen): variable: str; value: float; start_week: int
      end_week: int | None = None; jurisdictions: tuple[str, ...] | None = None; timing: Timing = Timing.START_OF_WEEK
      def active(self, week: int, jurisdiction: str) -> bool
  class StreamKind(StrEnum): COUNT = "count"; COVARIATE = "covariate"
  class StreamSpec(Frozen): id: str; world: str; role: str; kind: StreamKind; jurisdictions: tuple[str, ...]
      support_max: int | None = None; intervention: Intervention | None = None
      parent: str | None = None; first_issue: int = 0; fulfills: str | None = None
  class Row(Frozen): jurisdiction: str; week: int; value: float
  class Vintage(Frozen): stream: str; issue: int; rows: tuple[Row, ...]
  class Capture(Frozen): vintage: Vintage; published_at: AwareDatetime; source: str; sha256: str
      @classmethod
      def make(cls, vintage: Vintage, published_at: datetime, source: str) -> "Capture"
  class Target(Frozen): stream: str; jurisdiction: str; reference_week: int; horizon: int   # horizon >= 0
      resolution_lag: int = 1                                       # >= 1; the forecast is of the value reported at this lag
      @property
      def target_week(self) -> int
      @property
      def resolution_issue(self) -> int                             # target_week + resolution_lag
  class TargetFilter(Frozen): streams: tuple[str, ...] | None = None; roles: tuple[str, ...] | None = None
      jurisdictions: tuple[str, ...] | None = None; horizons: tuple[int, ...] | None = None
      def matches(self, target: Target, spec: StreamSpec) -> bool  # None means any
  def validate_vintage(spec: StreamSpec, vintage: Vintage) -> None  # raises ModelError
  ```
- Produces for tests (`tests/conftest.py`): `T0 = datetime(2026, 10, 1, tzinfo=UTC)`; `at(hours: float) -> datetime`; fixture `ws` (a `Workspace.create(tmp_path)`); `count_spec(id="w/adm", jurisdictions=("A", "B"), support_max=1000, **kw) -> StreamSpec` with `world="w", role="admissions"`; `covariate_spec(id="w/x", role="covariate-x", **kw) -> StreamSpec`.

- [ ] **Step 1: Write the failing tests**

```python
def test_target_week():
    assert Target(stream="w/adm", jurisdiction="A", reference_week=10, horizon=3).target_week == 13

def test_filter_none_matches_and_fields_restrict():
    t, spec = Target(stream="w/adm", jurisdiction="A", reference_week=1, horizon=0), count_spec()
    assert TargetFilter().matches(t, spec)
    assert not TargetFilter(jurisdictions=("B",)).matches(t, spec)
    assert TargetFilter(roles=("admissions",), horizons=(0,)).matches(t, spec)

def test_count_vintage_validation():
    spec = count_spec(jurisdictions=("A",), support_max=100)
    validate_vintage(spec, Vintage(stream="w/adm", issue=5, rows=(Row(jurisdiction="A", week=4, value=7.0),)))
    for bad in (Row(jurisdiction="A", week=5, value=7.0), Row(jurisdiction="A", week=4, value=101.0),
                Row(jurisdiction="A", week=4, value=2.5), Row(jurisdiction="B", week=4, value=1.0)):
        with pytest.raises(ModelError):
            validate_vintage(spec, Vintage(stream="w/adm", issue=5, rows=(bad,)))

def test_covariate_rows_may_lead_the_issue():
    validate_vintage(covariate_spec(jurisdictions=("A",)), Vintage(stream="w/x", issue=5, rows=(Row(jurisdiction="A", week=8, value=-0.3),)))

def test_count_spec_needs_support_max_and_arm_needs_parent():
    with pytest.raises(ValidationError):
        count_spec(support_max=None)
    with pytest.raises(ValidationError):
        count_spec(intervention=Intervention(variable="schools_closed", value=1.0, start_week=3))

def test_capture_hash_is_content_hash():
    v = Vintage(stream="w/adm", issue=1, rows=(Row(jurisdiction="A", week=0, value=3.0),))
    a, b = Capture.make(v, at(0), "test"), Capture.make(v, at(5), "test")
    assert a.sha256 == b.sha256 and a.sha256.startswith("sha256:")
    with pytest.raises(ValidationError):
        Capture(vintage=v, published_at=at(0), source="test", sha256="sha256:" + "0" * 64)

def test_isolation_order():
    assert Isolation.CONTAINER.at_least(Isolation.PROCESS) and not Isolation.NONE.at_least(Isolation.PROCESS)

def test_write_new_refuses_overwrite(ws):
    path = ws.root / "x.json"
    write_new(path, Row(jurisdiction="A", week=0, value=1.0))
    with pytest.raises(WriteOnceError):
        write_new(path, Row(jurisdiction="A", week=0, value=2.0))
```

- [ ] **Step 2: Run to verify failure.** `uv run pytest tests/test_model.py -q` fails on import.
- [ ] **Step 3: Implement `workspace.py` and `model.py`.** `StreamSpec.id` uses a pydantic `pattern` of one or more `[a-z0-9.~-]+` segments joined by `/` (it becomes a directory path). Validators: COUNT needs `support_max >= 0`; an intervention needs a parent. `Capture`'s validator recomputes `sha256:` + hex of `vintage.model_dump_json()` and rejects a mismatch. `validate_vintage` checks: stream id matches; jurisdictions are in the spec; no duplicate (jurisdiction, week); for COUNT, `week < issue`, the value is integer-valued, and `0 <= value <= support_max`.
- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5: Commit** with subject `feat: workspace and data model`.

### Task 3: Missions and wanted lists

**Files:**
- Create: `src/scienceme/mission.py`
- Modify: `tests/conftest.py` (add `make_mission`)
- Test: `tests/test_mission.py`

**Interfaces:**
- Consumes: `Frozen`, `StreamSpec`, `StreamKind`, `Target`, `TargetFilter`, `Isolation`, `Workspace`, `write_new`, `read_model`, `append_jsonl`, `read_jsonl`.
- Produces:
  ```python
  class MissionError(ValueError): ...
  class Claim(Frozen): id: str; statement: str; scope: TargetFilter; weight: float = 0.0
  class Candidate(Frozen): stream: StreamSpec; targets: tuple[Target, ...]   # stream has intervention and parent; targets on stream.id
  class WantedItem(Frozen): id: str; proposed_by: str; candidate: Candidate; cost: float = 1.0; fulfiller: str = "custodian"
  class Mission(Frozen):
      name: str; epoch: int = 1; captain: str; streams: tuple[str, ...]; horizons: tuple[int, ...]
      first_issue: int; last_issue: int; resolution_lag: int            # >= 1
      epsilon: float; tau: float; half_life_weeks: float                # 0 < eps < 1; tau > 0; finite half-life > 0
      coverage_min: float; claim_threshold_nats: float; regime_flag_tv: float; exploration_reserve: float
      required_isolation: Isolation; run_timeout_s: int = 300; claims: tuple[Claim, ...] = ()
      def targets(self, spec: StreamSpec, reference_week: int) -> list[Target]   # each with resolution_lag = self.resolution_lag
  def load_mission(ws: Workspace, name: str) -> Mission                # missions/<name>/mission.json
  def save_mission(ws: Workspace, mission: Mission) -> None             # the captain's file; may be replaced
  def mission_streams(mission: Mission, specs: Iterable[StreamSpec]) -> list[StreamSpec]   # ids in mission.streams plus specs whose parent is in it; sorted by id
  def load_wanted(ws: Workspace, mission: str) -> list[WantedItem]     # missions/<name>/wanted.jsonl
  def append_wanted(ws: Workspace, mission: str, item: WantedItem) -> None   # MissionError on a duplicate id
  ```
- Produces for tests: `make_mission(**overrides) -> Mission` with defaults `name="m", captain="test", streams=("w/adm",), horizons=(0, 1), first_issue=1, last_issue=10, resolution_lag=2, epsilon=0.01, tau=2.0, half_life_weeks=8.0, coverage_min=0.8, claim_threshold_nats=3.0, regime_flag_tv=0.5, exploration_reserve=0.2, required_isolation=Isolation.NONE`.

`targets(spec, r)` returns `[]` unless `spec.kind` is COUNT and `max(self.first_issue, spec.first_issue) <= r <= self.last_issue`. It enumerates jurisdictions in spec order, then horizons ascending, and for an intervention stream drops targets whose `target_week < intervention.start_week`.

- [ ] **Step 1: Write the failing tests**

```python
def test_targets_for_a_base_stream():
    assert make_mission().targets(count_spec(), 4) == [
        Target(stream="w/adm", jurisdiction=j, reference_week=4, horizon=h, resolution_lag=2) for j in ("A", "B") for h in (0, 1)]

def test_arm_targets_start_at_first_issue_and_intervention_start():
    arm = count_spec(id="w/adm~close", jurisdictions=("A",), parent="w/adm", first_issue=6,
                     intervention=Intervention(variable="schools_closed", value=1.0, start_week=7, end_week=9))
    m = make_mission()
    assert m.targets(arm, 5) == []
    assert [t.target_week for t in m.targets(arm, 6)] == [7]

def test_covariate_streams_have_no_targets():
    assert make_mission().targets(covariate_spec(), 4) == []

def test_resolution_issue_and_lag_validation():
    assert make_mission().targets(count_spec(), 4)[1].resolution_issue == 7
    with pytest.raises(ValidationError):
        make_mission(resolution_lag=0)

def test_mission_streams_include_arms_of_base_streams():
    arm = count_spec(id="w/adm~a", parent="w/adm", intervention=Intervention(variable="schools_closed", value=1.0, start_week=3))
    other = count_spec(id="v/adm", world="v")
    got = mission_streams(make_mission(streams=("w/adm", "w/x")), [arm, other, count_spec(), covariate_spec()])
    assert [s.id for s in got] == ["w/adm", "w/adm~a", "w/x"]

def test_mission_and_wanted_round_trip(ws):
    save_mission(ws, make_mission())
    assert load_mission(ws, "m") == make_mission()
    arm = count_spec(id="w/adm~a", parent="w/adm", intervention=Intervention(variable="schools_closed", value=1.0, start_week=3))
    item = WantedItem(id="a", proposed_by="test", candidate=Candidate(stream=arm, targets=(Target(stream="w/adm~a", jurisdiction="A", reference_week=3, horizon=0),)))
    append_wanted(ws, "m", item)
    assert load_wanted(ws, "m") == [item]
    with pytest.raises(MissionError):
        append_wanted(ws, "m", item)
```

- [ ] **Step 2: Run to verify failure.**
- [ ] **Step 3: Implement `mission.py`.**
- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5: Commit** with subject `feat: missions and wanted lists`.

### Task 4: Program manifests, closure hashing, matched pairs

**Files:**
- Create: `src/scienceme/manifest.py`
- Modify: `tests/conftest.py` (add `write_program`)
- Test: `tests/test_manifest.py`

**Interfaces:**
- Consumes: `Frozen`, `Intervention`, `Timing`, `Target`, `TargetFilter`, `StreamSpec`.
- Produces:
  ```python
  class Tag(StrEnum): ASSERTS = "asserts"; DENIES = "denies"; UNSPECIFIED = "unspecified"
  class InterfaceVar(Frozen): variable: str; timing: Timing; alters: tuple[str, ...]
  class PairDecl(Frozen): claim: str; partner: str                    # partner closure hash
  class ProgramManifest(Frozen):
      name: str; author_lineage: str; entry: str = "program.py"; library: bool = False
      imports: dict[str, str] = {}                                     # alias -> closure hash
      lens: str | None = None                                          # must be a key of imports
      scope: TargetFilter = TargetFilter(); interface: tuple[InterfaceVar, ...] = ()
      tags: dict[str, Tag] = {}; pairs: tuple[PairDecl, ...] = (); supersedes: str | None = None
  class PairError(ValueError): ...
  def load_manifest(program_dir: Path) -> ProgramManifest              # program_dir / "program.json"
  def closure_hash(program_dir: Path) -> str                           # "sha256:" + 64 hex
  def supports(manifest: ProgramManifest, intervention: Intervention | None) -> bool
  def in_scope(manifest: ProgramManifest, target: Target, spec: StreamSpec) -> bool   # not library and scope matches
  def validate_pair(asserts: ProgramManifest, denies: ProgramManifest, claim: str) -> None
  ```
- Produces for tests: `write_program(ws, name, code, **fields) -> Path`, which writes `programs/<name>/program.json` (a `ProgramManifest(name=name, author_lineage="test", **fields)`), `program.py` containing `code`, and `README.md` containing `"test program"`.

`closure_hash` hashes the sorted list of `[posix relative path, sha256 hex of bytes]` for every regular file under the directory except `readback.json` and anything under a `__pycache__` component, serialized with `json.dumps(..., separators=(",", ":"))`. `program.json` carries the import hashes, so the hash commits to the whole closure. `supports` returns True for `None`, otherwise whether some interface variable has the same `variable` and `timing`. `validate_pair` requires: the claim is ASSERTS on one side and DENIES on the other; every other claim's tag is equal (a missing tag counts as UNSPECIFIED); scopes are equal; and lenses are either both absent or resolve to the same import hash.

- [ ] **Step 1: Write the failing tests**

```python
CONST = "from scienceme.pmf import Pmf\ndef predict(ctx, target):\n    return Pmf.point(7)\n"

def test_hash_ignores_readback_and_pycache(ws):
    d = write_program(ws, "p", CONST)
    h = closure_hash(d)
    (d / "readback.json").write_text("{}")
    (d / "__pycache__").mkdir(); (d / "__pycache__" / "x.pyc").write_bytes(b"x")
    assert closure_hash(d) == h and h.startswith("sha256:") and len(h) == 71

@pytest.mark.parametrize("edit", ["program.py", "README.md", "program.json"])
def test_hash_changes_with_any_frozen_file(ws, edit):
    d = write_program(ws, "p", CONST)
    h = closure_hash(d)
    (d / edit).write_text((d / edit).read_text() + "\n")
    assert closure_hash(d) != h

def test_supports_by_variable_and_timing():
    m = ProgramManifest(name="p", author_lineage="t", interface=(InterfaceVar(variable="schools_closed", timing=Timing.START_OF_WEEK, alters=("transmission",)),))
    assert supports(m, None)
    assert supports(m, Intervention(variable="schools_closed", value=1.0, start_week=3))
    assert not supports(m, Intervention(variable="vaccinate_fraction", value=0.8, start_week=3))

def test_library_programs_are_never_in_scope():
    t = Target(stream="w/adm", jurisdiction="A", reference_week=1, horizon=0)
    assert not in_scope(ProgramManifest(name="l", author_lineage="t", library=True), t, count_spec())

def test_validate_pair():
    a = ProgramManifest(name="a", author_lineage="t", imports={"lens": "sha256:" + "1" * 64}, lens="lens",
                        tags={"covariate-x": Tag.ASSERTS, "school": Tag.ASSERTS})
    d = a.model_copy(update={"name": "d", "tags": {"covariate-x": Tag.DENIES, "school": Tag.ASSERTS}})
    validate_pair(a, d, "covariate-x")
    for bad in (a.model_copy(update={"name": "d"}),
                d.model_copy(update={"tags": {"covariate-x": Tag.DENIES, "school": Tag.DENIES}}),
                d.model_copy(update={"imports": {"lens": "sha256:" + "2" * 64}}),
                d.model_copy(update={"scope": TargetFilter(jurisdictions=("A",))})):
        with pytest.raises(PairError):
            validate_pair(a, bad, "covariate-x")
```

- [ ] **Step 2: Run to verify failure.**
- [ ] **Step 3: Implement `manifest.py`.**
- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5: Commit** with subject `feat: program manifests and closure hashing`.

### Task 5: The freeze registry

**Files:**
- Create: `src/scienceme/registry.py`
- Test: `tests/test_registry.py`

**Interfaces:**
- Consumes: `Workspace`, `append_jsonl`, `read_jsonl`, `load_manifest`, `closure_hash`, `validate_pair`, `Tag`.
- Produces:
  ```python
  class Freeze(Frozen): kind: Literal["freeze"] = "freeze"; name: str; closure_hash: str; frozen_at: AwareDatetime
  class Withdrawal(Frozen): kind: Literal["withdraw"] = "withdraw"; closure_hash: str; at: AwareDatetime; reason: str
  class RegistryError(Exception): ...
  class Registry:
      def __init__(self, ws: Workspace) -> None
      def entries(self) -> list[Freeze | Withdrawal]
      def freezes(self) -> dict[str, Freeze]                 # by closure hash
      def by_name(self, name: str) -> Freeze | None
      def program_dir(self, closure_hash: str) -> Path
      def manifest(self, closure_hash: str) -> ProgramManifest
      def freeze(self, name: str, now: datetime) -> Freeze
      def withdraw(self, closure_hash: str, now: datetime, reason: str) -> Withdrawal
      def active(self, closure_hash: str, at: datetime) -> bool   # frozen_at < at, and no withdrawal with withdrawal.at < at
      def verify(self, closure_hash: str) -> None                 # RegistryError("modified-after-freeze") on mismatch
      def closure(self, closure_hash: str) -> list[str]          # transitive imports first, the program last
  ```

`freeze` validation, in order: `programs/<name>/program.json` loads and its `name` equals the directory name; if `name` is already frozen, it returns the existing Freeze when the hash matches and otherwise raises `RegistryError` naming the fix (freeze under a new name); the same hash frozen under another name raises; every import hash is frozen; `lens` is an import alias; every `PairDecl.partner` is frozen and `validate_pair` passes, with the two programs oriented by their tags on that claim. Then it appends the Freeze. The registry file only ever grows.

- [ ] **Step 1: Write the failing tests**

```python
def test_freeze_records_hash_and_time(ws):
    d = write_program(ws, "p", CONST)
    f = Registry(ws).freeze("p", at(0))
    assert (f.name, f.closure_hash, f.frozen_at) == ("p", closure_hash(d), at(0))

def test_refreeze_same_content_is_idempotent_and_changed_content_refused(ws):
    d = write_program(ws, "p", CONST)
    r = Registry(ws); f = r.freeze("p", at(0))
    assert r.freeze("p", at(1)) == f
    (d / "program.py").write_text(CONST + "# edit\n")
    with pytest.raises(RegistryError, match="new name"):
        r.freeze("p", at(2))
    with pytest.raises(RegistryError, match="modified-after-freeze"):
        r.verify(f.closure_hash)

def test_unknown_import_refused(ws):
    write_program(ws, "p", CONST, imports={"core": "sha256:" + "d" * 64})
    with pytest.raises(RegistryError):
        Registry(ws).freeze("p", at(0))

def test_active_window_is_strict(ws):
    write_program(ws, "p", CONST)
    r = Registry(ws); h = r.freeze("p", at(0)).closure_hash
    assert not r.active(h, at(0)) and r.active(h, at(1))
    r.withdraw(h, at(5), "test")
    assert r.active(h, at(5)) and not r.active(h, at(6))

def test_pair_partner_must_be_frozen_and_matched(ws):
    write_program(ws, "a", CONST, tags={"school": Tag.ASSERTS})
    r = Registry(ws); ha = r.freeze("a", at(0)).closure_hash
    write_program(ws, "d", CONST + "#d\n", tags={"school": Tag.DENIES}, pairs=(PairDecl(claim="school", partner=ha),))
    r.freeze("d", at(1))
    write_program(ws, "bad", CONST + "#b\n", tags={"school": Tag.ASSERTS}, pairs=(PairDecl(claim="school", partner=ha),))
    with pytest.raises(RegistryError):
        r.freeze("bad", at(2))

def test_registry_is_append_only(ws):
    write_program(ws, "p", CONST); write_program(ws, "q", CONST + "#q\n")
    r = Registry(ws); r.freeze("p", at(0))
    first = ws.registry.read_text()
    r.freeze("q", at(1))
    assert ws.registry.read_text().startswith(first)

def test_closure_lists_imports_first(ws):
    write_program(ws, "core", "def level():\n    return 3\n", library=True)
    r = Registry(ws); hc = r.freeze("core", at(0)).closure_hash
    write_program(ws, "p", CONST, imports={"core": hc})
    hp = r.freeze("p", at(1)).closure_hash
    assert r.closure(hp) == [hc, hp]
```

- [ ] **Step 2: Run to verify failure.**
- [ ] **Step 3: Implement `registry.py`.**
- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5: Commit** with subject `feat: append-only freeze registry`.

### Task 6: The as-of archive

**Files:**
- Create: `src/scienceme/archive.py`
- Modify: `tests/conftest.py` (add `publish`)
- Test: `tests/test_archive.py`

**Interfaces:**
- Consumes: `StreamSpec`, `Vintage`, `Row`, `Capture`, `Target`, `validate_vintage`, `write_new`, `read_model`.
- Produces:
  ```python
  class ArchiveError(Exception): ...
  class ArchiveView(Frozen):
      as_of: int; specs: dict[str, StreamSpec]; vintages: dict[str, tuple[Vintage, ...]]   # sorted by issue
      def spec(self, stream: str) -> StreamSpec
      def history(self, stream: str) -> tuple[Vintage, ...]
      def latest(self, stream: str) -> tuple[Row, ...]                        # () if no vintage
      def series(self, stream: str, jurisdiction: str) -> list[tuple[int, float]]   # latest vintage, by week
      def find(self, world: str, role: str) -> StreamSpec | None              # base stream (no intervention)
      def with_candidate(self, spec: StreamSpec) -> "ArchiveView"            # adds spec; history aliases spec.parent's
  class Archive:
      def __init__(self, ws: Workspace) -> None
      def create_stream(self, spec: StreamSpec) -> None    # archive/<id>/stream.json; same spec again is a no-op; a different spec raises
      def spec(self, stream: str) -> StreamSpec
      def specs(self) -> list[StreamSpec]
      def add(self, capture: Capture) -> None             # archive/<id>/<issue:05d>.json; validate_vintage; duplicate issue raises
      def issues(self, stream: str) -> list[int]
      def published_at(self, stream: str, issue: int) -> datetime | None
      def view(self, streams: Iterable[str], as_of: int, published_by: datetime) -> ArchiveView   # issue <= as_of and published_at <= published_by
      def realized(self, target: Target) -> int | None   # row for target_week in the vintage at target.resolution_issue
  ```
- Produces for tests: `publish(ws, spec, issue, values: Mapping[tuple[str, int], float], when: datetime) -> Capture`, which creates the stream if needed and adds the capture.

A duplicate issue raises `ArchiveError` with the message "issue already captured; source corrections are a tier 2 feature".

- [ ] **Step 1: Write the failing tests**

```python
def test_view_respects_issue_and_publication_time(ws):
    s = count_spec(jurisdictions=("A",))
    for i in (1, 2, 3):
        publish(ws, s, i, {("A", i - 1): 10.0 * i}, at(i))
    a = Archive(ws)
    assert [v.issue for v in a.view(["w/adm"], as_of=2, published_by=at(3)).history("w/adm")] == [1, 2]
    assert [v.issue for v in a.view(["w/adm"], as_of=3, published_by=at(2)).history("w/adm")] == [1, 2]

def test_series_uses_the_latest_vintage(ws):
    s = count_spec(jurisdictions=("A",))
    publish(ws, s, 2, {("A", 0): 5.0, ("A", 1): 3.0}, at(2))
    publish(ws, s, 3, {("A", 0): 6.0, ("A", 1): 8.0, ("A", 2): 1.0}, at(3))
    assert Archive(ws).view(["w/adm"], 3, at(9)).series("w/adm", "A") == [(0, 6.0), (1, 8.0), (2, 1.0)]

def test_realized_reads_the_resolution_vintage(ws):
    s = count_spec(jurisdictions=("A",))
    t = Target(stream="w/adm", jurisdiction="A", reference_week=2, horizon=1, resolution_lag=2)
    a = Archive(ws)
    publish(ws, s, 4, {("A", 3): 4.0}, at(4))
    assert a.realized(t) is None
    publish(ws, s, 5, {("A", 3): 9.0}, at(5))
    assert a.realized(t) == 9

def test_duplicate_issue_and_unknown_stream_refused(ws):
    s = count_spec(jurisdictions=("A",))
    c = publish(ws, s, 1, {("A", 0): 1.0}, at(1))
    with pytest.raises(ArchiveError):
        Archive(ws).add(c)
    with pytest.raises(ArchiveError):
        Archive(ws).add(Capture.make(Vintage(stream="w/none", issue=1, rows=()), at(1), "t"))

def test_create_stream_conflict(ws):
    a = Archive(ws); a.create_stream(count_spec()); a.create_stream(count_spec())
    with pytest.raises(ArchiveError):
        a.create_stream(count_spec(support_max=5))

def test_candidate_aliases_parent_history(ws):
    publish(ws, count_spec(jurisdictions=("A",)), 1, {("A", 0): 1.0}, at(1))
    arm = count_spec(id="w/adm~c", jurisdictions=("A",), parent="w/adm", intervention=Intervention(variable="schools_closed", value=1.0, start_week=4))
    v = Archive(ws).view(["w/adm"], 1, at(9)).with_candidate(arm)
    assert v.history("w/adm~c") == v.history("w/adm") and v.spec("w/adm~c") == arm
```

- [ ] **Step 2: Run to verify failure.**
- [ ] **Step 3: Implement `archive.py`.**
- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5: Commit** with subject `feat: as-of archive`.

### Task 7: The program SDK and the in-sandbox runner

**Files:**
- Create: `src/scienceme/sdk.py`, `src/scienceme/worker_entry.py`
- Test: `tests/test_worker_entry.py`

**Interfaces:**
- Consumes: `ArchiveView`, `Target`, `Pmf`, `ProgramManifest`, `closure_hash`, `load_manifest`.
- Produces:
  ```python
  # sdk.py (program authors write: from scienceme.sdk import Context, Pmf, Target, imports_of)
  @dataclass(frozen=True)
  class Context:
      view: ArchiveView; seed: int
      def rng(self) -> np.random.Generator             # np.random.default_rng(self.seed)
  def imports_of(module_name: str) -> Mapping[str, ModuleType]
  def register_imports(module_name: str, imports: Mapping[str, ModuleType]) -> None   # loader only
  # worker_entry.py
  class WorkOrder(Frozen): program: str; manifests: dict[str, ProgramManifest]; view: ArchiveView; targets: tuple[Target, ...]
  class Prediction(Frozen): kind: Literal["prediction"] = "prediction"; target: Target; pmf: Pmf
  class Failure(Frozen): kind: Literal["failure"] = "failure"; target: Target; error: str
  class WorkResult(Frozen): results: tuple[Annotated[Prediction | Failure, Field(discriminator="kind")], ...]
  def program_dirname(closure_hash: str) -> str          # the hex after "sha256:"
  def derive_seed(program: str, target: Target) -> int   # first 8 bytes of sha256(program + "|" + target JSON), big-endian
  def execute(order: WorkOrder, work: Path) -> WorkResult  # programs live in work/programs/<hex>/
  def main(argv: Sequence[str] | None = None) -> int      # argv = [work_dir, out_dir]; reads order.json, writes result.json
  ```

The program contract: `program.py` defines `predict(ctx: Context, target: Target) -> Pmf`. A program reaches its imports with `IMPORTS = imports_of(__name__)` at module level. The loader loads imports first (recursively, memoized by hash) under module names `scienceme_program_<first 16 hex>`, registers them with `register_imports`, then executes the module. If any module fails to load, every target becomes `Failure("load: ...")`. Per target, a raised exception, a non-`Pmf` return, or a pmf outside `[0, support_max]` of the target stream becomes a `Failure` for that target only.

- [ ] **Step 1: Write the failing tests.** The helper `sandbox(ws, tmp_path, *names) -> Path` copies each named program into `work/programs/<hex>/` and returns `work`. `order(ws, name, view, targets)` builds a WorkOrder from the manifests.

```python
PER_TARGET = ("from scienceme.sdk import Pmf\n"
              "def predict(ctx, target):\n"
              "    if target.jurisdiction == 'B':\n        raise RuntimeError('boom')\n"
              "    return Pmf.point(target.horizon)\n")

def test_execute_returns_one_result_per_target_and_isolates_failures(ws, tmp_path):
    ...  # targets A/h0, A/h1, B/h0
    kinds = [(r.kind, getattr(r, "pmf", None)) for r in execute(o, work).results]
    assert kinds == [("prediction", Pmf.point(0)), ("prediction", Pmf.point(1)), ("failure", None)]

def test_imports_resolve_through_the_sdk(ws, tmp_path):
    # library "core": def level(): return 3 ; program: IMPORTS = imports_of(__name__); return Pmf.point(IMPORTS["core"].level())
    assert execute(o, work).results[0].pmf == Pmf.point(3)

@pytest.mark.parametrize("body,needle", [
    ("return Pmf.point(5000)", "support"),          # support_max is 1000
    ("return 7", "Pmf"),
    ("return Pmf.point(-1)", "support"),
])
def test_invalid_returns_fail_only_their_target(ws, tmp_path, body, needle):
    # the program returns `body` for jurisdiction A and Pmf.point(1) for B
    a, b = execute(o, work).results
    assert a.kind == "failure" and needle in a.error and b.kind == "prediction"

def test_load_error_fails_every_target(ws, tmp_path):
    # program.py contains a syntax error
    assert all(r.kind == "failure" and r.error.startswith("load:") for r in execute(o, work).results)

def test_seed_is_deterministic_and_target_specific():
    t0, t1 = (Target(stream="w/adm", jurisdiction="A", reference_week=1, horizon=h) for h in (0, 1))
    assert derive_seed("sha256:ab", t0) == derive_seed("sha256:ab", t0) != derive_seed("sha256:ab", t1)

def test_main_round_trips_files(ws, tmp_path):
    (work / "order.json").write_text(o.model_dump_json())
    assert main([str(work), str(out)]) == 0
    assert WorkResult.model_validate_json((out / "result.json").read_text()).results[0].kind == "prediction"
```

- [ ] **Step 2: Run to verify failure.**
- [ ] **Step 3: Implement `sdk.py` and `worker_entry.py`.** Use `importlib.util.spec_from_file_location`, put the module in `sys.modules` before `exec_module`, and catch `Exception` (not `BaseException`) per target.
- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5: Commit** with subject `feat: program SDK and in-sandbox runner`.

### Task 8: The worker: sandboxes, isolation, container

**Files:**
- Create: `src/scienceme/worker.py`, `scorer/Dockerfile`, `scorer/requirements.lock`
- Test: `tests/test_worker.py`, `tests/test_worker_docker.py`; modify `tests/conftest.py` (the `--docker` option)

**Interfaces:**
- Consumes: `Registry.closure`, `Registry.manifest`, `Registry.program_dir`, `WorkOrder`, `WorkResult`, `Failure`, `execute`, `program_dirname`, `Isolation`.
- Produces:
  ```python
  def build_order(ws: Workspace, program: str, view: ArchiveView, targets: Sequence[Target]) -> WorkOrder
  def prepare_sandbox(ws: Workspace, order: WorkOrder, dest: Path) -> None   # copies the closure (minus readback.json, __pycache__) and writes order.json
  def run_order(ws: Workspace, order: WorkOrder, isolation: Isolation, timeout_s: int, image: str | None = None) -> WorkResult
  def worker_image() -> str        # $SCIENCEME_WORKER_IMAGE or "scienceme-worker:latest"
  def scorer_hash() -> str         # "sha256:" over the installed scienceme package's *.py files, sorted by relative path
  ```

Behavior by isolation: `NONE` prepares the sandbox in a temporary directory and calls `execute` in-process, with no timeout (simulation studies only). `PROCESS` runs `[sys.executable, "-I", "-m", "scienceme.worker_entry", work, out]` with `cwd=work`, `env={"PATH": os.defpath}`, and the timeout. `CONTAINER` runs `docker run --rm --name sm-<uuid4 hex> --network none --read-only --tmpfs /tmp:size=256m --memory 2g --cpus 1 --pids-limit 256 --user <uid>:<gid> -v <work>:/work:ro -v <out>:/out <image> python -I -m scienceme.worker_entry /work /out`, and on `TimeoutExpired` runs `docker kill <name>`. In every mode, a timeout yields `Failure(error="timeout")` for every target, and a missing or invalid `result.json` yields `Failure(error="no-result")`.

- [ ] **Step 1: Pin the base image.** Run `docker pull python:3.13-slim && docker inspect --format '{{index .RepoDigests 0}}' python:3.13-slim`, then `uv export --no-dev --no-emit-project --format requirements-txt > scorer/requirements.lock`. Write `scorer/Dockerfile` using that digest:

```dockerfile
FROM python:3.13-slim@sha256:<digest printed above>
ENV PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
COPY scorer/requirements.lock /tmp/requirements.lock
RUN pip install --require-hashes -r /tmp/requirements.lock
COPY pyproject.toml /src/pyproject.toml
COPY src /src/src
RUN pip install --no-deps /src && rm -rf /src
WORKDIR /work
```

- [ ] **Step 2: Write the failing tests.** `tests/test_worker.py`: `test_process_mode_end_to_end` (a frozen program through `run_order(..., Isolation.PROCESS, 30)` returns its pmfs); `test_process_timeout_fails_every_target` (the program sleeps 10 seconds, timeout 1, every result is `Failure(error="timeout")`); `test_sandbox_contains_only_the_closure` (after `prepare_sandbox`, the files under `dest/programs` are exactly the closure's, with no `readback.json` and no other program). `tests/test_worker_docker.py` has `pytestmark = pytest.mark.docker` and a session fixture that builds `scienceme-worker:test`:

```python
NET = ("import socket\nfrom scienceme.sdk import Pmf\n"
       "def predict(ctx, target):\n"
       "    try:\n        socket.create_connection(('1.1.1.1', 80), timeout=2)\n        return Pmf.point(0)\n"
       "    except OSError:\n        return Pmf.point(1)\n")
def test_container_has_no_network(...): assert result.pmf == Pmf.point(1)
def test_container_cannot_see_the_host_archive(...):  # program returns point(1) iff os.path.exists(str(ws.archive)) is False
def test_container_timeout_kills_the_container(...):  # afterwards `docker ps -q --filter name=sm-` prints nothing
```

`conftest.py` adds a `--docker` option and skips `docker`-marked tests unless it is given.

- [ ] **Step 3: Run to verify failure.** `uv run pytest tests/test_worker.py -q` fails.
- [ ] **Step 4: Implement `worker.py`.**
- [ ] **Step 5: Run to verify pass.** Run `uv run pytest tests/test_worker.py -q`, then `docker build -f scorer/Dockerfile -t scienceme-worker:latest . && uv run pytest tests/test_worker_docker.py --docker -q`. Expected: all pass.
- [ ] **Step 6: Commit** with subject `feat: isolated worker with container mode`.

### Task 9: The prospective record and running an origin

**Files:**
- Create: `src/scienceme/record.py`, `src/scienceme/predict.py`
- Test: `tests/test_predict.py`

**Interfaces:**
- Consumes: `Mission`, `mission_streams`, `MissionError`, `Archive`, `Registry`, `in_scope`, `supports`, `build_order`, `run_order`, `scorer_hash`, `program_dirname`.
- Produces:
  ```python
  class PredictionRecord(Frozen): kind: Literal["prediction"] = "prediction"; mission: str; program: str; target: Target
      pmf: Pmf; scorer: str; isolation: Isolation; recorded_at: AwareDatetime
  class UnscoredRecord(Frozen): kind: Literal["unscored"] = "unscored"; mission: str; program: str; target: Target
      reason: str; scorer: str; isolation: Isolation; recorded_at: AwareDatetime
  Record = Annotated[PredictionRecord | UnscoredRecord, Field(discriminator="kind")]
  class RecordStore:
      def __init__(self, ws: Workspace) -> None
      def path(self, mission: str, stream: str, reference_week: int, program: str) -> Path   # scores/<mission>/<stream>/<week:05d>/<hex>.json
      def has(self, mission: str, stream: str, reference_week: int, program: str) -> bool
      def write(self, mission: str, stream: str, reference_week: int, program: str, records: Sequence[Record]) -> None   # write-once
      def all(self, mission: str) -> list[Record]
  class SkipReason(StrEnum): ALREADY_RECORDED = "already-recorded"; MODIFIED_AFTER_FREEZE = "modified-after-freeze"
      OUT_OF_SCOPE = "out-of-scope"; UNSUPPORTED_INTERVENTION = "unsupported-intervention"
  class Skip(Frozen): stream: str; program: str; reason: SkipReason
  class Run(Frozen): stream: str; program: str; n_targets: int
  class OriginReport(Frozen): mission: str; reference_week: int; ran: tuple[Run, ...]; skipped: tuple[Skip, ...]
  def run_origin(ws: Workspace, mission: Mission, reference_week: int, isolation: Isolation, now: datetime) -> OriginReport
  def run_all(ws: Workspace, mission: Mission, isolation: Isolation, now: datetime) -> list[OriginReport]
  ```

`run_origin` raises `MissionError` if `isolation` is weaker than `mission.required_isolation`. For each COUNT stream in `mission_streams` with a vintage at `reference_week`: `cutoff = published_at(stream, reference_week)`. The candidates are frozen, non-library programs with `Registry.active(h, cutoff)`. For each candidate, the checks run in this order: already recorded is a skip; `verify` failing is a skip with `MODIFIED_AFTER_FREEZE`; an unsupported stream intervention is a skip; no in-scope targets is a skip. Otherwise it runs one order over `view(mission stream ids, as_of=reference_week, published_by=cutoff)` and writes a PredictionRecord or UnscoredRecord (with the failure's error as the reason) for every target. `run_all` covers every reference week from `first_issue` to `min(last_issue, latest published issue)`.

- [ ] **Step 1: Write the failing tests.** All use `Isolation.NONE` and `make_mission(required_isolation=Isolation.NONE)`.

```python
def test_frozen_after_publication_is_ineligible(ws):            # spec 4.2; review finding 1
    publish(ws, count_spec(jurisdictions=("A",)), 1, {("A", 0): 3.0}, at(1))
    write_program(ws, "late", CONST); Registry(ws).freeze("late", at(2))
    assert run_origin(ws, make_mission(), 1, Isolation.NONE, at(3)).ran == ()

def test_frozen_before_publication_is_recorded(ws):
    write_program(ws, "early", CONST); h = Registry(ws).freeze("early", at(0)).closure_hash
    publish(ws, count_spec(jurisdictions=("A",)), 1, {("A", 0): 3.0}, at(1))
    rep = run_origin(ws, make_mission(), 1, Isolation.NONE, at(3))
    assert rep.ran == (Run(stream="w/adm", program=h, n_targets=2),)
    assert {r.kind for r in RecordStore(ws).all("m")} == {"prediction"}

def test_rerun_is_idempotent(ws): ...           # second run: ran == (), skipped reason ALREADY_RECORDED
def test_failures_are_recorded_unscored(ws): ...  # PER_TARGET program; jurisdictions A,B; B targets are UnscoredRecord with reason "boom"
def test_unsupported_arm_gets_no_record(ws): ...  # arm stream with schools_closed; program without interface: Skip UNSUPPORTED_INTERVENTION; no file
def test_modified_program_is_skipped(ws): ...     # edit program.py after freeze: Skip MODIFIED_AFTER_FREEZE; no file
def test_weaker_isolation_refused(ws):
    with pytest.raises(MissionError):
        run_origin(ws, make_mission(required_isolation=Isolation.PROCESS), 1, Isolation.NONE, at(3))
def test_view_excludes_later_vintages(ws):
    # program returns Pmf.point(len(ctx.view.history(target.stream))); issues 1..3 published at 1..3
    # run_origin at reference week 2 after all are published: every pmf == Pmf.point(2)
```

- [ ] **Step 2: Run to verify failure.**
- [ ] **Step 3: Implement `record.py` and `predict.py`.**
- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5: Commit** with subject `feat: prospective record and origin runs`.

### Task 10: Scoring and the mixture

**Files:**
- Create: `src/scienceme/scoring.py`, `src/scienceme/weights.py`
- Test: `tests/test_scoring.py`, `tests/test_weights.py`

**Interfaces:**
- Consumes: `RecordStore.all`, `Archive.realized`, `Archive.spec`, `Target.resolution_issue`, `floored_log_prob`, `floored_cdf`.
- Produces:
  ```python
  # scoring.py
  class PointScore(Frozen): log_p: float; cdf_below: float; cdf_at: float      # all under the floored distribution
  def point_score(pmf: Pmf, y: int, eps: float, support_max: int) -> PointScore
  class ResolvedTarget(Frozen): target: Target; realized: int; scores: dict[str, PointScore]
  class Resolution(Frozen): resolved: tuple[ResolvedTarget, ...]; pending: int
      predicted: dict[str, int]; unscored: dict[str, int]
  def resolve(ws: Workspace, mission: Mission, as_of: int) -> Resolution
  # weights.py
  class MixtureStep(Frozen): target: Target; weights: dict[str, float]; score: PointScore
  class Advantages(Frozen): cumulative: dict[str, float]; current: dict[str, float]; steps: tuple[MixtureStep, ...]
  def normalized_weights(advantage: Mapping[str, float], awake: Iterable[str], tau: float) -> dict[str, float]
  def run_mixture(resolved: Sequence[ResolvedTarget], tau: float, half_life: float, as_of: int) -> Advantages
  def regime_tv(a: Mapping[str, float], b: Mapping[str, float]) -> float        # 0.5 * sum |a - b| over the union of keys
  ```

`resolve` counts a PredictionRecord as pending when `target.resolution_issue > as_of` or `realized` is None. It is never scored as zero (Review Focus 5). `resolved` is sorted by `(reference_week, stream, jurisdiction, horizon)`.

`run_mixture` is the sleeping-experts (specialists) algorithm of Freund, Schapire, Singer and Warmuth (1997), which is the spec's common-opportunity rule:

```
for each resolved target k in order:
    r = k.target.reference_week
    cur_m(r) = sum over resolved j with j.target.resolution_issue <= r of 2^(-(r - j.target.target_week)/half_life) * a[m, j]
    awake = programs with a score at k
    w = normalized_weights(cur(r), awake, tau)                 # w_m proportional to exp(cur_m / tau); missing advantage counts as 0
    mixture log_p = logsumexp(log w_m + log_p_m);  mixture cdfs = sum w_m * cdf_m
    a[m, k] = log_p_m - mixture log_p   for m in awake
cumulative_m = sum over k of a[m, k];  current_m = sum over k of 2^(-(as_of - k.target.target_week)/half_life) * a[m, k]
```

A program that predicts nothing has no advantage entry and never appears in a weight table, because tables are normalized over awake programs only.

- [ ] **Step 1: Write the failing tests.** The helper `rt(ref, ri, scores, j="A", h=0)` builds a ResolvedTarget whose target has `resolution_lag = ri - ref - h`, with the given `log_p` values and dummy cdfs.

```python
def test_log_score_beats_the_codex_counterexample():            # review finding 2
    truth = Pmf.from_probs(0, [0.9] + [0.0] * 9 + [0.1])
    nb = scipy.stats.nbinom(0.125, 1 / 9)                        # mean 1, variance 9
    inflated = Pmf.from_probs(0, list(nb.pmf(range(100)) / nb.cdf(99)))
    def expected(p): return sum(truth.prob(y) * floored_log_prob(p, y, 0.01, 99) for y in range(100))
    assert expected(truth) - expected(inflated) > 0.3

def test_honest_report_is_within_the_floor_compromise_of_optimal():
    q = Pmf.from_probs(0, [0.5, 0.3, 0.2]); eps, S = 0.01, 2
    best = Pmf.from_probs(0, [(q.prob(y) - eps / (S + 1)) / (1 - eps) for y in range(3)])
    def expected(p): return sum(q.prob(y) * floored_log_prob(p, y, eps, S) for y in range(3))
    assert expected(best) >= expected(q) >= expected(best) - 2 * eps

def test_first_target_has_equal_weights():
    adv = run_mixture([rt(1, 2, {"a": math.log(0.8), "b": math.log(0.2)})], tau=1.0, half_life=1e9, as_of=2)
    assert adv.steps[0].weights == {"a": 0.5, "b": 0.5}
    assert adv.cumulative == pytest.approx({"a": math.log(1.6), "b": math.log(0.4)})

def test_newcomer_cannot_outrank_an_incumbent_that_beat_the_mixture():   # review finding 3
    good, bad = math.log(0.8), math.log(0.2)
    ks = [rt(r, r + 1, {"a": good, "b": bad}) for r in range(1, 6)] + [rt(6, 7, {"a": good, "b": bad, "c": good})]
    adv = run_mixture(ks, tau=1.0, half_life=1e9, as_of=7)
    w = normalized_weights(adv.cumulative, {"a", "b", "c"}, 1.0)
    assert w["a"] > w["c"] > w["b"]

def test_weights_wait_for_resolution():
    ks = [rt(1, 3, {"a": math.log(0.9), "b": math.log(0.1)}, j="A"),
          rt(2, 4, {"a": math.log(0.5), "b": math.log(0.5)}, j="B"),
          rt(3, 5, {"a": math.log(0.5), "b": math.log(0.5)}, j="C")]
    steps = run_mixture(ks, tau=1.0, half_life=1e9, as_of=5).steps
    assert steps[1].weights == {"a": 0.5, "b": 0.5} and steps[2].weights["a"] > 0.5

def test_forgetting_halves_per_half_life():
    adv = run_mixture([rt(4, 5, {"a": math.log(0.8), "b": math.log(0.2)})], tau=1.0, half_life=4.0, as_of=8)
    assert adv.current["a"] == pytest.approx(0.5 * adv.cumulative["a"])

def test_sleeping_program_is_absent():
    adv = run_mixture([rt(1, 2, {"a": 0.0})], tau=1.0, half_life=1e9, as_of=2)
    assert "z" not in normalized_weights(adv.cumulative, {"a"}, 1.0)

def test_tau_tempers():
    assert normalized_weights({"a": 2.0, "b": 0.0}, {"a", "b"}, 2.0)["a"] == pytest.approx(math.e / (math.e + 1))

def test_regime_tv():
    assert regime_tv({"a": 1.0}, {"b": 1.0}) == 1.0 and regime_tv({"a": 0.5, "b": 0.5}, {"a": 0.5, "b": 0.5}) == 0.0

def test_resolve_keeps_unresolved_targets_pending(ws): ...
    # prediction recorded at week 1, horizon 1, lag 2: as_of 3 -> pending 1, resolved (); after issue 4 publishes, resolved 1
    # a resolution vintage missing the target's row -> still pending
```

- [ ] **Step 2: Run to verify failure.**
- [ ] **Step 3: Implement `scoring.py` and `weights.py`.** Use `scipy.special.logsumexp`. Recomputing `cur(r)` per distinct reference week is fine at tier 1 scale.
- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5: Commit** with subject `feat: floored log scores and sleeping-experts mixture`.

### Task 11: Calibration

**Files:**
- Create: `src/scienceme/calibration.py`
- Test: `tests/test_calibration.py`

**Interfaces:**
- Consumes: `PointScore`.
- Produces:
  ```python
  class Calibration(Frozen): pit: tuple[float, ...]; coverage_50: float; coverage_90: float; n: int
  def calibration(points: Sequence[PointScore], bins: int = 10) -> Calibration
  ```

This uses the nonrandomized PIT for discrete forecasts (Czado, Gneiting and Held 2009). Each observation contributes a uniform distribution on `[cdf_below, cdf_at]`. The histogram is the average mass per equal-width bin, and coverage at level `L` is the average mass inside `[(1 - L)/2, (1 + L)/2]`. With no points, it returns `n=0`, all-zero bins, and coverages `nan`.

- [ ] **Step 1: Write the failing tests**

```python
def test_calibrated_discrete_forecast_is_uniform():
    pts = [PointScore(log_p=math.log(0.5), cdf_below=0.0, cdf_at=0.5), PointScore(log_p=math.log(0.5), cdf_below=0.5, cdf_at=1.0)]
    assert calibration(pts).pit == pytest.approx((0.1,) * 10)

def test_coverage_of_a_full_interval():
    c = calibration([PointScore(log_p=0.0, cdf_below=0.0, cdf_at=1.0)])
    assert (c.coverage_50, c.coverage_90, c.n) == (pytest.approx(0.5), pytest.approx(0.9), 1)

def test_overconfidence_is_u_shaped():
    pts = [PointScore(log_p=-9.0, cdf_below=0.0, cdf_at=0.01), PointScore(log_p=-9.0, cdf_below=0.99, cdf_at=1.0)]
    c = calibration(pts)
    assert c.pit[0] == pytest.approx(0.5) and c.pit[-1] == pytest.approx(0.5) and c.coverage_90 == pytest.approx(0.0)
```

- [ ] **Step 2: Run to verify failure.** **Step 3: Implement.** **Step 4: Run to verify pass.** **Step 5: Commit** with subject `feat: discrete PIT calibration`.

### Task 12: Claims over matched pairs

**Files:**
- Create: `src/scienceme/claims.py`
- Test: `tests/test_claims.py`

**Interfaces:**
- Consumes: `Claim`, `Mission`, `ResolvedTarget`, `Resolution`, `Registry.freezes`, `Registry.manifest`, `Tag`, `StreamSpec`.
- Produces:
  ```python
  class Verdict(StrEnum): SUPPORTS = "supports"; CONTRADICTS = "contradicts"
      INSUFFICIENT = "insufficient evidence"; MIXED = "mixed"
  class PairStanding(Frozen): claim: str; asserts: str; denies: str; delta_nats: float; n_targets: int; verdict: Verdict
  class ClaimStanding(Frozen): claim: str; statement: str; pairs: tuple[PairStanding, ...]; verdict: Verdict
  def pair_standing(claim: Claim, asserts: str, denies: str, resolved: Sequence[ResolvedTarget],
                    specs: Mapping[str, StreamSpec], tau: float, threshold: float) -> PairStanding
  def summarize(pairs: Sequence[PairStanding]) -> Verdict
  def find_pairs(ws: Workspace, claim_id: str) -> list[tuple[str, str]]    # (asserts, denies), deduplicated, from frozen PairDecls
  def claim_standings(ws: Workspace, mission: Mission, resolution: Resolution, specs: Mapping[str, StreamSpec]) -> list[ClaimStanding]
  ```

`delta_nats` sums `log_p[asserts] - log_p[denies]` over resolved targets in the claim's scope where both predicted. The verdict is SUPPORTS if `delta / tau >= threshold`, CONTRADICTS if `<= -threshold`, and otherwise INSUFFICIENT. `summarize` returns the shared verdict when every decisive pair agrees, MIXED when decisive pairs disagree, and INSUFFICIENT when no pair is decisive or there are no pairs. `claim_standings` excludes any pair with a member whose coverage `predicted / (predicted + unscored)` is below `mission.coverage_min`.

- [ ] **Step 1: Write the failing tests**

```python
def test_delta_counts_shared_in_scope_targets_only():
    claim = Claim(id="school", statement="s", scope=TargetFilter(jurisdictions=("A",)))
    ks = [rt(1, 2, {"a": 0.0, "d": -3.1}), rt(2, 3, {"a": 0.0, "d": -3.1}),
          rt(3, 4, {"a": 0.0, "d": -50.0}, j="B"), rt(4, 5, {"a": 0.0})]
    p = pair_standing(claim, "a", "d", ks, {"w/adm": count_spec(jurisdictions=("A", "B"))}, tau=2.0, threshold=3.0)
    assert (p.delta_nats, p.n_targets, p.verdict) == (pytest.approx(6.2), 2, Verdict.SUPPORTS)

@pytest.mark.parametrize("delta,verdict", [(6.2, Verdict.SUPPORTS), (-6.2, Verdict.CONTRADICTS), (5.8, Verdict.INSUFFICIENT)])
def test_thresholds(delta, verdict): ...      # one shared target with log_p difference = delta, tau 2, threshold 3

def test_summarize():
    s, c, i = (PairStanding(claim="x", asserts="a", denies="d", delta_nats=0, n_targets=1, verdict=v) for v in (Verdict.SUPPORTS, Verdict.CONTRADICTS, Verdict.INSUFFICIENT))
    assert summarize([s, i]) == Verdict.SUPPORTS and summarize([s, c]) == Verdict.MIXED
    assert summarize([i]) == summarize([]) == Verdict.INSUFFICIENT

def test_low_coverage_pair_is_excluded(ws): ...   # member with 1 prediction and 9 unscored, coverage_min 0.8 -> claim INSUFFICIENT with no pairs
```

- [ ] **Step 2: Run to verify failure.** **Step 3: Implement.** **Step 4: Run to verify pass.** **Step 5: Commit** with subject `feat: matched-pair claim standings`.

### Task 13: Expected information gain and the wanted list

**Files:**
- Create: `src/scienceme/gain.py`
- Test: `tests/test_gain.py`

**Interfaces:**
- Consumes: `load_wanted`, `Archive.view`, `ArchiveView.with_candidate`, `Registry`, `supports`, `in_scope`, `build_order`, `run_order`, `normalized_weights`, `Advantages`, `ClaimStanding`.
- Produces:
  ```python
  def information_gain(pmfs: Sequence[Pmf], weights: Sequence[float]) -> float   # H(mixture) - sum w H(p), nats
  class RankedItem(Frozen): item: str; supporting: tuple[str, ...]; failed: tuple[str, ...]
      gain: float; targeted: dict[str, float]; priority: float; cost: float
  class Ranking(Frozen): mission: str; as_of: int; items: tuple[RankedItem, ...]
  def rank_wanted(ws: Workspace, mission: Mission, as_of: int, now: datetime, isolation: Isolation,
                  advantages: Advantages, claims: Sequence[ClaimStanding]) -> list[RankedItem]
  def choose(ranked: Sequence[RankedItem], reserve: float, rng: np.random.Generator) -> RankedItem
  def save_ranking(ws: Workspace, ranking: Ranking) -> None          # scores/<mission>/wanted/<as_of:05d>.json, write-once
  def load_latest_ranking(ws: Workspace, mission: str) -> Ranking | None
  ```

`rank_wanted` considers wanted items that are not yet fulfilled (no archive spec has `fulfills == item.id`) and whose intervention starts after `as_of`. The supporting set is active, non-library programs (at `now`) that support the candidate's intervention and have every candidate target in scope. Each runs once on `view(mission stream ids, as_of, now).with_candidate(candidate.stream)`. Any failure moves a program to `failed`. `gain` sums `information_gain` over the candidate targets, using `normalized_weights(advantages.current, ok, mission.tau)` on the raw pmfs. `targeted[c]` sums, over claim c's pairs with both members in `ok`, the per-target gain of the two-program mixture with `w_asserts = 1 / (1 + exp(-delta / tau))`. `priority = (gain + sum_c claim.weight * targeted[c]) / cost`. Items are sorted by priority descending, then id. `choose` takes a uniformly random item with probability `reserve`, otherwise the first.

- [ ] **Step 1: Write the failing tests**

```python
def test_disjoint_point_masses_carry_one_bit():            # review finding 11
    assert information_gain([Pmf.point(0), Pmf.point(10)], [0.5, 0.5]) == pytest.approx(math.log(2))

def test_identical_predictions_carry_nothing():
    assert information_gain([Pmf.point(3), Pmf.point(3)], [0.3, 0.7]) == pytest.approx(0.0)

def test_rank_wanted_uses_the_supporting_subset(ws):
    # programs: "lo" (point 0) and "hi" (point 10) declare schools_closed; "flat" declares no interface
    # one wanted item with 2 candidate targets; Advantages with empty dicts (equal weights)
    [item] = rank_wanted(ws, mission, as_of=2, now=at(9), isolation=Isolation.NONE, advantages=Advantages(cumulative={}, current={}, steps=()), claims=[])
    assert set(item.supporting) == {h_lo, h_hi} and item.gain == pytest.approx(2 * math.log(2))
    assert item.priority == pytest.approx(item.gain / item.cost)

def test_fulfilled_and_started_items_are_excluded(ws):
    # item "a" has an archive arm spec with fulfills="a"; item "b" has start_week 2 with as_of 2
    assert rank_wanted(ws, mission, as_of=2, now=at(9), isolation=Isolation.NONE, advantages=empty, claims=[]) == []

def test_choose_honors_the_reserve():
    items = [RankedItem(item=str(i), supporting=(), failed=(), gain=0.0, targeted={}, priority=float(-i), cost=1.0) for i in range(3)]
    assert choose(items, 0.0, np.random.default_rng(0)).item == "0"
    assert {choose(items, 1.0, np.random.default_rng(s)).item for s in range(20)} == {"0", "1", "2"}
```

- [ ] **Step 2: Run to verify failure.** **Step 3: Implement.** **Step 4: Run to verify pass.** **Step 5: Commit** with subject `feat: expected information gain and wanted ranking`.

### Task 14: Read-back

**Files:**
- Create: `src/scienceme/readback.py`
- Test: `tests/test_readback.py`

**Interfaces:**
- Consumes: `ProgramManifest`, `Tag`, `Claim`, `Registry`.
- Produces:
  ```python
  class CaptainVerdict(StrEnum): PENDING = "pending"; MATCHES = "matches"; MISMATCH = "mismatch"
  class Readback(Frozen): author_lineage: str; author_agent: str; assumptions: tuple[str, ...]
      inferred_tags: dict[str, Tag]; inferred_interface: tuple[str, ...]; summary: str
      captain_verdict: CaptainVerdict = CaptainVerdict.PENDING
  class ReadbackFlag(StrEnum): MISSING = "missing"; SAME_LINEAGE = "same-lineage"; TAG_MISMATCH = "tag-mismatch"
      INTERFACE_MISMATCH = "interface-mismatch"; CAPTAIN_MISMATCH = "captain-mismatch"; PENDING = "pending"
  def load_readback(program_dir: Path) -> Readback | None          # program_dir / "readback.json"
  def flags(manifest: ProgramManifest, readback: Readback | None) -> frozenset[ReadbackFlag]
  def packet(ws: Workspace, program: str, claims: Sequence[Claim]) -> str
  ```

`flags` returns `{MISSING}` when there is no read-back. Otherwise: SAME_LINEAGE when the lineages are equal; TAG_MISMATCH when, for any claim id in either map, the tags differ (a missing tag counts as UNSPECIFIED); INTERFACE_MISMATCH when `set(inferred_interface)` differs from the manifest's interface variable names; CAPTAIN_MISMATCH for verdict MISMATCH and PENDING for verdict PENDING. `packet` is text for the reading agent. It contains the file contents of the program and of every program in its closure, except `README.md`, `readback.json`, and the `tags`, `pairs` and `interface` fields of each `program.json`, followed by the mission's claims (id and statement) and the `Readback` JSON schema. The reader must not be shown what the author claimed.

- [ ] **Step 1: Write the failing tests**

```python
def test_packet_hides_the_author_claims(ws):
    d = write_program(ws, "p", CONST + "# CODE-MARKER\n", tags={"school": Tag.ASSERTS},
                      interface=(InterfaceVar(variable="schools_closed", timing=Timing.START_OF_WEEK, alters=("transmission",)),))
    (d / "README.md").write_text("SECRET-README")
    h = Registry(ws).freeze("p", at(0)).closure_hash
    text = packet(ws, h, [Claim(id="school", statement="School terms raise transmission", scope=TargetFilter())])
    assert "CODE-MARKER" in text and "School terms raise transmission" in text
    assert "SECRET-README" not in text and "schools_closed" not in text and '"asserts"' not in text

def test_flags():
    m = ProgramManifest(name="p", author_lineage="anthropic", tags={"school": Tag.ASSERTS},
                        interface=(InterfaceVar(variable="schools_closed", timing=Timing.START_OF_WEEK, alters=()),))
    rb = Readback(author_lineage="openai", author_agent="codex", assumptions=(), inferred_tags={"school": Tag.ASSERTS},
                  inferred_interface=("schools_closed",), summary="", captain_verdict=CaptainVerdict.MATCHES)
    assert flags(m, rb) == frozenset() and flags(m, None) == {ReadbackFlag.MISSING}
    assert flags(m, rb.model_copy(update={"inferred_tags": {}})) == {ReadbackFlag.TAG_MISMATCH}
    assert flags(m, rb.model_copy(update={"author_lineage": "anthropic"})) == {ReadbackFlag.SAME_LINEAGE}
    assert flags(m, rb.model_copy(update={"inferred_interface": ()})) == {ReadbackFlag.INTERFACE_MISMATCH}
```

- [ ] **Step 2: Run to verify failure.** **Step 3: Implement.** **Step 4: Run to verify pass.** **Step 5: Commit** with subject `feat: blind read-back packets and flags`.

### Task 15: Standings

**Files:**
- Create: `src/scienceme/standings.py`
- Test: `tests/test_standings.py`

**Interfaces:**
- Consumes: `resolve`, `run_mixture`, `normalized_weights`, `regime_tv`, `calibration`, `claim_standings`, `load_latest_ranking`, `flags`, `load_readback`, `Registry`, `Archive`, `mission_streams`, `load_mission`.
- Produces:
  ```python
  class ProgramStanding(Frozen): program: str; name: str; lineage: str; w_cumulative: float; w_current: float
      advantage_cumulative: float; advantage_current: float; n_predicted: int; coverage: float
      length_bytes: int; calibration: Calibration; flags: tuple[ReadbackFlag, ...]
  class StreamStanding(Frozen): stream: str; programs: tuple[ProgramStanding, ...]; regime_tv: float; regime_flag: bool
      mixture_calibration: Calibration; mixture_log_score: float; n_resolved: int; n_pending: int
  class Indicators(Frozen): interface_weight_share: float; readback_clean_share: float; lineage_entropy: float
  class Standings(Frozen): mission: str; epoch: int; as_of: int; scorer: str; streams: tuple[StreamStanding, ...]
      claims: tuple[ClaimStanding, ...]; ranking: Ranking | None; indicators: Indicators
  def compute(ws: Workspace, mission: Mission, as_of: int) -> Standings
  def render(all_standings: Sequence[Standings]) -> str
  def write_all(ws: Workspace) -> None          # standings.json (a JSON list of Standings) and STANDINGS.md at the root
  def check_all(ws: Workspace) -> bool          # True iff both files equal what write_all would produce
  ```

`as_of` for a mission is the largest published issue across its COUNT streams. Missions with nothing published are omitted. A stream's awake set is the programs with any record on that stream that are not withdrawn. Weights are `normalized_weights` of the cumulative and current advantages over that set, and `regime_flag` is `regime_tv > mission.regime_flag_tv`. `length_bytes` is the total size of the closure's files. Indicators are computed on the mission's first base COUNT stream, over the top set (the fewest programs, by `w_cumulative` descending, whose weights reach 0.9): the share of weight on programs with a non-empty interface, the share of top programs with no read-back flags, and the entropy in nats of the weight-by-lineage distribution. `render` is deterministic. It writes no wall-clock time, formats weights to 3 decimals and nats to 2, and sorts programs by `w_cumulative` descending, then name. Each mission gets a heading with as-of week and scorer hash, one table per stream (program, w cum, w cur, advantage, n, coverage, cov90, flags), a claims table, the top 10 wanted items, and the indicators.

- [ ] **Step 1: Write the failing tests.** Build a tiny workspace with `RecordStore.write` directly: two programs, three resolved targets, and one claim with no pairs.

```python
def test_compute_and_render_are_deterministic(ws): assert render([compute(ws, m, 5)]) == render([compute(ws, m, 5)])
def test_programs_sorted_by_cumulative_weight(ws): ...      # the better program's row precedes the worse one's in the stream table
def test_claim_without_pairs_reads_insufficient(ws): assert "insufficient evidence" in render([compute(ws, m, 5)])
def test_pending_targets_are_counted(ws): ...               # a prediction whose resolution vintage is absent -> n_pending == 1
def test_check_detects_staleness(ws):
    write_all(ws); assert check_all(ws)
    RecordStore(ws).write(...)                               # a new record
    assert not check_all(ws)
    write_all(ws); assert check_all(ws)
def test_json_round_trip(ws):
    write_all(ws)
    assert TypeAdapter(list[Standings]).validate_json((ws.root / "standings.json").read_text())[0].mission == "m"
```

- [ ] **Step 2: Run to verify failure.** **Step 3: Implement.** **Step 4: Run to verify pass.** **Step 5: Commit** with subject `feat: generated standings with staleness check`.

### Task 16: CLI

**Files:**
- Create: `src/scienceme/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `main(argv: Sequence[str] | None = None) -> int`, with argparse subcommands and a global `--root PATH` (default: the current directory):
  ```
  freeze NAME
  withdraw NAME --reason TEXT
  predict --mission M (--issue N | --all) [--isolation {container,process,none}]   # default container
  rank-wanted --mission M [--isolation ...]      # computes advantages and claims, ranks, saves the Ranking
  standings [--check]
  readback-packet NAME --mission M               # prints the packet
  check                                          # every manifest and mission loads; every frozen program verifies; wanted lists parse
  ```
  Exit codes: 0 for success, 1 for a domain error, a failed check, or stale standings, and 2 for a usage error. Domain errors (`RegistryError`, `ArchiveError`, `MissionError`, `PairError`, `ValidationError`) print one line to stderr. `cli.py` is the only module that calls `datetime.now(UTC)`.

- [ ] **Step 1: Write the failing tests:** `main(["--root", root, "freeze", "p"]) == 0` and the registry has `p`; `check` returns 1 after a frozen program is edited; `standings --check` returns 1 when stale and 0 after `standings`; `predict --mission m --all --isolation none` writes records; an unknown subcommand returns 2.
- [ ] **Step 2: Run to verify failure.** **Step 3: Implement.** **Step 4: Run to verify pass**, then run `uv run pytest --cov=scienceme --cov-report=term-missing -q` and confirm at least 90%. Add tests for any module below that.
- [ ] **Step 5: Commit** with subject `feat: scienceme CLI`.

### Task 17: The seed library

Do not read Part B of this plan or `../science.me-worlds`. These programs encode standard epidemiology (spec 4.13), not the generator.

**Files:**
- Create: `programs/lens-admissions/`, `programs/seir-core/`, `programs/hub-baseline/`, `programs/flex-loglinear/`, `programs/seir-x1-s1/`, `programs/seir-x0-s1/`, `programs/seir-x1-s0/`, `programs/seir-x0-s0/` (each with `program.json`, `program.py`, `README.md`)
- Test: `tests/test_seed_library.py`

**Interfaces:**
- Consumes: the SDK (`Context`, `Pmf`, `Target`, `imports_of`), `ArchiveView.find`, `ArchiveView.history`, `ArchiveView.series`.
- Produces (library programs; `library: true`, `author_lineage: "anthropic/claude"`):
  ```python
  # lens-admissions/program.py
  def completeness(view: ArchiveView, stream: str, jurisdiction: str, max_lag: int = 8) -> np.ndarray   # c[d], 1.0 for d >= max_lag
  def nowcast(view: ArchiveView, stream: str, jurisdiction: str) -> list[tuple[int, float]]           # latest series divided by completeness
  def observe_pmf(mean: float, dispersion: float, support_max: int) -> Pmf    # negative binomial, truncated at the 1 - 1e-12 quantile
  def fit_dispersion(observed: np.ndarray, expected: np.ndarray) -> float     # method of moments, floored at 1.0
  # seir-core/program.py
  @dataclass(frozen=True)
  class Mechanisms: covariate_x: float; school: float           # published effect sizes; 0.0 means the mechanism is absent
  @dataclass(frozen=True)
  class Params: beta0: float; amplitude: float; peak_week: float; s0: float; i0: float; scale: float
  def fit(series: Sequence[tuple[int, float]], x: Mapping[int, float], term: Mapping[int, float], mech: Mechanisms) -> Params
  def expected(params: Params, weeks: Sequence[int], x: Mapping[int, float], term: Mapping[int, float], mech: Mechanisms,
               interventions: Sequence[Intervention], jurisdiction: str) -> np.ndarray
  def predict_target(ctx: Context, target: Target, mech: Mechanisms, lens: ModuleType) -> Pmf   # what theory programs call
  ```

The model (standard SEIR with seasonal forcing, from general epidemiology): daily substeps, mean latent period 2 days, mean infectious period 3 days. Transmission is `beta0 * (1 + amplitude * cos(2*pi*(week - peak_week)/52)) * exp(-covariate_x * x[week]) * (1 - school * closed[week])`, where `closed = 1 - term[week]`, set to 1 inside an active `schools_closed` intervention. `vaccinate_fraction` moves that fraction of susceptibles to recovered at the start of its week. Expected admissions per week are `scale * new infections`. `fit` uses `scipy.optimize.least_squares` on `log1p` of the lens nowcast. `predict_target` reads covariates through `ctx.view.find(spec.world, "covariate-x")` and `find(spec.world, "school-term")`, takes interventions from `ctx.view.spec(target.stream).intervention`, multiplies expected admissions by `completeness(...)[target.resolution_lag - 1]` (the target is the value as reported at its resolution lag), and returns `lens.observe_pmf` with the fitted dispersion inflated by horizon (`k / (1 + 0.5 * horizon)`). A target's `reference_week` may exceed `view.as_of` when candidates are ranked; forecast `target_week` from the data available. Cache fits in a module-level dict keyed by `(stream, jurisdiction, view.as_of)`.

Non-library programs (all scope `TargetFilter(roles=("admissions",))`, `author_lineage: "anthropic/claude"`):

| Program | Mechanisms | Tags (covariate-x, covariate-x-flat, school) | Pairs | Interface |
|---|---|---|---|---|
| `hub-baseline` | none: NB around the last nowcast, dispersion from the last 8 log-differences | unspecified for all | none | none |
| `flex-loglinear` | none: AR(2) on log1p of the last 16 nowcast weeks, 4000 residual-bootstrap paths via `ctx.rng()`, `Pmf.from_samples` | unspecified for all | none | none |
| `seir-x1-s1` | covariate_x 0.2, school 0.2 | asserts, asserts, asserts | none | `schools_closed` (alters transmission), `vaccinate_fraction` (alters susceptibles), both `start_of_week` |
| `seir-x0-s1` | covariate_x 0.0, school 0.2 | denies, denies, asserts | covariate-x and covariate-x-flat with `seir-x1-s1` | same |
| `seir-x1-s0` | covariate_x 0.2, school 0.0 | asserts, asserts, denies | school with `seir-x1-s1` | same |
| `seir-x0-s0` | covariate_x 0.0, school 0.0 | denies, denies, denies | covariate-x and covariate-x-flat with `seir-x1-s0`; school with `seir-x0-s1` | same |

The four `seir-*` programs import `core = seir-core` and `lens = lens-admissions`, set `lens: "lens"`, and their `program.py` is a few lines calling `IMPORTS["core"].predict_target(ctx, target, Mechanisms(...), IMPORTS["lens"])`. Freeze in dependency order: lens, core, baselines, `seir-x1-s1`, `seir-x1-s0`, `seir-x0-s1`, `seir-x0-s0`.

- [ ] **Step 1: Write the failing tests.** The fixture copies `programs/` into a temp workspace, freezes everything at `at(0)`, and publishes 20 issues of an `admissions` stream for jurisdictions `("F", "A", "B", "C")`. The counts come from `seir-core.expected` with known parameters (loaded through `importlib` in the test), thinned by a fixed completeness curve. Alongside: a `covariate-x` stream (0.0 for F, a fixed sine for the others, released 4 weeks ahead) and a `school-term` stream (all ones except weeks 10 and 11).

```python
def test_every_seed_program_predicts_valid_pmfs(seed_ws): ...       # run_origin at week 16: ran covers all 6 theories, no UnscoredRecord
def test_school_assertion_changes_arm_predictions(seed_ws):
    # candidate arm schools_closed weeks 17-19 in A: mean of seir-x1-s1 on target week 18 < 0.95 * its baseline mean;
    # seir-x1-s0's arm mean equals its baseline mean within 1%
def test_flat_covariate_pair_is_indistinguishable(seed_ws):
    # for jurisdiction F, seir-x1-s1 and seir-x0-s1 pmfs have total variation distance < 1e-3 at every horizon
def test_seed_fit_tracks_its_own_model(seed_ws):
    # seir-x1-s1's 90% central interval at horizon 1 contains the fixture's next value for at least 3 of 4 jurisdictions
def test_one_origin_runs_in_under_30_seconds(seed_ws): ...
```

- [ ] **Step 2: Run to verify failure.** **Step 3: Write the eight programs and READMEs.** Each README is prose: what the program assumes and why, in two short paragraphs. **Step 4: Run to verify pass.**
- [ ] **Step 5: Freeze the library in the real workspace.** Run `uv run scienceme freeze <name>` for each, in the order above, then `uv run scienceme check`. Expected: exit 0.
- [ ] **Step 6: Commit** with subject `feat: seed library of standard epidemic programs`.

### Task 18: SKILL.md and CI

**Files:**
- Create: `SKILL.md`, `.github/workflows/check.yml`

- [ ] **Step 1: Write `SKILL.md`** (the agent entry point, modeled on Prove2Me's). Sections:
  1. What science.me is (one paragraph, from spec section 0).
  2. Setup: `uv sync`; `docker build -f scorer/Dockerfile -t scienceme-worker:latest .`.
  3. The loop (spec 5.1).
  4. Tier 1 tasks: propose a theory, propose a repair, request an observation (append a `WantedItem` line to `missions/<m>/wanted.jsonl`), write a read-back, shorten the library.
  5. The program contract: `program.json` fields, the `predict(ctx, target) -> Pmf` signature, `imports_of`, determinism through `ctx.rng()`, no network or files outside the closure, and targets whose `reference_week` exceeds `view.as_of` during ranking.
  6. Rules: never edit a frozen directory; every change is a new name with `supersedes`; freeze, then commit; theories declare a non-empty scope and at least one tag; never read `../science.me-worlds`.
  7. The read-back protocol: the reader's lineage differs from the author's; run `scienceme readback-packet NAME --mission M`; write `programs/NAME/readback.json`; the captain sets `captain_verdict`.
  8. Reading `standings.json`.
- [ ] **Step 2: Write `.github/workflows/check.yml`.** On push and pull request: checkout, `astral-sh/setup-uv`, `uv sync`, `uv run pytest -q`, `uv run scienceme check`, `uv run scienceme standings --check`.
- [ ] **Step 3: Verify locally.** Run `uv run pytest -q && uv run scienceme check && uv run scienceme standings && uv run scienceme standings --check`. Expected: all exit 0.
- [ ] **Step 4: Commit** with subject `docs: agent entry point and CI`.

---

## Part B: the private worlds

Part B (Tasks 19-23) lives in the private repository at `docs/tier1-plan-part-b.md` and is deliberately not public, because program authors must not know the generator.

---

## Part C: running tier 1

### Task 24: Pre-register, run, and record tier 1

- [ ] **Step 1: Pre-register.** In the worlds repository, write `evaluation/tier1.json`: the `EvalConfig` defaults (private Part B, Task 23), `programs` set to the eight seed programs, `public_root = "../science.me"`, `workers = 10`, and `master_seed` from `python -c "import secrets; print(secrets.randbits(63))"`. Commit it before any full run, with subject `eval: pre-register tier 1`.
- [ ] **Step 2: Run the harness.** `uv run worlds evaluate --config evaluation/tier1.json` runs in the background (a few hours with 10 workers). It writes `evaluation/results/<UTC date>-tier1.json`. Expected: an `EvalReport` with 80 replicate results (per generator and replicate: one gain run, two random runs and one "all" run, which fulfills every feasible wanted item at the first decision issue) and a pass/fail for every criterion. Concentration is judged on the "all" runs (spec 6.3: "even with unlimited arms"); the budget-limited gain runs' concentration is reported, not judged.
- [ ] **Step 3: Record in public.** Write `docs/tier1-results.md` in `science.me`: the criteria table (name, generator, judged, passed, the numbers) and the pre-registration commit hash. Include no world parameters. Commit.
- [ ] **Step 4: Start the prospective worlds.** `worlds create --generator seir --channel admissions --world seir-adm-1`, `--generator seir --channel ed-visits --world seir-ed-1`, `--generator abm --channel admissions --world abm-1`, then `worlds tick --to-issue 4` for each. In `science.me`: `scienceme predict --mission <m> --all`, then `scienceme standings`, then commit the archive, missions, scores and standings.
- [ ] **Step 5: Lens-swap experiment** (criterion 1, "a lens swap is absorbed by an imported program"). Pass conditions, fixed before running: every ED wrapper's `coverage_90` on the ED stream is within 0.10 of its admissions counterpart's `coverage_90` on the admissions stream, and the wrappers' ED cumulative-weight order equals their admissions counterparts' order for at least 5 of 6 program pairs compared. Procedure: at issue 10 of `seir-adm-1`, run `worlds add-channel --world seir-adm-1 --channel ed-visits`. An agent following `SKILL.md` writes a library `lens-ed` and four wrappers `seir-x?-s?-ed` that import the unchanged `seir-core` and swap only the lens import. Freeze, then tick and predict for 8 issues.
- [ ] **Step 6: Read-back experiment** (criterion 1, "a deliberately wrong program injected with a false README is caught"). A Claude-lineage agent writes `seir-liar`: README and tags assert the school effect and the interface declares `schools_closed`, but the code ignores both. Freeze it. A Codex-lineage agent receives only `scienceme readback-packet seir-liar --mission seir-adm-1` and writes `readback.json`. Pass condition: `flags` includes `tag-mismatch` or `interface-mismatch`. Then `scienceme withdraw seir-liar --reason "read-back experiment"`.
- [ ] **Step 7: Close out.** Add steps 5 and 6 to `docs/tier1-results.md`, with an overall verdict on criterion 1 following spec 7.3: if any judged criterion fails, the mechanism is wrong and tier 2 is not planned. Commit.

---

## Deferred to the tier 2 plan

NHSN raw HTTP captures with headers, transformation programs, and the per-source information-cutoff rule; held-out-jurisdiction predictive scores (spec 4.6); WIS and the FluSight quantile set; near-duplicate reporting and the log-score versus WIS rank-divergence indicator; votes as committed predictions on wanted items; scorer-arithmetic and source-data corrections with both results kept, and mission epochs; external anchoring (OpenTimestamps or a mirror); the tier 2 seed library (Serfling regression, humidity-driven transmission, the FluSight baseline); GitHub remotes and CI on push.
