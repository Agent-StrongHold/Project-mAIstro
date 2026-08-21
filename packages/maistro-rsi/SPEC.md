# maistro-rsi — Spec & Acceptance Criteria

Recursive self-improvement: an agent that branches, patches, tests, and
benchmarks its own codebase inside an isolated sandbox, with results scored
through the shared `maistro-evolve` Elo tournament.

Each section below is a human-readable behavior spec. Acceptance criteria are
numbered `<module>-<n>` and every test in `tests/` must reference the AC(s) it
verifies in its docstring — no test exists without a traceable AC, and no AC
ships without a test.

---

## 1. MicroVM sandbox (`protocols.py`, `sandbox/microvm.py`)

**Spec:** RSI code never talks to a concrete sandbox technology directly — it
depends on the `MicroVmSandbox` protocol. A Docker-backed implementation
(`DockerMicroVmSandbox`) makes the package runnable today; a real microVM
backend (Firecracker/E2B/gVisor, or **Docker Sandboxes / `sbx`**) can replace it
later by satisfying the same protocol, with zero changes to call sites.

When the RSI cycle already runs *inside* an isolated microVM — i.e. maistro-rsi
is launched as an `sbx` agent (see `sbx/maistro-rsi/`) — a nested container would
be redundant Docker-in-Docker. `LocalSandbox` satisfies the same protocol by
running commands directly on the (already-isolated) local FS, and
`create_rsi_sandbox` picks the backend from `$MAISTRO_RSI_SANDBOX`.

| AC | Criterion |
|----|-----------|
| sandbox-1 | `DockerMicroVmSandbox` satisfies the `MicroVmSandbox` protocol (structural check via `isinstance`). |
| sandbox-2 | `exec(command)` runs the command inside the underlying container and returns `(exit_code, output)`. |
| sandbox-3 | `write_file` followed by `read_file` round-trips file content through the sandbox workspace. |
| sandbox-4 | `snapshot(label)` returns a unique id each call, even for the same label (no collisions across concurrent attempts). |
| sandbox-5 | `restore(snapshot_id)` raises `KeyError` for an id that was never captured, and `NotImplementedError` for a real one — the Docker backend cannot resume paused state, and must say so rather than silently no-op. |
| sandbox-6 | `destroy()` tears down the underlying container exactly once. |
| sandbox-7 | Used as `async with`, the sandbox is destroyed on exit (success or exception) — no leaked containers. |
| sandbox-8 | `LocalSandbox` structurally satisfies the `MicroVmSandbox` protocol. |
| sandbox-9 | `LocalSandbox.exec(command)` runs the command against the workspace and returns `(exit_code, output)`; a non-zero exit is reported verbatim, not swallowed. |
| sandbox-10 | `LocalSandbox` `write_file`/`read_file` round-trip content through the workspace, and relative paths resolve under it (no escape to arbitrary host paths for relative inputs). |
| sandbox-11 | `LocalSandbox.snapshot(label)` returns a unique id each call; `restore` raises `KeyError` for an unknown id and `NotImplementedError` for a captured one (same honest posture as the Docker backend). |
| sandbox-12 | `LocalSandbox.destroy()` is a no-op that never raises — `sbx` owns the microVM lifecycle — and `async with` still exits cleanly. |
| sandbox-13 | `create_rsi_sandbox` returns a `LocalSandbox` when the backend is `local` (arg or `$MAISTRO_RSI_SANDBOX`) and a `DockerMicroVmSandbox` otherwise; an explicit `backend` arg overrides the env var. **Precondition for `local`:** container evidence must be detected (`isolation_evidence()` — `/.dockerenv`, `/run/.containerenv`, or a runtime token in `/proc/1/cgroup`) or the creating layer must attest containment via `MAISTRO_RSI_SANDBOX_ATTEST_ISOLATED` (set by `sbx/maistro-rsi/spec.yaml`); otherwise `RuntimeError`. Generic VM markers (DMI) are deliberately NOT accepted — a persistent development VM is not disposable. |
| sandbox-14 | `LocalSandbox` rejects any file path that escapes the workspace — `..` traversal or an absolute path outside it — with `ValueError`, mirroring the Docker backend's `_safe_path` posture; absolute paths *inside* the workspace still resolve. |
| sandbox-15 | `LocalSandbox.exec` runs each command in its own process group (via `bash -c`, matching the Docker backend's shell contract) and a timeout kills the *whole group* — children spawned by the command do not outlive the call. |

---

## 2. Quarantine gate (`quarantine.py`)

**Spec:** Recursive self-improvement that can't touch its own scaffolding
isn't recursive — so `maistro-rsi` does **not** ban agents from proposing
changes to harness, sandbox, or security code. Instead, *every* self-diff,
regardless of what it touches, is scanned by Warden (the same content scanner
used at every other trust boundary) before it's allowed out of the sandbox as
a PR. Diffs that touch declared "sensitive surface" — the agent's own cage:
sandbox control, security wiring, the self-branch/runner pipeline itself — are
not blocked outright, but are escalated to require an *additional* adversarial
(red-team-style) review pass on top of Warden + the full test suite. The
property we want is "nothing self-modified reaches the outside world unscanned
and unreviewed," not "some files are permanently off-limits."

| AC | Criterion |
|----|-----------|
| quarantine-1 | `quarantine_scan` returns `cleared=False` whenever the Warden verdict for the diff is not clean — a flagged diff never clears quarantine, regardless of which files it touches. |
| quarantine-2 | A diff that touches none of `SENSITIVE_PATH_PATTERNS` and passes the Warden scan clears with `requires_adversarial_review=False`. |
| quarantine-3 | A diff that touches *any* sensitive-surface path — even just one file alongside unrelated changes — sets `requires_adversarial_review=True`, regardless of the Warden verdict. |
| quarantine-4 | `cleared` is `True` only when the Warden scan is clean **and** (the diff doesn't require adversarial review **or** an adversarial review verdict was supplied and passed). A pending/missing adversarial review on a sensitive-surface diff must never clear. |
| quarantine-5 | `flags` on the returned verdict surfaces the Warden flags verbatim — quarantine never swallows or summarizes *why* something was held, since that trail is what a human reviewer acts on. |

---

## 3. Self-branch workflow (`selfbranch.py`)

**Spec:** Given a target repo and a test command, the workflow clones the repo
into the sandboxed workspace, creates a uniquely-named branch, hands control to
an agent-supplied `apply_patch` callback, commits, runs the test command
*inside the sandbox*, runs the diff through the injected quarantine check, and
— only if tests pass **and** quarantine clears — opens a draft PR. A
self-modifying agent does not get to propose changes to its own codebase that
fail its own test suite, nor to ship anything (including changes to its own
harness) that hasn't been scanned and, where warranted, adversarially reviewed.

| AC | Criterion |
|----|-----------|
| selfbranch-1 | `new_attempt(repo_url, test_command)` produces a branch name that is unique per call (no two attempts collide). |
| selfbranch-2 | A failed clone short-circuits the workflow: no branch/patch/test/PR/quarantine steps run, and the result carries a non-`None` `error`. |
| selfbranch-3 | On a successful clone, the workflow calls `git_branch`, then `apply_patch`, then `git_commit`, in that order, before running tests. |
| selfbranch-4 | `tests_passed` is `True` iff the sandboxed test command exits `0` *and* no error was recorded — a clone failure must never read as "tests passed". |
| selfbranch-5 | A PR is opened (`github_create_pr` invoked, `pr_url` populated) only when `open_pr=True` **and** the test command exits `0` **and** (`quarantine_check` is absent **or** returns a cleared verdict). A failing test suite or an uncleared quarantine verdict must never produce a PR, regardless of `open_pr`. |
| selfbranch-6 | The returned `diff` reflects `git diff` output captured after the patch is applied and committed. |
| selfbranch-7 | `paths_touched_by_diff` extracts every `a/...`/`b/...` path named in a unified diff's `diff --git` headers, de-duplicated and in first-seen order. |
| selfbranch-8 | The `quarantine` field on the result carries the verdict `quarantine_check` returned, so callers can inspect *why* a change was held without re-deriving it. |

---

## 4. Quota-burn scheduling (`quota_burn.py`)

**Spec:** The scheduler discovers models from the connected LiteLLM instance
and routes each RSI cycle toward whichever model currently has the most idle
free-tier headroom, so unused allowances get exercised before they expire —
without ever recommending a model whose tracked usage already exceeds its
configured free-tier budget.

| AC | Criterion |
|----|-----------|
| quota-1 | `rank_models_by_headroom` orders models by **descending** remaining headroom (`free_tokens * (1 - used_pct)`), most idle first. |
| quota-2 | A model with recorded usage above its configured `free_tokens` ranks at the bottom (zero/negative headroom clamps to zero — never goes negative). |
| quota-3 | `QuotaBurnScheduler.next_model([])` returns `None` — an empty model list is not an error, it's "nothing to schedule". |
| quota-4 | `QuotaBurnScheduler.next_model(models)` returns the model `rank_models_by_headroom` ranks first, given the same tracker state. |
| quota-5 | `record_attempt` attributes usage to the model's **provider** (the `provider/model-name` prefix), so subsequent ranking reflects the recorded consumption. |

---

## 5. SWE-Bench Pro adapter (`benchmarks/swebench_pro.py`)

**Spec:** Scores a candidate's ability to produce *coordinated, multi-file*
fixes — the defining trait that separates SWE-Bench Pro from the original
SWE-bench (avg. ~107 lines across ~4 files per task). A patch that only
touches one file on an inherently cross-cutting bug is, by construction,
incomplete and must score lower than one that addresses every affected file.

| AC | Criterion |
|----|-----------|
| swebench_pro-1 | `run_swebench_pro` returns an `EvalResult` with `benchmark="swebench_pro"` and `samples_evaluated == len(SWEBENCH_PRO_SAMPLES)`. |
| swebench_pro-2 | A response that references every file listed in a sample's `files` scores strictly higher (via `_score_multi_file_fix`) than a response that references only one of them, all else equal. |
| swebench_pro-3 | A response containing none of a sample's `expected_keywords` and no code block scores at or near `0.0`. |
| swebench_pro-4 | `load_remote_samples()` raises `NotImplementedError` — it is a documented extension point, not a silent stub that returns empty data. |

---

## 6. RSI cycle runner (`runner.py`)

**Spec:** One cycle wires the pieces end-to-end: pick a model by quota
headroom, run a self-branch attempt in a sandbox, evaluate *both* the baseline
and candidate genomes against the configured benchmark suite, and record one
Elo battle per shared benchmark. `improved` is the single boolean that decides
whether a self-modification is allowed to stand: it requires both a passing
test suite *and* a benchmark majority — passing tests alone is not enough to
call a change an improvement, and winning benchmarks with a broken build is
not improvement either.

| AC | Criterion |
|----|-----------|
| runner-1 | `RsiCycle.run` evaluates both `baseline` and `candidate` genomes on exactly the benchmarks named in `RsiCycleConfig.benchmarks`. |
| runner-2 | One `GenomeBattle` is recorded per benchmark present in **both** result sets; benchmarks present in only one are skipped, not battled against a missing score. |
| runner-3 | `benchmarks_won` counts only battles the candidate (`genome_b`) outright won — draws and baseline wins do not count. |
| runner-4 | `improved` is `True` only when `branch_result.tests_passed` is `True` **and** `benchmarks_won` is a strict majority of `battles`; either condition failing makes it `False`. |
| runner-5 | The sandbox is destroyed even when `apply_patch` or evaluation raises — no leaked containers on a failed cycle. |

---

## 7. Hypothesis-Tree Refinement (`htr.py`)

**Spec:** Run on its own, each RSI cycle is a *local* attempt that learns
nothing from the cycles before it. Following Arbor (arXiv:2606.11926), `htr.py`
keeps a persistent tree of hypotheses so the loop becomes *cumulative*: each
node is a proposed direction for a self-change; once an executor runs it, the
node carries the returned evidence, the artifacts it produced, and a distilled,
reusable insight. The tree's scoring is evidence-grounded (an unexecuted node
has no score — never a silent zero; a change that breaks its own tests is
worthless regardless of benchmarks), and its refinement policy prunes dead-end
branches while propagating the lessons learned along a lineage into whatever is
tried next. The module is pure — no sandbox, git, or network — so the policy is
reasoned about independently of execution.

| AC | Criterion |
|----|-----------|
| htr-1 | `HypothesisEvidence` rejects impossible tallies — `benchmarks_won` outside `[0, battles]` (or a negative `battles`) raises `ValueError` — and `net_gain` is `+1`/`-1`/`0` for a sweep/clean-loss/even-split, `0.0` when there are no battles. |
| htr-2 | A node's `score` is `None` until evidence is recorded (unknown is never a silent `0.0`); once recorded it is `0.0` whenever the tests failed regardless of benchmark wins, and otherwise the net benchmark gain mapped onto `[0, 1]` (clean sweep → `1.0`, even split → `0.5`). |
| htr-3 | `expand(parent_id, hypothesis)` adds an OPEN child whose `depth` is the parent's `depth + 1`, appends it to the parent's `children`, raises `KeyError` for an unknown parent, and raises `ValueError` for an ABANDONED parent (a pruned branch is never grown). |
| htr-4 | `record` marks a node ABANDONED when its tests failed **or** its net benchmark gain is `<= 0`, and EXPLORED otherwise; it also stores the supplied `diff`/`pr_url`/`run_id` artifacts and distills an insight when none is supplied. |
| htr-5 | `best_node` returns the highest-scoring executed node — `None` while none have run — with deterministic tie-breaking (shallower depth, then earliest proposed). |
| htr-6 | `pending` returns only OPEN nodes ordered so a node descending from a higher-scoring parent comes first (ties broken by recency), **excluding** any node whose lineage contains an abandoned ancestor (pruned branches never re-grow); `expandable_seeds` returns only EXPLORED nodes, most-promising first; `select_seed` returns the top seed or the root (if unexecuted), and raises `ValueError` if the root is abandoned and no explored branches exist. |
| htr-7 | `distilled_insights(node_id)` returns the non-empty insights along that node's root-to-node lineage, oldest first and de-duplicated; called with no argument it follows the best node's lineage. This is the cumulative-not-local property: a node inherits every lesson on the path to it. |
| htr-8 | `HypothesisTree.to_dict()` / `from_dict()` round-trip losslessly: statuses, scores, evidence, insights, artifacts, children, and priority order are preserved, and `pending()`, `best_node()`, `distilled_insights()`, and `summary()` return identical results on the restored tree. |
| htr-9 | `from_dict` restores the private proposal counter to `max(order) + 1`, so `expand()` after a resume produces globally unique, correctly prioritized orderings — recency tie-breaks behave as if the process had never restarted. Restoring an empty tree or a `root_id` not among the nodes raises `ValueError`. |

---

## 8. HTR coordinator (`coordinator.py`)

**Spec:** The long-lived coordinator drives short-lived executors against the
tree. On each step it acts on an already-queued hypothesis if one exists,
otherwise grows a fresh hypothesis off the most promising explored branch; it
hands the executor the node *and the insights distilled from that node's
lineage*; and it records the returned report back into the tree. A real
`RsiCycleResult` bridges into the coordinator's `ExecutionReport` without the
coordinator importing the sandbox/git chain.

| AC | Criterion |
|----|-----------|
| coordinator-1 | `run(n, propose)` executes exactly `n` steps, recording one node per step, and `propose` is invoked only on steps where no OPEN hypothesis is already queued. |
| coordinator-2 | When a hypothesis is already queued (OPEN), the coordinator acts on it rather than proposing a new one; the node handed to the executor is the highest-priority pending node. |
| coordinator-3 | The `HtrContext` passed to the executor carries `distilled_insights` for the acted-on node's lineage, so a child attempt sees its ancestors' recorded lessons. |
| coordinator-4 | Each executor `ExecutionReport` is recorded against its node (evidence, artifacts, insight), so after the run the tree's statuses/scores reflect every step and `CoordinatorResult.best` is the tree's best node. |
| coordinator-5 | `report_from_cycle_result` maps an `RsiCycleResult` into an `ExecutionReport` — `tests_passed`/`benchmarks_won`/`battles`/`improved` evidence plus `diff`/`pr_url`/`run_id` artifacts — and importing `coordinator` does not import the runner/sandbox chain. |

---

## 9. Agent-backed apply_patch drivers (`apply_agents.py`)

**Spec:** The RSI cycle's `apply_patch` seam (`ApplyPatchFn`) is agent-agnostic
— any non-interactive CLI coding agent can fill it by editing the checkout
in-sandbox. `command_apply_patch` is one generic driver, templated so it covers
opencode (the default) or any future CLI agent, without hardcoding a specific
tool. It is one option among several `apply_patch` drivers — `local_loop.py`'s
`make_builders_apply_patch` (the native builders agent) is another, already
real and already compatible with the same 3-arg protocol.

| AC | Criterion |
|----|-----------|
| applyagents-1 | `command_apply_patch(prompt)` renders `template` with the prompt shlex-quoted, so shell metacharacters in the hypothesis/prompt text cannot break out of their argument position. |
| applyagents-2 | The rendered command is executed via `sandbox.exec`, not a bare shell call outside the sandbox — the agent's edits happen inside the isolation boundary. |
| applyagents-3 | A non-zero exit from the agent command raises `ApplyPatchError` (not a silently-empty patch), carrying the command's exit code and output tail. |
| applyagents-4 | When `template` contains a `{model}` placeholder, the per-cycle `model` argument (threaded through `ApplyPatchFn`'s third parameter) is substituted, shlex-quoted; when `model` is `None` it substitutes an empty string rather than the literal `"None"`. |

---

## 10. Autonomous experimentation run (`autorun.py`)

**Spec:** This is the *exploratory auto-experimentation* variant of RSI — a
distinct mode from the directed cleanup loop (`local_loop.py`/`cli.py`): where
that loop ratchets one baseline forward, `autorun` grows a `HypothesisTree`
of *candidate experiments*, each measured against differential workspace
probes, with the Elo tournament as the judge of what survives. `apply_patch`
is pluggable — opencode by default, but any factory (including
`make_builders_apply_patch`) can drive the experiment instead. Every cycle's
outcome, win or lose, is appended to an audit log so the run is inspectable
after the fact, and the quarantine gate (Warden, plus adversarial review when
configured) still governs whether a winning experiment may leave the sandbox
as a PR.

| AC | Criterion |
|----|-----------|
| autorun-1 | `build_executor` wires each hypothesis's prompt into an `ApplyPatchFn` via `config.apply_patch_factory` when supplied, else the opencode-template default — so the driver is swappable without changing the coordinator/executor plumbing. |
| autorun-2 | `build_executor`'s `RsiCycle` is always constructed with a `quarantine_check` backed by `quarantine_scan` + the supplied (or default) `Warden` — an autonomous run is never unquarantined. |
| autorun-3 | `run_autonomous` pre-expands every `AutorunConfig.seed_hypotheses` onto the tree before the first coordinator step, so caller-supplied experiment ideas run before the proposer starts inventing its own. |
| autorun-4 | `run_autonomous` stops issuing new cycles once `max_wall_clock_s` has elapsed (checked between cycles only — a running cycle always finishes), and `CoordinatorResult.steps` reflects exactly the cycles that ran. |
| autorun-5 | `make_llm_proposer` falls back to `template_proposer` (never raises) when the LiteLLM call fails or returns empty content — a mis-configured/unreachable gateway degrades the loop to deterministic refinement instead of crashing the run. |
| autorun-6 | `AuditLog.record` appends one JSON object per cycle (hypothesis, run id, tests_passed, benchmarks_won, quarantine verdict + flags, PR url) to its file, and never overwrites a prior record — the trail is append-only. |
| autorun-7 | The tree snapshot is written after **every** cycle with an atomic write (temp file + `os.replace`) — a crash or kill mid-run loses at most the in-flight cycle, and a crash mid-*write* can never leave a truncated snapshot. |
| autorun-8 | On start, an existing snapshot is loaded and continued (seeds are expanded only on a NEW tree — never duplicated on resume); a snapshot whose root hypothesis differs from the configured one is refused with a clear `ValueError`; `fresh=True` (CLI `--fresh`) explicitly starts a new tree. |
| autorun-9 | A run stopped by the wall-clock budget resumes where it left off: the next `run_autonomous` over the same tree path continues the same tree rather than re-exploring from the root — the budget guard no longer discards work. |
| autorun-10 | Every executed cycle appends its node's distilled insight to the `LearningsLedger` (repo url, run id, hypothesis, insight, improved, tests_passed, score) — append-only, one JSON line per cycle. |
| autorun-11 | **Retained learnings:** prior insights recalled from the ledger are injected into the proposer and experiment-prompt context on every start — including a `fresh` run with a brand-new tree — with insights from experiments that `improved` preferred first, recency breaking ties, duplicates dropped, and repo-scoped filtering. Learnings survive tree disposal. |
| autorun-12 | The ledger is corruption-tolerant: corrupt or partial lines are skipped with a warning (never raise) and a missing file reads as an empty ledger — a damaged memory degrades recall, never the run. |
