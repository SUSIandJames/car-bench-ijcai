# IDEAS.md

Backlog of improvement ideas for the CAR-bench Track 1 agent. Each idea has a
hypothesis, expected effect, and status. Once an idea is attempted, link to
the `MODIFICATIONS.md` entry that captures what we did and what the smoke run
showed.

**Status legend:** proposed · in-progress · tried-worked · tried-failed · dropped

---

## Planning-tool suppression (efficiency win)
**Status:** tried-worked (efficiency, 2026-05-30). Hiding `planning_tool` from
the LLM (`--suppress-tools planning_tool`) eliminated all planning errors
(204→0) and **halved LLM calls + wall time** on the 12-unseen-task experiment
while matching baseline Pass^3 (0.333). The tool is an optional scratchpad
that the agent mis-calls (malformed schema retry storms) — pure cost, no
reliability benefit observed. Keep it suppressed. Reliability impact on a
LARGER held-out set still worth measuring (n=12 too small to claim a Pass^3
gain), but the cost win is unambiguous. NOTE: even baseline reliability on
unseen tasks is only ~0.33 (vs 0.80 on the first-20) — the real headroom is in
capability on hard/unseen tasks, not in shaving the planning tool.

## Reliability harness (rules-compliant levers for Hallucination + Disambiguation)

Context: harnessed Gemini 3.5 Flash (0.80) beats raw Opus 4.8 (0.68 off /
0.72 medium-thinking) on the test split — the *harness* outweighs the base
model. Opus' losses are consistency (Pass@3 0.95), concentrated in
Hallucination and Disambiguation. The levers below are all explicitly allowed
by RULES.md §3 (agentic scaffolding / verification / ensembles / fine-tuning /
RAG) and are **task-agnostic** — they never detect the task type, inspect
hidden state, or simulate the scoring metrics. The hard boundary (RULES.md §4):
verification must check the response's INTERNAL grounding/consistency, never
re-prompt against the evaluator's sub-scores (that is prohibited iterative
repair). Task-scoped thinking effort is OUT (benchmaxxing — branches on task
type).

### #1 Self-consistency voting
**Status:** tried-failed · VORLÄUFIG NICHT ZIELFÜHREND (2026-05-29). On the n=60×3 test split, adding
self-consistency (n=3, T=0.7) + code-verify to the 0.80 config dropped it to
**0.60** (Disambiguation .75→.30). Root cause: self-consistency needs T>0, but
this agent's sweet spot is T=0 (deterministic). T=0.7 candidates add variance
and majority voting then picks the wrong action — exactly on internal
disambiguation, where the deterministic run reliably used the preference. The
implementation is correct; the *technique* is a poor fit for an
already-deterministic, well-tuned agent. NOT used. Possible salvage (untested):
very low candidate temperature (e.g. 0.2) or adaptive voting only when the
first sample is low-confidence — but lower priority now.
**Hypothesis:** Pass^3 punishes any single flaky trial. disambiguation_7 was
2/3 purely from flakiness. Sampling N candidates per turn (temp>0) and picking
the majority *action shape* (which tool calls, or act-vs-ask) should convert
flaky 2/3 tasks to 3/3. Generic ensemble method — explicitly allowed.
**Expected effect:** higher Pass^3 via consistency, especially Disambiguation.
**Cost:** N× inference per turn.
**Tried:** see MODIFICATIONS 2026-05-29 (self_consistency_n flag + _vote()).

### #2 Grounding self-verification pass
**Status:** VORLÄUFIG NICHT ZIELFÜHREND (confounded, parked 2026-05-29). The only
test-split run that used verification also used self-consistency (#1), which
dominated the result with a −0.20 regression — so #2's standalone effect is
unknown (confounded). To evaluate properly, run verify-mode (code or llm) at
T=0 WITHOUT self-consistency vs the 0.80 baseline. The code-verify mechanism
works (fires selectively, ~18% of turns in smoke) and is latency-cheap; its
reliability effect just isn't isolated yet. See #6.
**Hypothesis:** A single self-check before finalizing each turn catches the
observed failure modes directly: claiming an action without emitting the tool
call (disambiguation_7 premature closure), inventing values, treating
"unknown" as real (hallucination_37), using missing tools/parameters
(hallucination_23/29). The check verifies INTERNAL grounding against the
provided tool results/tools only — NOT the scoring metrics — so it is allowed
"verification", not prohibited repair.
**Expected effect:** fewer hallucination + premature-closure failures.
**Cost:** +1 inference per turn (+1 if it revises).
**Tried:** see MODIFICATIONS 2026-05-29 (--verify flag + _verify_and_revise()).

### #6 Latency-aware variant of #1+#2 (deployment-faithful)
**Status:** VORLÄUFIG NICHT ZIELFÜHREND (parked 2026-05-29). Implemented +
mechanically verified; reliability effect confounded by #1 in the only test run
(which regressed to 0.60 due to #1's T>0 — see #1). Code remains in the agent
but is OFF by default; revisit only via the isolated experiment below.
**Next clean experiment:** code-verify ALONE at T=0 (no self-consistency) vs the
0.80 baseline — i.e. `--self-consistency-n 1 --verify-mode code --temperature 0
--thinking --reasoning-effort medium`. That isolates whether the cheap
structural grounding check helps, holding the deterministic sweet spot.
**Motivation:** #1 (N candidates) + #2 (LLM verify) as-is is unsuitable for a
real-time in-car voice assistant — ~4 sequential LLM calls/turn with thinking
≈ tens of seconds/turn, vs the ~1–2 s a voice UX needs. The *principle*
(verify before confirming/acting — safety-critical in a car) is right; the
*implementation via extra full LLM round-trips* is the problem. Two fixes that
keep reliability while cutting latency, both rules-compliant and task-agnostic:
  - **Parallel candidates:** run the N self-consistency calls concurrently
    (ThreadPoolExecutor) → per-turn wall time ≈ max(call), not sum.
  - **Code-based grounding check** instead of an always-on LLM verify pass:
    a deterministic, instant check that (a) rejects tool calls to tools not in
    the provided list, (b) rejects parameters not in a tool's schema — these
    catch missing-tool / missing-parameter hallucinations with zero false
    positives and zero LLM cost — and (c) a conservative heuristic for
    premature closure (confirmation phrasing with no tool call). Only when the
    check FLAGS something does it spend ONE corrective LLM call; in the common
    (already-correct) case it adds ~0 latency. Verify mode = off | code | llm.
**Expected effect:** most of #2's reliability benefit at a fraction of the
latency/cost; a credible "deployable in real time" story for the technical
report (reliability-vs-latency tradeoff made explicit).
**Risk:** the premature-closure heuristic can false-positive on filler
"done"/"set" phrasing → an occasional unnecessary corrective call (latency,
not incorrectness). Tool/param checks are exact.

### #3 Plan → Gather → Act → Confirm scaffold (DEFERRED)
**Status:** proposed (deferred — revisit after #1+#2 results)
**Hypothesis:** A standing generic pipeline for every request — gather evidence
(preferences, vehicle state, weather) → check capabilities/unknowns → act →
confirm only what tool results show — enforces preference lookup (Disambiguation)
and capability checks (Hallucination) uniformly, without task detection. This
is plan/execution separation (allowed).
**Expected effect:** more deterministic disambiguation + fewer hallucinations.
**Risk:** added latency/turns; may over-gather on trivial requests.

### #4 Fine-tuning on the train split (SFT/DPO) (DEFERRED)
**Status:** proposed (deferred — biggest investment, do after lighter levers)
**Hypothesis:** Teach the disambiguation-priority policy and the
hallucination-guard *into the weights* via DPO on (good vs hallucinated /
over-asking) pairs generated from the 254 train tasks, instead of ever-longer
prompts. Explicitly allowed (fine-tuning on training data). Generalizes best.
**Risk:** infra + time; overfitting to train distribution; must not encode
test answers.

### #5 RAG over policy wiki + preferences (idea, not scheduled)
**Status:** proposed
**Hypothesis:** Retrieve the most relevant policy clauses + matching preference
entries per turn and surface them, instead of carrying the whole 19k-token
prompt every turn. Helps policy compliance + disambiguation priority. Allowed
(RAG over environment data).

---

## Prompt & harnessing

### System-Prompt aufbohren (Policies + Preferences + Halluzinations-Guard)
**Status:** in-progress (implemented 2026-05-28, smoke run pending)
**Where:** `src/track_1_agent_under_test/car_bench_agent.py:37` (one-liner today)
**Hypothesis:** The stock prompt ("You are a helpful car voice assistant.
Follow the policy and tool instructions provided.") leaves the model free to
ignore policy obligations, skip preference lookup, and fabricate tool calls.
Replacing it with explicit rules — *always check the relevant precondition
tools before acting (e.g. weather before sunroof)*; *read `user_preferences`
when a user request has an ambiguous parameter*; *if a required tool is not in
the provided tool list, say so explicitly and do not pretend to execute it* —
should address all three failure modes observed in the 2026-05-28 baseline.
**Expected effect:** Could plausibly recover the hallucination task and
harden base/disambiguation against regressions when we vary the model.
**Risk:** Over-constrained prompts can suppress useful improvisation; needs
smoke + test-set validation.
**Tried:** see MODIFICATIONS.md entry "2026-05-28 06:45 — Expand SYSTEM_PROMPT
with policy-precondition / preference-lookup / hallucination-guard rules".

### Halluzinations-Guard im System-Prompt
**Status:** in-progress (implemented 2026-05-28 as part of the broader prompt expansion, smoke run pending)
**Hypothesis:** In `hallucination_0`, the Flash-3.5 run *partially* recognized
the missing sunshade tool ("I do not have a separate control for it") but then
invented a "would have to open in parallel" workaround and proceeded. A single
sentence like *"If a tool you need is not in the provided tools list, refuse
the action and explain that the capability is unavailable; never describe an
action you did not call as a tool"* should turn that soft-hallucination into a
hard refusal that triggers `HALLUCINATION_ERROR` from the user simulator.
**Expected effect:** +1 task on smoke (hallucination split).
**Risk:** Overzealous refusal could hurt base/disambiguation if the wording
isn't precise.
**Tried:** folded into rule 3 of the expanded `SYSTEM_PROMPT`; see same
MODIFICATIONS.md entry as the prompt-aufbohren idea.

### Halluzinations-Guard auf Missing-Parameter ausdehnen
**Status:** tried-worked (SYSTEM_PROMPT rule 6; `hallucination_29` 0/3 → 3/3 on 17:52 run)
**Hypothesis:** In `hallucination_5/trial0` the removed part was the `level`
*parameter* of `set_fan_speed`, not the whole tool. The agent called the tool
with `level=1` anyway and claimed in its user-facing message that it "set the
fan speed to level one" — triggering
`HALLUCINATION_ERROR_REMOVED_PARAMETER`. Our current rule 3 only mentions
missing *tools*. Extending it to: *"If a parameter is missing from a tool's
schema, do not pass that parameter and do not claim you set it; if you cannot
achieve the user's intent without that parameter, refuse the specific
sub-action and say so."* should catch this case.
**Expected effect:** Hallucination Pass^3 up by maybe one task on the 30-task
sample.
**Risk:** Wording around "parameter not in schema" is delicate — could confuse
the model into refusing legitimate parameters it just didn't think to use.

### Workaround-Hopping unterbinden ("first refusal wins")
**Status:** tried-worked partially (SYSTEM_PROMPT rule 7; `hallucination_23`
0/3 → 3/3 on 17:52 run. However, `hallucination_19` regressed from 1/3 → 2/3
fail — the rule may need narrowing to "no hand-calculation" specifically and
not "no alternative tool exploration in general")
**Hypothesis:** In `hallucination_19/trials 0+2`, the agent recognized that
contact-search-by-name was unavailable but still tried Calendar, Email, and
Navigation-history lookups before finally refusing. Each false-positive
workaround burned turns and ended up generating ambiguous tool errors that the
user-simulator did not accept. Rule 3 needs a sharper edge: *"Once you have
identified that the user's request requires a capability you do not have, do
not search for indirect substitutes via unrelated tools; refuse on the first
turn after detection."*
**Expected effect:** +1 hallucination task; also reduces token/latency cost.
**Risk:** Legitimate alternative tool paths (the user really did just want
*some* contact, any) would be cut off. Needs nuance — limit to cases where
the *specific named capability* is missing, not where alternative paths exist.

### Degradierte Tool-Returns als "unknown" interpretieren
**Status:** tried-worked partially (SYSTEM_PROMPT rule 5; `hallucination_11`
and `_27` recovered to 1/3 pass each on 17:52 run, but `hallucination_37` is
still 0/3 — the rule does not stop the agent from deriving missing values
from related numeric fields. Needs a stronger sub-rule: "do not infer a
missing percentage / ratio / total from related fields like remaining_range".)
**Hypothesis:** In `hallucination_11/trial2`, the removed part was the
`fog_lights` return-field. The tool returned `"fog_lights": "unknown"`, and
the agent silently treated it as off. Policy on high-beams may depend on
fog-light status, so this is a policy-relevant silent assumption. Add a rule:
*"If a tool returns a value of `"unknown"`, treat that field as unavailable
information, not as a default. If a policy depends on that field, inform the
user that the precondition cannot be verified and do not proceed."*
**Expected effect:** +1 hallucination task on this sample.
**Risk:** Might cause over-refusal if multiple optional fields return
`"unknown"` for benign reasons.

### Prompt caching aktivieren (Cost-Lever, kein Score-Lever)
**Status:** tried-worked (for Anthropic, 2026-05-28 21:10). The existing
`cache_control` markers were misplaced (on `tools[-1]["function"]` and as a
top-level message key) so caching never fired. After moving them to the tool
level and into a system content block, a real run logs
`read=19042` per call — the full system+tools prefix served from cache.
Gemini caching is a separate, still-open item (cached_tokens=0 there; Gemini
uses a different caching mechanism in LiteLLM).
**Hypothesis:** The 08:26 run shows `cached_tokens = 0` despite the agent
sending the same system prompt + tool definitions on every turn. Input
dominates cost (6.6M tokens, $9.89). Gemini context caching costs $0.15/M
vs $1.50/M input — a 10× discount on the cached portion. If we can route the
fixed prefix (evaluator-supplied system text + our supplement + tool schemas)
through the cache, we plausibly save 30–60% of the input cost. Need to check
whether LiteLLM's prompt-caching path is wired up for `gemini/*` models in
our setup (`car_bench_agent.py:183` mentions "Configure prompt caching").
**Expected effect:** No reward delta; ~$30–80 saved on the extrapolated
full 254×3 run. More relevant once we go to expensive models.
**Risk:** Cache misconfiguration can quietly increase cost (e.g. by writing
caches that never get hit).

### Stronger context-inference hint for ambiguous numeric/categorical requests
**Status:** tried-mixed (SYSTEM_PROMPT rule 2 widened on 2026-05-28 12:00 to
require preference lookup before *any* preference-relevant action. Fixed
`disambiguation_25` (3/3 pass) but regressed `disambiguation_9` from 1/3 fail
to 3/3 fail — the broadened rule over-fires on already-clear requests. Next
iteration should narrow the trigger back toward "value left unspecified by
the user".)
**Hypothesis:** `disambiguation_9/trial0` failed because the model asked
*"high or low beams?"* even though the context (low beams already on, dawn
driving) implies high beams. Trials 1+2 inferred correctly. A small prompt
addendum like *"Before asking the user to disambiguate between options, check
whether the current vehicle/environment state in the tool results makes the
intent obvious (e.g. if the user asks to "turn on the beams" and low beams
are already on, the user means high beams)."* could harden this.
**Expected effect:** Marginal — reasoning variance at temperature 0 is the
real driver, and prompt nudges only partially fix that. Maybe +1 task across
many runs, not consistently.
**Risk:** Encouraging assumption-making could regress true ambiguities elsewhere.

### Preference-Lookup als Reflex
**Status:** proposed
**Hypothesis:** Flash-3.5 already calls `get_user_preferences` in the
disambiguation task — but only after retrying the planning tool a few times.
Adding "before any vehicle-control action with a numeric parameter, fetch the
relevant `user_preferences` once" to the prompt should make it deterministic
and cheaper.

### Plan-Tool-Schema im Prompt vorgeben
**Status:** proposed
**Hypothesis:** Flash-3.5 fails 4× with `PLANNING_TOOL_ERROR` ("step_dependent_on
must contain only integers", "step index must be an integer") before
succeeding. Echoing the planning tool's JSON schema (especially that
`step_dependent_on` is `list[int]`) in the system prompt should eliminate the
retry storm and the `🔧 Error parsing plan` evaluator warnings.
**Expected effect:** Latency + token cost reduction; no reward change.

### Plan-Tool ganz untersagen
**Status:** proposed
**Alternative to the previous idea.** The agent solved the disambiguation task
*without* needing the planning tool — the plan was eventually created but the
actual sub-actions were independent. If we instruct the prompt to skip the
planning tool, we cut latency and remove an entire failure surface.

---

## Model / inference

### Gemini thinking budget auf MEDIUM explizit setzen
**Status:** tried-worked (17:52 run with `--thinking --reasoning-effort medium`)
**Outcome:** Compounded with the prompt change to deliver +0.10 Avg Pass^3
(0.700 → 0.800). Thinking tokens nearly doubled (518k → 1015k). Cost lever
is real (+$24 / +68%) — useful, but the next escalation to "high" should be
gated on whether the remaining 3 systematic failures and the new regressions
are actually thinking-bound or prompt-bound.
**Hypothesis:** The n=60 run already shows ~500k thinking tokens — Gemini does
some thinking by default for 3.5 Flash, but our agent never passes
`reasoning_effort` to LiteLLM because the `--thinking` CLI flag was off
(`car_bench_agent.py:226` gates it). Explicitly enabling `--thinking
--reasoning-effort medium` forces a defined medium thinking budget. The 8
systematic failures (especially hallucination_37's hallucinated SoC and
disambiguation_31's Munich/Milan contradiction) plausibly reflect
under-thought multi-step reasoning; medium thinking should help.
**Expected effect:** Some hallucination/disambiguation recovery, but also
~+30–50% thinking tokens → +cost. Need to measure on next run.
**Risk:** Higher cost without proportional reward gain. If medium does not
help, escalate to "high" or revert.

### OSS-Modell via Ollama: Qwen3.6 empfohlen (GGUF läuft, MLX schneller)
**Status:** in-progress (scenarios created 2026-05-28 18:30; runs pending)
**Registry-verified facts (2026-05-28 20:00):** All three user-suggested tags
DO exist — an earlier note in this file claiming otherwise was wrong:
  - `qwen3.6:35b-mlx` → registry HTTP 412 "this model requires macOS" =
    EXISTS, MLX (Apple-Silicon) build, macOS-gated. ~22.8 GB.
  - `gemma4:31b-mlx` → 412 "requires macOS" = EXISTS, MLX build.
    (gemma4:latest = 9.2 GB GGUF also exists.)
  - `deepseek-v4-flash:cloud` → HTTP 200 = EXISTS, cloud-hosted.
Locally already pulled: qwen3.6:latest (GGUF, 23 GB, tools+thinking verified),
qwen3.5:latest (6.6 GB), minimax-m2.7:cloud.
**Hypothesis / recommendation:** Qwen3.6 is the best CAR-bench fit because
(a) it advertises native `tools` — the hard requirement; (b) the Qwen3 family
is among the strongest open models for agentic tool use; (c) it is the largest
local option (~35B). On Apple Silicon prefer the **MLX build
`qwen3.6:35b-mlx`** (faster than the GGUF `qwen3.6:latest` already pulled) to
cut the dominant walltime cost of a local n=60×3 run. Verify the MLX build
exposes `tools` via `ollama show` after pulling.
  - `gemma4:31b-mlx`: viable second choice, but Gemma's native tool calling is
    historically weaker than Qwen's → higher malformed-tool-call risk.
  - `deepseek-v4-flash:cloud`: strongest reasoning but NOT local (defeats the
    "runs locally" goal, needs Ollama cloud auth + adds latency).
**Expected effect:** Likely below the Gemini 3.5 Flash harnessed run (0.80)
but a useful $0-cost / fully-local data point, and a strong Track-1 "Best
Innovation" story.
**Risk:** Local 35B inference is slow (hours for n=60×3); some OSS models emit
malformed tool-call JSON that breaks the A2A parse at car_bench_agent.py:356.

### Modellwechsel evaluieren über die Tracks hinweg
**Status:** in-progress (Opus 4.8 + Ollama qwen3.6 scenarios created 2026-05-28 18:30)
**Hypothesis:** Flash-3.5 already jumped us from 0/3 to 2/3 on the smoke set.
Worth a one-shot comparison of Gemini Flash 3.5 vs. Pro 2.5 vs. Anthropic
Haiku 4.5 / Sonnet 4.6 at fixed prompt, so we know the model-vs-harness
tradeoff before locking the submission.
**Risk:** Each run costs quota + time.

### Temperatur > 0 mit Self-Consistency
**Status:** superseded — implemented as "#1 Self-consistency voting" above
(see the Reliability-harness section). Kept for history.

---

## Evaluation / measurement

### `local_test_set.toml` Lauf nach jedem nicht-trivialen Prompt-Change
**Status:** proposed
**Hypothesis:** The 3-task smoke is too small to be a useful regression
signal beyond gross changes. After a prompt or harness change that survives
smoke, we should run the full public test set (254 tasks, 3 trials each, public
split) to get a Pass^3 estimate that approximates the hidden eval.
**Cost:** ~3× the smoke time and quota; budget it.

### Failure-mode dashboard
**Status:** proposed
**Hypothesis:** Each result JSON encodes per-task `reward_info.info` (subscores
like `r_policy`, `r_tool_subset`, `r_user_end_conversation`). A small script
that aggregates which subscores are zero across runs would tell us *which*
reliability dimension to attack next, instead of eyeballing trajectories.

---

### Rule 2 zurückdrehen: Preference-Lookup nur wenn User keinen Wert nennt
**Status:** proposed
**Hypothesis:** The 17:52 run broadened Rule 2 to require preference lookup
before *any* preference-relevant action. It fixed `disambiguation_25` but
regressed `disambiguation_9` (1/3 fail → 3/3 fail), `disambiguation_13`
(0/3 → 1/3), and `disambiguation_39` (0/3 → 1/3). The likely cause is the
agent doing an unnecessary preference lookup on already-explicit user
requests, which adds an extra turn and a chance to mis-parse the result.
Narrowing the rule back toward "when the user leaves a value unspecified"
(but keeping it expanded for CC lists / communication actions where
preferences are commonly silent defaults) should recover the regressions
without losing `disambiguation_25`.

### "Do not derive missing values from related fields" — extend Rule 5
**Status:** proposed
**Hypothesis:** `hallucination_37` is still 0/3 — the agent gets
`state_of_charge: "unknown"` and `remaining_range: "68.0km"` and tells the
user "you are currently at 10% state of charge". Rule 5 says "treat unknown
as missing info" — the agent is *technically* not using `state_of_charge`,
but deriving a percentage from `remaining_range` (a related field) and
presenting it as the missing value. Need an explicit prohibition: "if a
field is unknown, do not derive its value by inverse-computing from other
fields that depend on it".

### Plan-Tool ablation on disambiguation
**Status:** proposed
**Hypothesis:** `disambiguation_31` is still 0/3 and its trajectory shows
multiple `PLANNING_TOOL_ERROR` retries before the actual route work begins.
The agent's "from Andorra to Milan" output inconsistency may stem from
context confusion across many planning-tool failed turns. Either prohibit
the planning tool entirely in the prompt or instruct "stop using the
planning tool after the first two failures on the same turn".

### "Never say done without the matching tool call" prompt rule
**Status:** proposed
**Hypothesis:** The Opus thinking=medium regression on Disambiguation
(0.65→0.50) is caused by *premature closure*: after reasoning out the answer
(e.g. fan level 3 from preferences), the model narrates "Done! Set to level 3"
but never emits the `set_fan_speed` tool call (confirmed in
`disambiguation_7` trial 2: `tool_subset_missing_tools=["set_fan_speed"]`,
`r_actions=0`). A prompt rule — "Never tell the user an action is done unless
you emitted the corresponding tool call in this same turn; deciding to do
something is not doing it" — should bind decision to action. See
`docs/task-anatomy-and-opus-regression.md`.
**Expected effect:** recover the thinking-induced disambiguation flakiness
without losing the Base/Hallucination gains.
**Risk:** interacts with the CAR-bench policy line that says message+tool_call
in the same turn causes the tool call to be ignored — wording must be careful.

### Selective thinking per task shape
**Status:** proposed
**Hypothesis:** Thinking helped Base (→1.00) and Hallucination (.60→.65) but
hurt Disambiguation (.65→.50). If thinking could be enabled only for non-
disambiguation-shaped requests it would net more. Hard part: detecting task
shape without inspecting hidden evaluator state (which is prohibited). Maybe a
cheap heuristic on the user message / tool-result pattern.
**Expected effect:** capture the +Base/+Hall gains while avoiding the −Disamb
loss. Net Avg Pass^3 above both the 0.68 (off) and 0.72 (medium) points.

## Out of scope (do not pursue)

- Hard-coding answers to specific tasks — explicitly prohibited by `RULES.md`.
- Self-evaluating against task-level metrics and re-prompting to repair —
  explicitly prohibited.
- Inspecting hidden evaluator/task state — explicitly prohibited.
