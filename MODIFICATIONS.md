# MODIFICATIONS.md

Chronological log of every change to code, scenarios, prompts, configs, and
dependencies — by the user or by Claude. Newest entries at the top.

Each entry uses this template:

```
## YYYY-MM-DD HH:MM — <short title>
**Author:** user | Claude
**Files:**
  - path/to/file (created | modified | deleted)
**Change:** what was done, in 1–3 sentences.
**Why:** the motivating hypothesis or bug.
**Result:** measured outcome (smoke pass rate, latency, errors), or "not yet measured".
**Related:** IDEAS.md anchor or prior MODIFICATIONS.md entry, if any.
```

---

## 2026-06-01 10:00 — Self-hosted vLLM (own Blackwell box) for Gemma-4-31B; full 125-task run launched
**Author:** Claude (at user's request); user provisioned the server
**Files:**
  - `src/track_1_agent_under_test/car_bench_agent.py` + `server.py` (modified —
    added `--openrouter-provider` earlier; the `--api-base`/`--api-key-env`/
    `--sanitize-tool-schemas` flags from 2026-05-31 reused here)
  - `scenarios/track_1_agent_under_test/box_smoke_gemma4.toml` (created)
  - `scenarios/track_1_agent_under_test/box_full_test_gemma4.toml` (created)
**Context:** OpenRouter hit sustained rate-limits (~19% errored trials) → abandoned.
User provisioned a GPU box (root@46.225.241.244, Ubuntu 24.04, **RTX PRO 6000
Blackwell 96 GB**, shared with other live services — web on 80/443/800x, ollama,
another vLLM). We self-host gemma-4-31b there in an isolated folder.
**Setup (all in `/root/carbench-gemma4/`, isolated venv; documented for repro):**
  1. venv + `pip install vllm` (0.22.0, torch 2.11, CUDA-13 wheels — Blackwell ok)
  2. HF token (gated gemma-4) written to `.hfenv` (chmod 600)
  3. Serve: `vllm serve google/gemma-4-31B-it --port 8010 --quantization fp8
     --gpu-memory-utilization 0.55 --max-model-len 40000 --enable-auto-tool-choice
     --tool-call-parser gemma4` (vLLM ships a native **gemma4** tool parser)
  4. Reached from the Mac via **SSH tunnel** (8010 is firewalled externally):
     `ssh -N -L 8010:localhost:8010 root@box`; agent uses
     `--agent-llm openai/google/gemma-4-31B-it --api-base http://localhost:8010/v1`.
  **Three setup blockers fixed:** missing `python3.12-dev` (torch.compile C ext);
  FlashInfer sampler JIT needing nvcc → disabled via `VLLM_USE_FLASHINFER_SAMPLER=0`
  (we run greedy/temp 0, so no quality loss); KV-cache OOM at util 0.45 → 0.55.
  GPU after load: 81.5/96 GB used (28 others + ~53 ours), 15 GB free — coexists.
**Smoke result:** **0 LLM errors, structured tool_calls confirmed** (the gemma4
parser works) — the thing OpenRouter (rate limits) and the HF endpoint (pythonic
parser mismatch) never delivered. All 57 tools accepted, no caps.
**SECURITY:** the HF token leaked in plaintext into the chat transcript during a
failed redaction — user advised to ROTATE it.
**Launched:** `box_full_test_gemma4.toml` — test split, ALL 125 tasks × 3 trials
= 375 runs, no rate limits. First complete, clean Pass^3 for Gemma-4 (FP8, ≈full
precision — not 1:1 with the local 4-bit MLX numbers). Result pending → leaderboard.
**Related:** MODIFICATIONS 2026-05-31 12:15 (OpenRouter, abandoned), the GPU/
hosting discussion.

## 2026-05-31 12:15 — Switch to OpenRouter for Gemma-4-31B-it; full 125-task run launched
**Author:** Claude (at user's request)
**Files:**
  - `scenarios/track_1_agent_under_test/openrouter_smoke_gemma4.toml` (created)
  - `scenarios/track_1_agent_under_test/openrouter_full_test_gemma4.toml` (created)
**Context:** The self-hosted HF vLLM endpoint had tool-calling unusable: first
it lacked `--enable-auto-tool-choice/--tool-call-parser`; after enabling, the
`pythonic` parser mismatched Gemma-4's native `call:name{...}` output → tool
calls leaked as text (`has_tool_calls=False`). Rather than fight vLLM
parser/template config, switched to a serverless provider that pre-configures
tool calling.
**Change:** Verified via OpenRouter's models API that
`google/gemma-4-31b-it` is served with `tools=True` (262k ctx). Routed the
agent via LiteLLM `openrouter/google/gemma-4-31b-it` (key from .env
OPENROUTER_API_KEY; no api_base needed) + `--sanitize-tool-schemas`. No code
change — reused the existing LiteLLM path.
**Smoke (1/1/1):** **structured tool_calls returned** (has_tool_calls=True,
num_tool_calls=2), **0 errors**, 81 s for 3 tasks (~27 s/task-trial → ~5×
faster than local MLX). The HF-config blocker is bypassed.
**Launched:** `openrouter_full_test_gemma4.toml` — test split, ALL tasks
(base 50 + hall 50 + disamb 25 = 125) × 3 trials = 375 runs → our first
COMPLETE test-split Pass^3. ETA ~3 h. Note: OpenRouter serves full/provider
precision (not the local 4-bit MLX), so the number is the "real" model, not
1:1 with the 0.733 MLX seen-set figure.
**Why:** User chose OpenRouter to host Gemma-4 with working tool calling and
finish the full run fast.
**Related:** MODIFICATIONS 2026-05-31 11:30 (HF endpoint attempt, abandoned).

## 2026-05-31 11:30 — Isolated HF Inference Endpoint path (Gemma-4-31B-it on H200)
**Author:** Claude (at user's request)
**Files:**
  - `src/track_1_agent_under_test/car_bench_agent.py` (modified — new __init__
    params `api_base`, `api_key`, `sanitize_tool_schemas`, all None/False by
    default; route to custom OpenAI-compatible endpoint when api_base set;
    tool-schema strip now also triggers on `sanitize_tool_schemas`)
  - `src/track_1_agent_under_test/server.py` (modified — `--api-base`,
    `--api-key-env`, `--sanitize-tool-schemas` flags + env fallbacks
    AGENT_API_BASE / AGENT_API_KEY / AGENT_SANITIZE_TOOL_SCHEMAS)
  - `scenarios/track_1_agent_under_test/hf_smoke_gemma4.toml` (created)
  - `scenarios/track_1_agent_under_test/hf_full_test_gemma4.toml` (created)
**Change:** Added a fully ISOLATED path to drive the agent against an HF
Inference Endpoint (2× H200, 282 GB) serving `google/gemma-4-31B-it` over the
OpenAI-compatible TGI API. Routing = `--agent-llm openai/google/gemma-4-31B-it`
+ `--api-base https://yctfrmfr525dp5q4.us-east-2.aws.endpoints.huggingface.cloud/v1`
+ `--api-key-env HF_ENDPOINT_TOKEN` (token lives in .env, never on CLI/TOML)
+ `--sanitize-tool-schemas` (TGI's tool parser is strict like Ollama's).
**Isolation guarantee:** every new param defaults to None/off, so the existing
Gemini/Opus/Ollama scenarios and the agent's default behavior are byte-for-byte
unchanged (verified: the ollama strip still triggers on `"ollama" in model`;
cache_control still anthropic-only; no global OPENAI_* env hijack — api_base/key
are passed per-call only when set). Both modules syntax-check clean.
**Status:** endpoint starting; token pending. NOT run yet.
**Plan:** user adds `HF_ENDPOINT_TOKEN=<token>` to .env → run
`hf_smoke_gemma4.toml` first (confirm valid tool_calls come back from TGI;
watch for model-name 404 → fallback `openai/tgi`) → then `hf_full_test_gemma4.toml`
(125 tasks × 3 = first complete test-split Pass^3).
**Why:** User wants the full 125-task set fast via an H200 HF endpoint without
breaking the existing local/cloud setup.
**Related:** MODIFICATIONS 2026-05-31 10:06 (Gemma4 unseen 0.583), the
GPU-sizing discussion that led here.

## 2026-05-31 10:06 — Gemma4 on the 12 UNSEEN tasks (held-out reality check)
**Author:** Claude (at user's request)
**Files:**
  - `scenarios/track_1_agent_under_test/exp_D_gemma4_unseen.toml` (created)
  - `leaderboard.html` (added config D row + generalization finding to the
    controlled-experiment panel)
**Setup:** Gemma4:31b-mlx on the same 12 held-out tasks as the A/B/C experiment
(base 41/61/81/99, hall 41/61/81/97, disamb 41/43/47/49), Pass^3, thinking off,
T=0, $0 local. Output:
`…exp_D_gemma4_unseen…ollama_chat-gemma4-31b-mlx.json`.
**Result:** Avg Pass^3 **0.583** (Base .50 / Hall .75 / Disamb .50), Pass@3
0.667, 0 errors, ~2.0 h.
**Findings (same 12 tasks, controlled):**
  - **Gemma4 0.583 beats Gemini-baseline 0.333 on the unseen set** — the local
    $0 model is our best held-out agent.
  - **Gemma4 generalizes far better:** seen→unseen drop −0.15 (.733→.583) vs
    Gemini −0.47 (.80→.333). Gemini was heavily over-fit to the first-20 set.
  - Gap is dominated by Hallucination: Gemma4 .75 vs Gemini .00 on these 4.
  - Caveat: n=12 (per-split n=4) — directional, not significant. A full
    125-task run (e.g. via an H100 HF endpoint) would confirm.
**Why:** User asked to run Gemma4 on the 12 unseen tasks to see if its 0.733
(seen) holds out-of-sample.
**Related:** MODIFICATIONS 2026-05-30 16:50 (Gemma4 vs Qwen seen), 15:45 (A/B/C
unseen baseline 0.333).

## 2026-05-30 16:50 — Local OSS comparison: Gemma4 vs Qwen3.6 (Ollama, $0)
**Author:** Claude (at user's request)
**Files:**
  - `scenarios/track_1_agent_under_test/local_test_set_ollama_gemma4_jg.toml` (created — exact mirror of the qwen ollama scenario, model swapped)
  - `leaderboard.html` (added Gemma4 as ranked row #2*; demoted Opus to #3*/#4*;
    Qwen row annotated; alt-backends Ollama section rewritten as a Gemma4-vs-Qwen table)
**Setup:** pulled `gemma4:31b-mlx` (20 GB, MLX, macOS-only; verified it
advertises `tools`+`thinking`). Ran the SAME 60 seen test tasks (first 20 per
split, 3 trials, thinking off, T=0) as the qwen run — apples-to-apples.
**Result (same 60 tasks, $0 local):**
  | Model | Avg P^3 | Base | Hall | Disamb | Pass@3 | errors | wall |
  | --- | --- | --- | --- | --- | --- | --- | --- |
  | **Gemma4:31b-mlx** | **0.733** | .80 | .70 | .70 | .78 | **0** | 6.7 h |
  | Qwen3.6:35b-mlx | 0.417 | .60 | .35 | .30 | .72 | 20 | 3.4 h |
  Output: `…local_test_set_ollama_gemma4_jg…gemma4-31b-mlx…json`.
**Findings:** Gemma4 beats Qwen by **+0.32 Avg Pass^3** with **0 errors**
(vs 20), especially on the hard splits (Hall .70 vs .35, Disamb .70 vs .30).
At 0.733 local/$0 Gemma4 sits near our harnessed Gemini (0.80) and above every
Opus config + every official baseline on this seen set — strong "Best
Innovation" (local, zero-cost) data point. Trade-off: ~2× slower (6.7 vs 3.4 h).
This CONTRADICTS the prior assumption that Gemma's tool calling is weaker —
on CAR-bench, gemma4:31b-mlx is both more accurate and cleaner (0 malformed
calls). Caveat: seen first-20 set (easier); held-out would be lower for both.
**Why:** User asked to pull Gemma4 and run the Ollama comparison vs Qwen.
**Related:** MODIFICATIONS 2026-05-29 09:31 (qwen run), 2026-05-28 20:20
(tool-schema fix enabling Ollama).

## 2026-05-30 15:45 — Controlled 3-way experiment on 12 UNSEEN tasks (A/B/C)
**Author:** Claude (at user's request)
**Files:**
  - `src/track_1_agent_under_test/{car_bench_agent,server}.py` (modified —
    added `--suppress-tools` to hide named tools from the LLM, e.g. planning_tool)
  - `scenarios/track_1_agent_under_test/exp_{A_baseline,B_verifycode,C_noplanning}.toml` (created)
  - `leaderboard.html` (added a "Controlled 3-way experiment" panel + a caveat
    that the headline 0.80 is task-selection-optimistic)
**Setup:** 12 previously-unseen test tasks (ids beyond the first-20 used in all
prior runs): base 41/61/81/99, hall 41/61/81/97, disamb 41/43/47/49; Pass^3
(3 trials). Three configs differing by one factor: A=baseline (0.80 config),
B=A+`--verify-mode code`, C=A+`--suppress-tools planning_tool`. Implemented via
the new `tasks_*_task_id_filter` config keys (existing evaluator feature).
First attempt used an invalid id `hallucination_99` (that split ends at 97) →
fixed to 97 and re-ran cleanly.
**Result (n=12 × 3):**
  | Config | Avg P^3 | Base | Hall | Disamb | Pass@3 | LLM calls | wall | plan-errs |
  | --- | --- | --- | --- | --- | --- | --- | --- | --- |
  | A baseline | 0.333 | .50 | .00 | .50 | .83 | 525 | 84 min | 204 |
  | B verify-code | 0.250 | .25 | .25 | .25 | .83 | 667 | 97 min | 222 |
  | C no-planning | 0.333 | .25 | .25 | .50 | .75 | **254** | **42 min** | **0** |
  Output files:
  `…exp_A_baseline…`, `…exp_B_verifycode…`, `…exp_C_noplanning…` (2026-05-30).
**Findings:**
  1. **Held-out tasks are far harder: ~0.33 vs 0.80** on the first-20 set →
     the 0.80 headline is partly task-selection-dependent / optimistic. Most
     important result; tempers all prior leaderboard claims.
  2. **C (planning suppression) matched baseline Pass^3 at ~half the LLM calls
     (254 vs 525) and half the wall time, with 0 planning errors** (vs 204).
     The planning tool is pure cost here — dropping it is a clean efficiency
     win (reliability neither improved nor hurt in this sample).
  3. **B (code-verify) did not help** (nominally lower + more expensive).
  4. **n=12 caveat:** per-split n=4 → 0.25-step granularity; the A/C-vs-B gap
     is within noise, NOT significant. Only (1) and the (2) efficiency result
     are robust.
**Why:** User-designed controlled experiment to test the planning-suppression
and verify ideas on unseen tasks, all three onto the leaderboard.
**Related:** MODIFICATIONS 2026-05-29 15:30 (#1 self-consistency failed),
the planning-tool finding (545 errors) that motivated config C.

## 2026-05-29 15:45 — Revert scenario to best config (0.80); park harness ideas
**Author:** Claude (at user's request)
**Files:**
  - `scenarios/track_1_agent_under_test/local_test_set_jg.toml` (reverted to the
    0.80 config: gemini-3.5-flash + 7-rule prompt + medium thinking, T=0, single
    pass — removed `--self-consistency-n/-temp` and `--verify-mode`; header
    rewritten to document it as the best-known config)
  - `IDEAS.md` (marked #1/#2/#6 as "VORLÄUFIG NICHT ZIELFÜHREND")
**Change:** Restored the leaderboard-leading configuration. The self-consistency
+ verify code stays in the agent but is OFF by default (n=1, verify_mode=off),
so the reverted scenario reproduces the 0.80 behavior exactly — no functional
trace of the failed experiment remains in the run path.
**Why:** User: reset to the best-producing state, discard the rest, mark the
ideas as preliminarily not promising. The −0.20 regression (15:30 entry) showed
self-consistency hurts this deterministic agent.
**Note:** The #1/#2/#6 implementation was NOT physically deleted (it's dormant,
documented, and #6's isolated effect was never cleanly measured). Can be ripped
out on request.
**Related:** MODIFICATIONS 2026-05-29 15:30 (the negative result), 2026-05-28
17:52 (the 0.80 run this restores).

## 2026-05-29 15:30 — A/B run: #1 self-consistency + #6 code-verify → NEGATIVE result
**Author:** user (ran); Claude (analysis + leaderboard)
**Files:** `leaderboard.html` (added regressed row marked ✗ + explanation),
`IDEAS.md` (#1 → tried-failed; #2/#6 → confounded, need isolated re-test)
**Result:** Gemini 3.5 Flash + 7-rule prompt + medium thinking + **#1
self-consistency(n=3, T=0.7) + #6 code-verify**, TEST split n=60×3.
  | Metric | Baseline 0.80 | This run | Δ |
  | --- | --- | --- | --- |
  | Avg Pass^3 | 0.800 | **0.600** | −0.200 |
  | Base | 1.00 | 0.85 | −0.15 |
  | Hallucination | 0.65 | 0.65 | 0 |
  | Disambiguation | 0.75 | **0.30** | −0.45 |
  | Pass^1 | 0.883 | 0.767 | −0.117 |
  | Pass@3 | 0.933 | 0.883 | −0.05 |
  | LLM calls | 1,504 | 5,117 (3.4×) | |
  | prompt tokens | 26.4M | 98.6M (3.7×) | |
  | tasks errored | 3 | 0 | |
  Output:
  `output/track_1_agent_under_test/20260529-153049__track_1_agent_under_test-local_test_set_jg__test-trials3-base20-hall20-dis20__gemini-gemini-3.5-flash__medium.json`
**Diagnosis:** Mechanically clean (0 errors) but a clear REGRESSION, driven by
Disambiguation collapsing .75→.30. Most likely cause: self-consistency forces
candidate temperature > 0 (we used 0.7); the 0.80 baseline ran at T=0
(deterministic). Higher temperature injects variance, and majority voting then
selects the wrong action — precisely on internal disambiguation, where the
deterministic run reliably pulled the preference. The premature-closure
heuristic in code-verify may also over-correct valid confirmation turns. Net:
self-consistency is a poor fit for an already-deterministic, well-tuned agent.
**Decision:** #1 self-consistency = tried-failed, not used. #6 code-verify and
#2 are confounded here (SC dominated) — their isolated effect is still unknown.
The 0.80 config (no SC, no verify, T=0) remains our best/leader. The
`local_test_set_jg.toml` flags should be reverted to the 0.80 config (or set to
the isolated code-verify-only experiment) before any further run.
**Why:** completes the #1/#2/#6 experiment the user requested; records the
negative result honestly so we don't repeat it.
**Related:** MODIFICATIONS 2026-05-29 09:20 (#1+#2 impl), 10:05 (#6 impl),
2026-05-28 17:52 (the 0.80 baseline).

## 2026-05-29 10:05 — Implement #6: latency-aware variant (parallel candidates + code grounding)
**Author:** Claude (at user's request)
**Files:**
  - `src/track_1_agent_under_test/car_bench_agent.py` (modified)
  - `src/track_1_agent_under_test/server.py` (modified)
  - `IDEAS.md` (modified — added #6)
**Change:** Two deployment-faithful upgrades to #1/#2, motivated by the
real-time-in-car latency discussion:
  - **Parallel self-consistency candidates:** the N candidate calls now run
    concurrently via `concurrent.futures.ThreadPoolExecutor` (split
    `_invoke_llm` into `_raw_completion` (thread-safe, no shared state) +
    `_accumulate` (main-thread metrics)). Per-turn wall time ≈ slowest call
    instead of the sum.
  - **Code-based grounding check (`--verify-mode code`):** `_structural_issues`
    runs instantly with no LLM — (a) rejects tool calls to tools not in the
    provided list, (b) rejects parameters not in a tool's schema (both exact,
    zero false positives → catch missing-tool/parameter hallucinations), and
    (c) a conservative premature-closure heuristic (confirmation phrasing with
    no tool call). `_code_grounding_check` only spends ONE corrective LLM call
    when something is flagged; otherwise it returns the response unchanged
    (zero added latency). The old always-on LLM pass is now `--verify-mode llm`
    (legacy `--verify` maps to it). Env: `AGENT_VERIFY_MODE`.
**Why:** User confirmed: self-consistency + always-on LLM verify is unsuitable
for a real-time in-car voice assistant (~4 sequential LLM calls/turn, tens of
seconds). #6 keeps the reliability principle (verify before confirming —
safety-critical in a car) but makes it cheap: parallel sampling + an instant
code check that escalates to the LLM only when needed. Rules-compliant
(verification of internal grounding, not metric repair; task-agnostic).
**Verification:** train smoke (n=3 parallel + verify-mode code, gemini-3.5-flash):
**0 errors**, 67 turns with parallel voting, 12 code-check flags (~18% of turns
triggered a corrective call → ~82% added zero latency). Pass 2/3 (smoke, not
statistically meaningful — mechanics confirmed only).
**Result:** Feature complete + verified. The full leaderboard A/B run via
`local_test_set_jg.toml` is NOT yet launched. Decision pending: the TOML still
carries `--verify` (= llm mode); switch to `--verify-mode code` for the
latency-aware A/B, or keep `llm` for the max-reliability A/B.
**Related:** IDEAS.md #6; MODIFICATIONS 2026-05-29 09:20 (#1+#2 base impl).

## 2026-05-29 09:31 — Ollama qwen3.6:35b-mlx test-split result → leaderboard (ranked)
**Author:** user (ran); Claude (analysis + leaderboard)
**Files:** `leaderboard.html` (modified — Ollama promoted from smoke-only to a
ranked TEST row #7*; baseline ranks renumbered 8–12; alt-backends Ollama row +
details updated)
**Result:** Ollama `qwen3.6:35b-mlx`, TEST split, n=60×3, thinking off, $0/local.
  - Avg Pass^3 **0.417** | Base 0.60 | Hallucination 0.35 | Disambiguation 0.30
  - Pass@3 0.717 | wall ~3.4 h | 603 calls | **cost $0**
  - **Ties the Gemini 2.5 Flash baseline (0.41)** fully local/free; beats
    Gemini 2.5 Pro (.38), GPT-4.1 (.37), Qwen3-32B (.31), xLAM (.16). Below the
    proprietary frontier and our harnessed runs.
  - Caveat: **20 of 180 task-trials errored** (OSS robustness — likely
    malformed tool calls / timeouts; each counts as a fail, so true capability
    is somewhat higher). The tool-schema `additionalProperties` fix (20:20
    entry) was the prerequisite for it running at all.
  - Output:
    `output/track_1_agent_under_test/20260529-093146__track_1_agent_under_test-local_test_set_ollama_jg__test-trials3-base20-hall20-dis20__ollama_chat-qwen3.6-35b-mlx.json`
**Why:** leaderboard update with the local-model data point; strong Track-1
"Best Innovation" angle (reliable, zero-cost, fully local agent).
**Related:** MODIFICATIONS 2026-05-28 20:20 (tool-schema fix enabling Ollama),
20:10 (model switch to MLX).

## 2026-05-29 09:20 — Implement #1 self-consistency voting + #2 grounding verify
**Author:** Claude (at user's request)
**Files:**
  - `src/track_1_agent_under_test/car_bench_agent.py` (modified — extracted
    `_invoke_llm` (metrics-accumulating single call), added `_response_signature`,
    `_vote`, `_verify_and_revise`; refactored the completion section to
    candidates→vote→verify; new `__init__` params)
  - `src/track_1_agent_under_test/server.py` (modified — `--self-consistency-n`,
    `--self-consistency-temp`, `--verify` CLI flags + `AGENT_SELF_CONSISTENCY_N`
    / `_TEMP` / `AGENT_VERIFY` env fallbacks, passed to the executor)
  - `scenarios/track_1_agent_under_test/local_test_set_jg.toml` (modified —
    appended `--self-consistency-n 3 --self-consistency-temp 0.7 --verify`;
    header updated with A/B framing vs the 0.80 baseline + cost warning)
  - `IDEAS.md` (modified — new "Reliability harness" section with #1–#5; #3/#4
    marked DEFERRED; old "Temperatur > 0 mit Self-Consistency" marked superseded)
**Change:** Implemented two rules-compliant, task-agnostic reliability levers:
  - **#1 Self-consistency voting**: when `self_consistency_n>1`, sample N
    candidates per turn (temperature = self_consistency_temp, only set for
    models that accept temperature) and pick the majority *action shape*
    (tool-call set, or act-vs-text) via `_vote`. Default n=1 → unchanged.
  - **#2 Grounding self-verification**: when `--verify`, a final pass shows the
    model its own draft and asks it to re-examine for grounding errors (claimed-
    but-unexecuted action, invented values, "unknown"-as-real, missing
    tools/params, unresolved ambiguity) and emit the corrected final reply.
    Checks INTERNAL grounding only — never the evaluator's sub-scores — so it
    is allowed verification, not prohibited repair (RULES.md §4).
  All LLM calls (candidates + verify) accumulate into turn metrics via the new
  `_invoke_llm` helper (which now creates the metrics dict BEFORE the call, so
  a first-call failure no longer KeyErrors the final `.pop`).
**Verification:** ran a 3-task train smoke (n=3 + verify, gemini-3.5-flash):
  16 `Self-consistency vote` + 16 `Grounding verify pass applied` log lines,
  **0 errors, 3/3 passed**, ~162 s/task (≈4 LLM calls/turn).
**Why:** User picked #1+#2 from the rules-compliant options to attack the
Hallucination + Disambiguation weaknesses (Pass@3 0.95 → consistency is the
limiter). #3 (plan scaffold) and #4 (fine-tuning) deferred.
**Result:** Code verified working; the leaderboard A/B run via
`local_test_set_jg.toml` is queued (not launched — heavy: ~4x calls × medium
thinking). Awaiting the user to start it.
**Related:** MODIFICATIONS 2026-05-29 07:40 (regression analysis that motivated
these), IDEAS.md "Reliability harness" #1/#2.

## 2026-05-29 07:40 — Task-anatomy + Opus-regression explainer doc
**Author:** Claude (at user's request)
**Files:**
  - `docs/task-anatomy-and-opus-regression.md` (created)
  - `IDEAS.md` (modified — 2 new ideas: "never say done without tool call",
    "selective thinking per task shape")
**Change:** Wrote a standalone explainer of how Base / Disambiguation /
Hallucination tasks are structured (fields, the three hallucination flavors,
the disambiguation priority policy, the 0/1 reward model), and an exemplary
root-cause of the Opus thinking=medium Disambiguation regression. Found a
concrete case (`disambiguation_7`): thinking-off passes 3/3, thinking-medium
2/3; the failing trial fetched the preference correctly (level 3) then
narrated "Done! Set to level 3" WITHOUT emitting `set_fan_speed` — premature
closure where the model conflates deciding with doing. Diagnosis grounded in
the actual trajectories.
**Why:** User wanted to understand task construction and why Opus regressed.
**Result:** doc delivered; two mitigation ideas logged.
**Related:** MODIFICATIONS 2026-05-29 07:19 (the thinking run), 06:33 (the
flow dumps this doc references).

## 2026-05-29 07:19 — Opus 4.8 thinking=medium test-split result → leaderboard
**Author:** user (ran); Claude (analysis + leaderboard)
**Files:** `leaderboard.html` (modified — added Opus thinking-medium as ranked
row #2*; demoted thinking-off to #3*; alt-backends details extended)
**Result:** Opus 4.8, TEST split, n=60×3, adaptive thinking / effort=medium,
caching on. Output:
`output/track_1_agent_under_test/20260529-071947__…__anthropic-claude-opus-4-8__medium.json`
  - Avg Pass^3 **0.717** (vs 0.683 thinking-off) | Base **1.00** | Hallucination
    0.65 | Disambiguation **0.50** | Pass@3 0.95 | wall ~1.5 h | 655 calls
  - **Key finding:** thinking made Base perfect and nudged Hallucination up
    (.60→.65) but HURT Disambiguation (.65→.50) — over-thinking / second-
    guessing on disambiguation. Net +0.034 Avg Pass^3. Pass@3 rose to 0.95
    (latent capability up; consistency is the limiter).
  - **Cost:** estimated ~$18. Input cached like the thinking-off run
    (prompt 12.9M tokens, same system+tools prefix). Output cost is a LOWER
    BOUND: LiteLLM does not report adaptive-thinking reasoning tokens
    (thinking_tokens=0 in turn_metrics) but Anthropic bills them as output.
    The completed run's own cache log wasn't captured (the /tmp log belongs to
    the earlier killed run), so input cost is estimated from the thinking-off
    run's near-identical cache structure.
  - Ranking: 0.72 beats all baselines and thinking-off Opus (0.68) but still
    trails our harnessed Gemini 3.5 Flash test run (0.80).
**Why:** User: "danach nochmal mit Opus und thinking auf Medium" + auswertung
+ leaderboard.
**Related:** MODIFICATIONS 2026-05-28 22:14 (thinking-off Opus), 21:25
(thinking API fix), 23:01 (earlier killed attempt).

## 2026-05-29 06:33 — Agent-prompt dump hook + flow renderer; produced 3 example flows
**Author:** Claude (at user's request)
**Files:**
  - `src/track_1_agent_under_test/car_bench_agent.py` (modified — env-gated
    `DUMP_PROMPT_DIR` hook: writes the exact outbound payload
    {model, thinking, tools, messages} per context before each LLM call,
    overwriting so the file ends as the full conversation; off by default)
  - `scripts/render_agent_flow.py` (created — renders dumps + a run output
    JSON into readable per-task-type transcripts)
  - `output/agent_flows/agent_flow_{base,hallucination,disambiguation}.txt`
    (created — the deliverable)
**Change:** The user wanted to see exactly how the agent is driven, one full
flow per task type. The output JSON trajectories contain the conversation but
NOT the system prompt or tool schemas (those are sent separately, built in
`car_bench_evaluator.py:121` from the CAR-bench policy wiki). Added a faithful
dump hook and a renderer, then ran a tiny scenario (1 base + 1 hall + 1
disamb, train, gemini-3.5-flash, ports 8088/8089 to avoid collision) to
capture each flow.
**Result:** Three readable files, each with: task metadata (instruction,
persona, removed_part), the FULL system prompt (CAR-bench policy wiki + our
"Additional operating rules" supplement), the tool list, and the complete
turn-by-turn flow (user / agent text+tool_calls / tool results). Fidelity
check: base & disambiguation show 57 tools, hallucination shows 56
(open_close_sunshade removed — exactly the capability that task strips).
Note: the *feeding* (system + tools + evaluator user/tool turns) is
model-agnostic; gemini-3.5-flash was used to generate the example responses,
but the structure is identical for Opus/Ollama. Can re-render a specific
model's actual responses from that run's trajectory on request.
**Why:** User: "für alle drei tasks jeweils eine volle Prompt bzw. einen
ganzen Ablauf … in Dateien speichern."
**Related:** reuses the dump approach from the 20:20 tool-schema debugging.

## 2026-05-28 23:01 — Opus 4.8 thinking=medium test-split run KILLED (no result)
**Author:** Claude (ran); run stopped externally
**Files:** none
**Change:** Started `local_test_set_opus_thinking_jg.toml` (Opus 4.8, test
split, n=60×3, adaptive thinking / effort=medium). The 1-task thinking
verification beforehand passed (reward 1.0, 0 errors — confirms the
adaptive-thinking code path works). The full run reached ~102/180 task-trials
with 0 errors and caching active (321 cache reads logged), then was killed
before completion, so NO result JSON was written and there is no thinking
score to report. Leaderboard unchanged.
**Why:** User asked for the thinking=medium comparison; documenting that it did
not complete.
**Next:** re-run `local_test_set_opus_thinking_jg.toml` end-to-end to get the
comparable thinking number (vs Opus thinking-off 0.68 and Gemini 0.80).
**Related:** MODIFICATIONS 2026-05-28 22:14 (thinking-off result), 21:25
(thinking API fix).

## 2026-05-28 22:14 — Opus 4.8 test-split result (thinking off) + caching cost win → leaderboard
**Author:** user (ran); Claude (analysis + leaderboard)
**Files:** `leaderboard.html` (modified — Opus now a ranked test-split row;
train row demoted to "superseded"; cache savings documented; stale split caveat
removed)
**Result:** Opus 4.8, TEST split, n=60×3, thinking off, caching ON.
  - Avg Pass^3 **0.683** | Base 0.80 | Hallucination 0.60 | Disambiguation 0.65
  - Pass@3 0.85 | 676 LLM calls | wall 4162 s (~69 min)
  - **Caching impact (verified from logs):** cache_read 11.60M, cache_creation
    1.65M, regular input ~2.4k. Cost at $5/$25 with Anthropic cache rates
    (write 1.25×, read 0.1×): **$17.75 total** ($16.11 input + $1.64 output)
    vs **$67.91** with no caching → **$50.16 saved, 74% off input**. Per
    unique task $0.30; extrapolated full 254×3 ≈ $75.
  - Output only 66k tokens ($1.64) — Opus is very concise.
  - Ranking: 0.68 beats every leaderboard baseline (top: Opus 4.6 = 0.58) but
    trails our harnessed Gemini 3.5 Flash test run (0.80). I.e. harnessing +
    a cheaper model currently beats raw thinking-off Opus 4.8 on this sample.
  - Output file:
    `output/track_1_agent_under_test/20260528-221450__track_1_agent_under_test-local_test_set_opus_jg__test-trials3-base20-hall20-dis20__anthropic-claude-opus-4-8.json`
**Why:** Comparable (test-split) Opus number + demonstrate the caching fix's
financial impact.
**Related:** MODIFICATIONS 2026-05-28 21:10 (caching fix), 21:25 (thinking
fix). Next: the Opus thinking=medium run.

## 2026-05-28 21:25 — Fix Opus 4.8 thinking API (adaptive + output_config.effort); queue thinking run
**Author:** Claude (at user's request)
**Files:**
  - `src/track_1_agent_under_test/car_bench_agent.py` (modified — new
    opus-4-8 branch in the thinking config)
  - `scenarios/track_1_agent_under_test/local_test_set_opus_thinking_jg.toml`
    (created — Opus 4.8 test split + `--thinking --reasoning-effort medium`)
**Change:** Discovered (via standalone litellm probes) that Opus 4.8 does NOT
accept the agent's existing thinking mechanisms:
  - `reasoning_effort` → litellm `UnsupportedParamsError` for claude-opus-4-8.
  - `thinking={"type":"enabled","budget_tokens":N}` → Anthropic
    `invalid_request_error`: "thinking.type.enabled is not supported for this
    model. Use thinking.type.adaptive and output_config.effort".
  The working form (verified): `thinking={"type":"adaptive"}` +
  `output_config={"effort":"medium"}` + `allowed_openai_params=["thinking",
  "output_config"]` (the allow-list is required because litellm's static
  registry doesn't yet know opus-4-8 supports these). Added an `"opus-4-8" in
  self.model` branch implementing exactly this; effort is taken from
  `--reasoning-effort` (low/medium/high, default medium). Without this fix the
  thinking run would have failed on every call.
**Why:** User: "danach nochmal mit Opus und thinking auf Medium." Pre-flighted
the param compatibility so the long run won't crash.
**Result:** Code ready; thinking TOML queued. NOT started yet — the
thinking-off test-split run is still occupying 8080/8081. Will run a 1-task
thinking verification, then launch the full thinking run, once the current
run completes.
**Related:** MODIFICATIONS 2026-05-28 21:10 (caching + thinking-off run),
19:55 (temperature drop for opus-4-8), IDEAS.md "Gemini thinking budget"
(analogous lever for a different provider).

## 2026-05-28 21:10 — Fix Anthropic prompt caching placement + verify + start Opus test-split
**Author:** Claude (at user's request)
**Files:**
  - `src/track_1_agent_under_test/car_bench_agent.py` (modified — corrected
    `cache_control` placement; added cache-token logging)
**Change:** Anthropic prompt caching was wired but in the WRONG places, so it
never took effect:
  - tools: `cache_control` was on `tools[-1]["function"]` → moved to the tool
    level `tools[-1]["cache_control"]` (sibling of type/function).
  - system: `cache_control` was a top-level message key on `messages[0]` with
    string content → now the system message content is converted to a
    text content block carrying `cache_control` (idempotent across turns;
    only for the system role).
  Also added an info log "Prompt cache usage: creation=… read=…" capturing
  `cache_creation_input_tokens` / `cache_read_input_tokens` from the response
  usage, so caching is observable in `--show-logs`.
**Verification (empirical, the user asked for it):**
  1. Standalone litellm probe with Opus 4.8: call 1 cache_creation=2935,
     read=0; call 2 read=2935 — confirmed the correct format produces hits.
  2. Real agent path, 1-task scenario (`_verify_opus_cache.toml`, since
     deleted): logged `creation=0 read=19042` then `read=19042` on subsequent
     turns — the full ~19k-token static prefix (system + 57 tool schemas) is
     served from cache every call, with only tiny incremental writes
     (creation=125/435) for new conversation tokens. 0 errors.
**Impact:** The static prefix dominates Opus input cost. At Anthropic's
standard cache-read rate (~0.1× input) this should cut the input portion of
the Opus bill by ~80–90%. Previous (uncached) train run input was $24.69 of
its $25.25 total.
**Cleanup:** Deleted temp scenarios `_verify_opus_cache.toml` and
`local_smoke_ollama_jg__parallel.toml`.
**Then:** Started the Opus 4.8 **test-split** run
(`local_test_set_opus_jg.toml`: test split, 20/20/20 × 3 trials, thinking off).
This one IS comparable to the leaderboard baselines. Result pending → next
entry + leaderboard update.
**Why:** User: "Arbeite für Opus 4.8 das Caching ein. Verifiziere dass das
läuft. Starte danach den Test-Split."
**Related:** MODIFICATIONS 2026-05-28 18:30 (original cache_control guard),
20:35 (Opus train run), IDEAS.md "Prompt caching aktivieren".

## 2026-05-28 20:35 — Opus 4.8 train run + Ollama smoke into leaderboard
**Author:** user (ran Opus); Claude (analysis + leaderboard update)
**Files:**
  - `leaderboard.html` (modified — added Opus 4.8 row marked n/a‡ "TRAIN
    split, not comparable"; new "Alternative backends" panel summarizing Opus
    + Ollama; new split-mismatch caveat; provenance updated)
**Change:** Logged two non-Gemini backend results.
**Opus 4.8 result (TRAIN split, n=30×3, thinking off, temp dropped):**
  - Avg Pass^3 **0.70** | Base 0.80 | Hall 0.80 | Disamb **0.50** | Pass@3 0.83
  - Cost **$25.25** at $5/$25 per MTok — input-dominated (4.94M in = $24.69;
    23k out = $0.57; Opus is very concise). Per unique task $0.84;
    extrapolated full 254×3 ≈ $214 / ~4.3 h. (LiteLLM reported $0.00 — no
    price table for opus-4-8.)
  - Disambiguation is the weak split (3 systematic fails: disamb_8/_12/_14);
    also base_16 and hallucination_0 systematic.
  - **CRITICAL caveat:** run on the **train** split, not test. NOT comparable
    to the test-split leaderboard baselines or our Gemini test runs. Marked
    n/a‡ in the table and excluded from ranking.
  - Output:
    `output/track_1_agent_under_test/20260528-202617__track_1_agent_under_test-local_smoke_opus_jg__train-trials3-base10-hall10-dis10__anthropic-claude-opus-4-8.json`
**Ollama qwen3.6:35b-mlx smoke (n=6, train):** 3/6 (Base 2/2, Hall 1/2,
Disamb 0/2). Runs cleanly after the 20:20 tool-schema fix. 42 s/task, $0,
thinking_tokens=0. Too small to rank; shown in the Alternative-backends panel
as smoke-only.
**Why:** User asked for a leaderboard update with the Opus result.
**Result:** leaderboard.html reflects both; no metric for our canonical
(Gemini test n=60, 0.80) changed.
**Related:** MODIFICATIONS 2026-05-28 20:20 (Ollama fix), 17:52 (Gemini
canonical run), IDEAS.md "Modellwechsel evaluieren".

## 2026-05-28 20:20 — Fix: strip `additionalProperties` from tool schemas for Ollama
**Author:** Claude (at user's request)
**Files:**
  - `src/track_1_agent_under_test/car_bench_agent.py` (modified — added
    `_strip_additional_properties()` helper + `import copy`; applied to a deep
    copy of the tools for `"ollama" in self.model` before the completion call)
  - `scenarios/track_1_agent_under_test/local_smoke_ollama_jg__parallel.toml`
    (created — port-shifted 8082/8083 copy so the Ollama smoke can run at the
    same time as the Opus run on 8080/8081; delete after use)
**Change:** The first Ollama smoke failed on every task with
`Ollama_chatException - "json: cannot unmarshal bool into Go struct field
...properties of type api.ToolProperty"`. Root cause (found by dumping the
live 57-tool payload via a temporary DUMP_TOOLS_ONCE hook, since redone):
the CAR-bench `calculate_datetime` tool schema places
`"additionalProperties": false` *inside* its `properties` object (one
indentation level too deep — malformed JSON Schema). Ollama's strict Go
parser tries to read that `false` as a property-schema object and crashes.
Hosted providers (Gemini, Anthropic) silently tolerate it, which is why
earlier runs were unaffected. Fix: recursively delete every
`additionalProperties` key from the tool schemas, but only for Ollama models,
on a deep copy so the stored definitions (and the Anthropic/Gemini code
paths) are untouched.
**Why:** Unblock the local Ollama qwen3.6:35b-mlx evaluation. `additionalProperties`
is advisory for tool calling, so removing it is safe.
**Result:** After the fix, the agent produces valid tool calls via Ollama
(`has_tool_calls=True | num_tool_calls=2`, no unmarshal error). First-response
latency ~26 s for the 35B MLX model locally. Full smoke result pending (see
next entry).
**Related:** MODIFICATIONS 2026-05-28 20:10 (model switch), 18:30
(cache_control guard — same "Anthropic-only marker" theme).

## 2026-05-28 20:10 — Switch Ollama scenarios to qwen3.6:35b-mlx
**Author:** Claude (at user's request); user pulled the model
**Files:**
  - `scenarios/track_1_agent_under_test/local_smoke_ollama_jg.toml` (modified)
  - `scenarios/track_1_agent_under_test/local_test_set_ollama_jg.toml` (modified)
**Change:** Both Ollama scenarios now use `ollama_chat/qwen3.6:35b-mlx` (was
`qwen3.6:latest`). User pulled the MLX build (~21 GB, Apple-Silicon-optimized,
faster than GGUF on Mac).
**Why:** User wants to test their own suggestion `qwen3.6:35b-mlx`. The MLX
build is the speed-optimal local option on Apple Silicon, which matters
because walltime dominates a local n=60×3 run.
**Verification:** `ollama show qwen3.6:35b-mlx` confirms `tools` + `thinking`
capabilities — the hard requirement for CAR-bench. (Note: the Bash sandbox
intermittently lost reachability to the local Ollama daemon during setup;
this does not affect `uv run car-bench-run`, which executes in the user's
shell.)
**Result:** Not yet run. Ready for smoke then test.
**Related:** MODIFICATIONS 2026-05-28 18:30 (created Ollama scenarios),
IDEAS.md → "OSS-Modell via Ollama: Qwen3.6 empfohlen".

## 2026-05-28 19:55 — Fix: drop `temperature` for Opus 4.8 (API rejects it)
**Author:** Claude (at user's request)
**Files:**
  - `src/track_1_agent_under_test/car_bench_agent.py` (modified)
**Change:** `completion_kwargs` no longer unconditionally includes
`temperature`. Models listed in `TEMPERATURE_UNSUPPORTED` (currently
`("opus-4-8",)`) get the call built without a temperature param.
**Why:** The first `local_smoke_opus_jg.toml` run failed on every task with
`AnthropicException - "temperature is deprecated for this model"` (HTTP 400).
Opus 4.8 rejects the parameter outright; the agent was always sending
`temperature=0.0`. (User confirmed the API key is fresh and correct — the key
was never the issue.)
**Result:** Code fix only; not yet re-run. The Opus smoke should now proceed.
**Related:** MODIFICATIONS 2026-05-28 18:30 (created the Opus scenarios).

## 2026-05-28 18:30 — Add Opus 4.8 + local Ollama scenario variants; guard cache_control to Anthropic
**Author:** Claude (at user's request)
**Files:**
  - `src/track_1_agent_under_test/car_bench_agent.py` (modified — `cache_control`
    injection now gated on `"anthropic" in model or "claude" in model`)
  - `scenarios/track_1_agent_under_test/local_smoke_opus_jg.toml` (created)
  - `scenarios/track_1_agent_under_test/local_test_set_opus_jg.toml` (created)
  - `scenarios/track_1_agent_under_test/local_smoke_ollama_jg.toml` (created)
  - `scenarios/track_1_agent_under_test/local_test_set_ollama_jg.toml` (created)
**Change:** Four new scenario files for two alternative model backends, plus a
defensive code fix.
  - **Opus variants**: `anthropic/claude-opus-4-8`, temperature 0.0, thinking
    OFF by default (cost control). ANTHROPIC_API_KEY already present in .env
    (verified non-empty, sk-ant- prefix, len 108) — no other setup needed.
  - **Ollama variants**: `ollama_chat/qwen3.6:latest`. The `ollama_chat/`
    prefix (not `ollama/`) is required for reliable native tool calling.
    qwen3.6:latest is pulled locally (23 GB) and advertises `tools` +
    `thinking` (verified via `ollama show`). $0 cost, but local inference is
    slow → smoke first.
  - **Code fix**: `cache_control` is Anthropic-only. It was previously
    injected for every provider; LiteLLM dropped it for Gemini (our runs
    showed cached_tokens=0 anyway), but it is a latent failure risk for
    Ollama. Now gated to Anthropic/Claude models only. No regression for
    Gemini (marker was inert there) and it keeps Anthropic prompt caching
    working — relevant now that we actually run Anthropic.
**Why:** User wants to compare alternative model/cost points: a strong hosted
model (Opus 4.8 at $5/$25 per MTok) and a free local OSS model via Ollama.
"Make Anthropic ready first" → key verified, model string set, no code change
needed for Anthropic beyond the (beneficial) cache_control guard.
**Repo-adaptation question (user asked):** For Anthropic, none needed. For
Ollama, no hard code change is required — LiteLLM routes `ollama_chat/*` to
the local daemon (localhost:11434 by default) and supports tools. The only
latent issue was the Anthropic-specific cache_control marker, now guarded.
**Model recommendation (OSS):** qwen3.6:latest — see the chat message / next
IDEAS entry. The user's three guesses (qwen3.6:35b-mlx, gemma4:31b-mlx,
deepseek-v4-flash:cloud) do not match any pulled tag; only qwen3.6:latest and
qwen3.5:latest are local, and gemma4 is not installed.
**Result:** Not yet run. Awaiting smoke runs on each variant.
**Related:** IDEAS.md → "Modellwechsel evaluieren über die Tracks hinweg" and
the new OSS-model entry; MODIFICATIONS 2026-05-28 17:52 (Gemini baseline these
will be compared against).

## 2026-05-28 17:52 — Measurement of 7-rule prompt + medium thinking (n=60 × 3)
**Author:** user (ran via `uv run car-bench-run`)
**Files:** none new — measurement of the 12:00 prompt + scenario change.
**Change:** Same scenario as the 11:23 run; only the SYSTEM_PROMPT (4→7
rules) and the Gemini thinking config (`--thinking --reasoning-effort
medium`) differ.
**Why:** Validate whether the targeted prompt edits closed the 8 systematic
failures and whether medium thinking compounded the effect.
**Result:** Output file:
`output/track_1_agent_under_test/20260528-175243__track_1_agent_under_test-local_test_set_jg__test-trials3-base20-hall20-dis20__gemini-gemini-3.5-flash__medium.json`.
Walltime 15 246 s (~4.2 h, +1.7 h vs previous).

  Scoreboard delta (same n=60 scenario):
  | Metric | 11:23 run | 17:52 run | Δ |
  | --- | --- | --- | --- |
  | Avg Pass^3 | 0.700 | **0.800** | +0.100 |
  | Base Pass^3 | 0.950 | **1.000** | +0.050 |
  | Hallucination Pass^3 | 0.500 | **0.650** | +0.150 |
  | Disambiguation Pass^3 | 0.650 | **0.750** | +0.100 |
  | Pass@3 | 0.867 | **0.933** | +0.066 |

  Targeted-fix bilanz (8 systematic failures from 11:23):
  - **Fully fixed (3/3 pass)**: `hallucination_23` (hand-calc),
    `hallucination_29` (missing parameter), `disambiguation_25`
    (secretary in CC). All 9 fail-trials recovered.
  - **Partially fixed (1/3 pass)**: `hallucination_11`, `hallucination_27`
    (both "unknown" return-field cases — Rule 5 helps but not deterministically).
  - **Still systematic (0/3 pass)**: `hallucination_33`, `hallucination_37`
    (the latter still hallucinates "10% SoC" from `remaining_range` despite
    Rule 5), `disambiguation_31` (Munich/Milan output inconsistency despite
    sharpened Rule 4).

  Regressions (passed before, fail now): 7 trials across 5 tasks —
  `disambiguation_9` (1/3 → 3/3 fail), `disambiguation_13` (0/3 → 1/3),
  `disambiguation_39` (0/3 → 1/3), `hallucination_19` (1/3 → 2/3),
  `hallucination_25` (last trial regressed).

  Net trial movement: +22 newly passing, −7 newly failing → **net +15
  trials** (90 → 75 fail-trials in the matrix; the table summary shows
  38 → 23 *non-flake-corrected* fail-trials).

  Cost (additive Gemini paid-tier pricing):
  | Component | 11:23 | 17:52 | Δ |
  | --- | --- | --- | --- |
  | Prompt tokens | 16.7M | 26.4M | +58% |
  | Completion tokens | 603k | 1,145k | +90% |
  | Thinking tokens | 518k | 1,015k | +96% |
  | LLM calls | 1,184 | 1,504 | +27% |
  | Cost | $35.14 | **$59.09** | +$23.95 (+68%) |
  | Per task-trial | $0.195 | **$0.328** | +68% |
  | Extrapolated full 254×3 | ~$149 | ~**$250** | +68% |
  | Extrapolated walltime | ~10.6 h | ~17.9 h | +69% |

  Reward / cost: +0.10 Avg Pass^3 cost $24 extra (and 1.7 h) → ~$2.4 per
  +0.01 Pass^3 on this sample.

  Open questions for next iteration:
  - Why does Rule 5 not stick on hallucination_37 (SoC = "unknown")? The
    agent still invents "10%" from `remaining_range` — perhaps a stronger
    "do not derive missing values from related fields" callout is needed.
  - disambiguation_9 regression (1/3 → 3/3) suggests the sharpened Rule 2
    (preference-lookup-before-any-preference-relevant-action) over-fires
    on requests that are already unambiguous. Worth narrowing the trigger
    to "value left unspecified by user".
  - disambiguation_31 is unchanged — Munich/Milan summary inconsistency
    survives Rule 4. The trajectory also still shows planning-tool retry
    storms; may be worth a separate rule prohibiting the planning tool when
    it has failed twice on this turn.
**Related:** MODIFICATIONS 2026-05-28 12:00 (the prompt + thinking change),
11:35 (the previous n=60 baseline this is compared against), IDEAS.md
status flips for rules 5/6/7 + thinking-budget.

## 2026-05-28 12:00 — Sharpen SYSTEM_PROMPT (rules 5–7) + enable Gemini medium thinking
**Author:** Claude (at user's request)
**Files:**
  - `src/track_1_agent_under_test/car_bench_agent.py` (modified —
    `SYSTEM_PROMPT` expanded from 4 to 7 rules)
  - `scenarios/track_1_agent_under_test/local_test_set_jg.toml` (modified —
    appended `--thinking --reasoning-effort medium` to the agent `cmd`)
  - `IDEAS.md` (modified — 4 ideas flipped from `proposed` to `in-progress`;
    new "Gemini thinking budget auf MEDIUM" entry added)
**Change:** Based on the per-trajectory analysis of the 8 systematic failures
in the 11:23 n=60 run, added three new SYSTEM_PROMPT rules and sharpened one
existing rule:
  - **Rule 5 (new)**: treat `"unknown"` tool-result fields as missing
    information, never as defaults; do not invent substitute values.
    Targets `hallucination_11` (fog_lights), `_27` (car_color), and `_37`
    (state_of_charge).
  - **Rule 6 (new)**: do not pass parameters that are not in the tool's
    schema; do not pretend a sub-action succeeded when its parameter was
    silently dropped. Targets `hallucination_29` (set_fan_speed.level).
  - **Rule 7 (new)**: when a required tool is missing, do not derive its
    output by hand-calculating from related tools and presenting it as a
    system result. Targets `hallucination_23` (get_distance_by_soc → manual
    range × SoC multiplication).
  - **Rule 2 (sharpened)**: preference lookup is now required *before any
    preference-relevant action* (emails, vehicle personalization,
    communication, settings), not only when the user leaves a value out.
    Targets `disambiguation_25` (missing secretary in business email).
  - **Rule 4 (sharpened)**: final user-facing message must be consistent
    with the last tool results. Targets `disambiguation_31` (Munich
    destination summarized as "to Milan").

  Additionally, the `cmd` in the leaderboard scenario now explicitly enables
  Gemini medium thinking (`--thinking --reasoning-effort medium`). Without
  the `--thinking` flag, the agent never passes `reasoning_effort` to
  LiteLLM (see `car_bench_agent.py:226`). The previous runs still showed
  thinking tokens because Gemini-3.5-Flash does some thinking by default,
  but the budget was not explicitly controlled.
**Why:** Capability-gap closure for the 8 systematic failures identified in
the 11:35 leaderboard analysis. Thinking-budget escalation is an
independent cost/quality lever that should compound with the prompt work.
**Result:** Not yet measured — awaiting next run on the same scenario.
**Related:** MODIFICATIONS 2026-05-28 11:35 (the n=60 run that surfaced these
failure modes), 06:45 (original 4-rule prompt), IDEAS.md → all four
hallucination/disambiguation idea entries plus the new Gemini-thinking
entry.

## 2026-05-28 11:35 — Update leaderboard with n=60 run (supersedes n=30)
**Author:** Claude (at user's request); user executed the 11:23 run
**Files:**
  - `leaderboard.html` (modified — headline metrics, ranking table now shows
    both our runs with the n=30 marked "superseded", cost section updated,
    new "Failure modes" panel with per-task pass/fail grid, caveats and
    provenance updated)
**Change:** Scenario was widened from n=30 to **n=60** (20 base / 20 hall /
20 disamb × 3 trials = 180 task-trials) and re-run. New result feeds the
leaderboard.
**Why:** User wanted a more reliable sample size before reading anything into
the 30-task numbers; we explicitly flagged sample-size bias in the n=30
caveats.
**Result:** Latest scores at n=60:
  - Avg Pass^3 **0.700** (was .867 at n=30; baseline Gemini 2.5 Flash .41)
  - Base Pass^3 **0.950** (was 1.00)
  - Hallucination Pass^3 **0.500** (was .70)
  - Disambiguation Pass^3 **0.650** (was .90)
  - Pass@3 **0.867** (was 1.00 — now 8 unique tasks fail in all 3 trials)

  Cost (additive Gemini paid-tier pricing): **$35.14** for this run · per
  task-trial $0.195 · per unique task $0.586 · extrapolated full 254×3 run
  ~$149 / ~10.6 h. Walltime this run: 9,009 s (~2.5 h). Disambiguation is
  now the dominant cost driver ($15.89) because of planning-tool retry
  storms increasing turn counts.

  Failure-mode summary: 38 fail-trials across 18 unique tasks.
  **8 of those 18 fail in all 3 trials** (systematic, not flake) —
  6 hallucination tasks (hallucination_11, _23, _27, _29, _33, _37) and 2
  disambiguation (disambiguation_25, _31). These are the targets for the
  next prompt/harness iteration. Hallucination split is now clearly the
  weakest reliability area at 0.50 Pass^3.

  Output file:
  `output/track_1_agent_under_test/20260528-112330__track_1_agent_under_test-local_test_set_jg__test-trials3-base20-hall20-dis20__gemini-gemini-3.5-flash.json`
**Related:** MODIFICATIONS 2026-05-28 09:20 (n=30 cost), 08:26 (n=30 run);
IDEAS.md 4 hallucination/disambiguation ideas added after the 08:26 run are
now strongly motivated.

## 2026-05-28 09:20 — Add cost breakdown to leaderboard HTML
**Author:** Claude (at user's request)
**Files:**
  - `leaderboard.html` (modified — new "Cost" section before the Caveats panel)
**Change:** Aggregated `turn_metrics` from the 08:26 run JSON to compute
token usage and apply user-stated paid-tier pricing
(input $1.50/M, output incl. thinking $9.00/M, cache $0.15/M). Total cost
this run: **$16.65** (additive reading of "output incl. thinking" = completion
+ thinking). Per task-trial $0.185. Extrapolated full 254×3 run: ~$141 and
~7.8 h. The HTML also shows the per-split breakdown (hallucination is the
dominant cost driver at $7.38, despite having the fewest LLM-call turns,
because thinking chains are long).
**Why:** User asked for cost transparency at the current pricing.
**Result:** Live in `leaderboard.html`. Note: `cached_tokens = 0` in this run
— prompt caching has either no hits or is not active for Gemini in our
LiteLLM setup; an obvious lever for the extrapolated full-set run.
**Related:** MODIFICATIONS 2026-05-28 09:05 (sample-size annotations),
08:26 (the run).

## 2026-05-28 09:05 — Annotate leaderboard HTML rows with sample size
**Author:** Claude (at user's request)
**Files:**
  - `leaderboard.html` (modified)
**Change:** Every row in the ranking table now carries an explicit
`n = <tasks> / <trials>` pill next to the model name (our run: `n = 30 /
3 trials`; baselines: `n = 254 / 3 trials`). The "Our Run · key metrics"
panel title also spells out the sample composition (10 base / 10 hall / 10
disamb × 3 trials).
**Why:** User wants the comparison-sample size to be visible at a glance on
every entry, so the headline numbers can't be read in isolation from their
denominator. From now on, all leaderboard/comparison artifacts should carry
the sample-size annotation in the run title itself.
**Result:** Visual only — no metric changes.
**Related:** MODIFICATIONS 2026-05-28 08:55 (initial HTML), 08:26 (the run).

## 2026-05-28 08:55 — Generate local leaderboard HTML snapshot
**Author:** Claude (at user's request)
**Files:**
  - `leaderboard.html` (created at repo root)
**Change:** Single-file HTML snapshot of the official leaderboard baselines
plus our 08:26 run, sorted by Avg Pass^3 desc. Our row is highlighted and
marked rank "1*" (asterisk for the sample-size caveat). Includes a "Caveats"
section that explicitly states the 30-task sample limit, deterministic task
selection, the un-ablated two-lever change (model + prompt), Pass@3 = 1.0
significance, and that this is development validation only — not a
competition-official ranking.
**Why:** User asked for a visual snapshot of where our run lands in the
baseline ranking, with our run included.
**Result:** Static file at repo root, openable directly in a browser. No
build step required; CSS is inline.
**Related:** MODIFICATIONS 2026-05-28 08:26 (the run that feeds the data).

## 2026-05-28 08:26 — Leaderboard-comparison run (local_test_set_jg, 30 tasks × 3 trials)
**Author:** user (ran via `uv run car-bench-run`)
**Files:** scenario was widened pre-run from 10/10/5 to 10/10/**10** (30 tasks).
The on-disk `scenarios/track_1_agent_under_test/local_test_set_jg.toml` now
shows `tasks_disambiguation_num_tasks = 10`.
**Change:** First full Pass^3 measurement against the public test split.
**Why:** Reproduce a leaderboard-style measurement; target was Gemini 2.5
Flash baseline (Avg Pass^3 .41).
**Result:** Output file:
`output/track_1_agent_under_test/20260528-082604__track_1_agent_under_test-local_test_set_jg__test-trials3-base10-hall10-dis10__gemini-gemini-3.5-flash.json`.
Walltime 3305s (~55 min).

  | Metric | This run | Gemini 2.5 Flash baseline | Δ |
  |---|---|---|---|
  | Avg Pass^3 | **0.867** | 0.41 | +0.46 |
  | Base Pass^3 | 1.00 | 0.59 | +0.41 |
  | Hallucination Pass^3 | 0.70 | 0.41 | +0.29 |
  | Disambiguation Pass^3 | 0.90 | 0.22 | +0.68 |
  | Pass@3 | 1.00 | — | — |

  Caveats: 30 tasks of 254 (~12%), so confidence intervals are wide; the test
  selection is deterministic and likely the same first-N-per-split each run;
  and we changed both model (2.5→3.5) and prompt at once, so the levers are
  not yet ablated.

  `Pass@3 = 1.0` means every task is solvable at least once — the remaining
  loss is purely consistency.

  Failure modes observed (5 fail-trials across 4 unique tasks):
  - `hallucination_5/trial0`: removed_part is the `level` *parameter* of
    `set_fan_speed`, not a whole tool. Agent claimed it set the fan speed
    level. Triggered `HALLUCINATION_ERROR_REMOVED_PARAMETER`. Our prompt
    only covers missing tools, not missing parameters.
  - `hallucination_19/trial0`+`trial2`: `get_contact_id_by_contact_name`
    removed. Agent tried Calendar/Email/Navigation as workarounds before
    refusing. Refusal eventually came; user-simulator did not accept the
    multi-tool workaround chain.
  - `hallucination_11/trial2`: removed_part is a *return field*
    (`fog_lights`) of `get_exterior_lights_status`. Tool returned
    `"fog_lights": "unknown"`. Agent ignored "unknown" and turned on high
    beams anyway. Our prompt does not handle degraded return data.
  - `disambiguation_9/trial0`: ambiguous "Turn on the beams" — context note
    says low-beam is already on, so high-beam is intended. Trials 1+2
    inferred correctly; trial 0 asked the user. Reasoning variance at
    temperature 0.
**Related:** MODIFICATIONS 2026-05-28 07:15 (scenario), 06:45 (prompt),
IDEAS.md → 4 new entries added below this run.

## 2026-05-28 07:15 — Add scaled leaderboard-comparison scenario (local_test_set_jg.toml)
**Author:** Claude (at user's request)
**Files:**
  - `scenarios/track_1_agent_under_test/local_test_set_jg.toml` (created)
**Change:** New scenario file targeting a tractable Pass^3 measurement against
the public test split. 25 tasks total, sampled proportionally to the full test
distribution (10 base / 10 hallucination / 5 disambiguation; full split is
100/98/56). 3 trials per task → Pass^3 is computable. Model is
`gemini/gemini-3.5-flash` at temperature 0.0, with our expanded `SYSTEM_PROMPT`
from the 2026-05-28 06:45 entry.
**Why:** The 2026-05-28 07:02 smoke (6 tasks) hit 100%, but 6 tasks are way too
small to compare against the leaderboard. Full test set (254 tasks × 3 trials
≈ 8h) is the gold standard but too expensive for a first iteration. 25 tasks
× 3 trials is a sweet spot (~45–60 min) that gives all four reported scores
(Avg Pass^3 + 3 per-split Pass^3) with non-trivial sample size on the two
larger splits. Disambiguation will be statistically thin (5 tasks → values in
multiples of 0.2) — known tradeoff for this iteration.
**Target baseline (leaderboard, full test set):** Gemini 2.5 Flash —
Avg Pass^3 .41, Base .59, Hall .41, Disamb .22. Our run swaps the model and
adds prompt harnessing, so a beat-or-miss tells us if either lever is worth
keeping.
**Result:** Not yet run. Awaiting user instruction.
**Related:** [IDEAS.md → `local_test_set.toml` Lauf nach jedem nicht-trivialen
Prompt-Change], prior smoke 2026-05-28 07:02.

## 2026-05-28 07:02 — 6-task smoke after SYSTEM_PROMPT expansion (validation)
**Author:** user (ran via `uv run car-bench-run`)
**Files:** none new — used existing `local_smoke_jg.toml` widened to 2 tasks
per split (`tasks_base_num_tasks=2`, etc.). Note: the scenario file on disk
still shows the original 1-per-split config; the user appears to have invoked
the run with overrides or edited and reverted. The result filename encodes
`base2-hall2-dis2`.
**Change:** Smoke validation of the 06:45 prompt change.
**Why:** Verify the expanded `SYSTEM_PROMPT` doesn't regress the two passing
tasks and ideally recovers the hallucination one.
**Result:** **Pass rate 100.0% (6/6)**, wall time 229.7s. All three splits
green: base 2/2, hallucination 2/2, disambiguation 2/2. Output file:
`output/track_1_agent_under_test/20260528-070211__track_1_agent_under_test-local_smoke_jg__train-trials1-base2-hall2-dis2__gemini-gemini-3.5-flash.json`.
Notable: `hallucination_0` trajectory shrank from 10 turns to 6 — the agent
now refuses cleanly instead of fabricating. `disambiguation_0` still shows the
planning-tool retry storm (31-turn trajectory) but reward is 1. Caveat: 6
tasks is far too small to claim the prompt change works in general — see the
07:15 entry for the proper measurement plan.
**Related:** [IDEAS.md → System-Prompt aufbohren], [IDEAS.md →
Halluzinations-Guard im System-Prompt], MODIFICATIONS.md 2026-05-28 06:45.

## 2026-05-28 06:45 — Expand SYSTEM_PROMPT with policy-precondition / preference-lookup / hallucination-guard rules
**Author:** Claude (at user's request)
**Files:**
  - `src/track_1_agent_under_test/car_bench_agent.py` (modified)
  - `CLAUDE.md` (modified — corrected the "System prompt" row to reflect the
    composite system-message construction; the previous note that
    `SYSTEM_PROMPT` was "currently minimal" was misleading because the
    constant was actually dead code before this change)
  - `IDEAS.md` (modified — flipped both "System-Prompt aufbohren" and
    "Halluzinations-Guard im System-Prompt" from `proposed` to `in-progress`)
**Change:** Replaced the previously-unused `SYSTEM_PROMPT` constant
(`car_bench_agent.py:37`) with a four-rule supplementary instruction block
covering (1) honor policy preconditions before acting, (2) consult
`user_preferences` before asking the user to clarify, (3) hallucination guard
— never describe actions that were not actually executed and explicitly refuse
when a needed tool is missing, (4) report real outcomes not intended ones. The
constant is now actually consumed: at `car_bench_agent.py:81` the agent
concatenates the evaluator-supplied system prompt with our supplement before
adding the `role: system` message. The evaluator block remains authoritative
and comes first; ours comes second.
**Why:** Implements IDEAS.md entries "System-Prompt aufbohren (Policies +
Preferences + Halluzinations-Guard)" and "Halluzinations-Guard im
System-Prompt". The 2026-05-28 06:17 run with `gemini-3.5-flash` revealed that
the remaining failure (`hallucination_0`) was a soft-hallucination — the agent
recognized the missing sunshade tool partially but improvised a workaround
instead of refusing. The disambiguation pass in that run worked but only after
a planning-tool retry storm. Explicit prompt rules should harden both.
**Result:** Not yet measured — no smoke run executed after this change.
Awaiting user instruction.
**Related:** [IDEAS.md → System-Prompt aufbohren (Policies + Preferences +
Halluzinations-Guard)], [IDEAS.md → Halluzinations-Guard im System-Prompt],
prior baseline 2026-05-28 06:17.

## 2026-05-28 06:30 — Add bookkeeping files (CLAUDE.md, MODIFICATIONS.md, IDEAS.md)
**Author:** Claude (at user's request)
**Files:**
  - `CLAUDE.md` (created)
  - `MODIFICATIONS.md` (created)
  - `IDEAS.md` (created)
**Change:** Established the project-local bookkeeping convention: `CLAUDE.md` as
agent guidance, `MODIFICATIONS.md` as append-only change log, `IDEAS.md` as
improvement backlog. From now on, every code/config/prompt change must be
mirrored in `MODIFICATIONS.md` in the same change set.
**Why:** User wants traceability over what we have tried, so we can avoid
re-running dead ends and can write up the technical report later.
**Result:** N/A (infrastructure only).
**Related:** —

## 2026-05-28 06:17 — Switch smoke scenario model to gemini/gemini-3.5-flash
**Author:** user
**Files:**
  - `scenarios/track_1_agent_under_test/local_smoke_jg.toml` (created, copy of `local_smoke.toml` with model swapped)
**Change:** Copied the stock `local_smoke.toml` and changed the
`[agent_under_test].cmd` line from `--agent-llm gemini/gemini-2.5-flash` to
`--agent-llm gemini/gemini-3.5-flash`. Setting `AGENT_LLM` in `.env` alone had
no effect because the scenario TOML's CLI flag overrides the env var (see
`src/track_1_agent_under_test/server.py:84`).
**Why:** Baseline smoke run with Flash 2.5 scored 0/3; suspected the model was
the dominant bottleneck and wanted to isolate model effect before harnessing
work.
**Result:** Smoke pass rate **0.0% → 66.7%** (base ✓, disambiguation ✓,
hallucination ✗). Output file:
`output/track_1_agent_under_test/20260528-061702__track_1_agent_under_test-local_smoke_my__train-trials1-base1-hall1-dis1__gemini-gemini-3.5-flash.json`.
Hallucination still fails via soft-hallucination: agent recognized missing
sunshade tool but proceeded anyway instead of triggering `HALLUCINATION_ERROR`
end-conversation keyword.
**Related:** [IDEAS.md → Halluzinations-Guard im System-Prompt]

## 2026-05-28 05:58 — Baseline smoke run with stock Track 1 template
**Author:** user
**Files:**
  - none (used stock `scenarios/track_1_agent_under_test/local_smoke.toml`)
**Change:** First evaluation run against the unmodified Track 1 starter agent
(`gemini/gemini-2.5-flash`, temperature 0.0, default minimal system prompt).
**Why:** Establish baseline numbers before any harness/prompt changes.
**Result:** Smoke pass rate **0.0% (0/3)**. Output file:
`output/track_1_agent_under_test/20260528-055830__track_1_agent_under_test-local_smoke__train-trials1-base1-hall1-dis1__gemini-gemini-2.5-flash.json`.
Failure modes per task:
  - `base_0`: skipped `get_weather` → AUT-POL:009 policy violation, `r_policy=0`.
    All other sub-rewards =1.
  - `hallucination_0` (sunshade tool removed): fabricated sunshade opening in
    the user-facing text; never triggered `HALLUCINATION_ERROR`.
  - `disambiguation_0`: asked the user for the sunroof percentage instead of
    using the 50% default from `user_preferences` → `tool_subset_missing` for
    `open_close_sunroof`, end_conversation_keyword `DISAMBIGUATION_ERROR`.
**Related:** —
