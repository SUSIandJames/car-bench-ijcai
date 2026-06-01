# AGENTS.md

Guidance for Codex when working in this repository.

## Project
This is a participant fork for the **CAR-bench Challenge (IJCAI-ECAI 2026)**.
Goal: build a dockerized A2A agent under test that maximizes reliability (Pass^3) on
the CAR-bench in-car voice assistant benchmark. We are participating in **Track 1
(Open Track)**.

Reading order for project context:
- `README.md` — full setup, architecture, submission mechanics
- `RULES.md` — competition rules (eligibility, allowed/prohibited approaches, deadlines)
- `docs/development-guide.md` — A2A turn contract
- `docs/agent-under-test-harnessing.md` — allowed harness boundaries
- `src/track_1_agent_under_test/` — the agent we are iterating on

## Mandatory bookkeeping (read before editing anything)

Two repo-local logs **must** stay in sync with our work. Update them in the same
change set as the code/config change itself; never edit code without also
updating the relevant log.

- **`MODIFICATIONS.md`** — append-only chronological log of every change
  (by the user OR by Codex) to code, scenarios, prompts, configs, dependencies.
  Each entry: timestamp, author (user / Codex), files touched, what changed,
  why, and resulting score delta if measured. Newest entries at the top.
- **`IDEAS.md`** — backlog of improvement ideas (prompt changes, harnessing,
  model choices, evaluation hypotheses). Each idea: a short title, the
  hypothesis, expected effect, status (proposed / in-progress / tried-worked /
  tried-failed / dropped), and a link to the `MODIFICATIONS.md` entry once
  attempted.

These two files are the source of truth for "what have we tried." Do not
duplicate their content into commit messages or other docs.

## Where the moving parts live

| Concern | Path |
|---|---|
| Agent source (Track 1) | `src/track_1_agent_under_test/car_bench_agent.py` |
| Agent server entrypoint | `src/track_1_agent_under_test/server.py` |
| System prompt | Composite: the evaluator sends `System: ...` as the first inbound text part (parsed at `car_bench_agent.py:78`) and our supplementary rules in `SYSTEM_PROMPT` (`car_bench_agent.py:37`) are appended at `car_bench_agent.py:81`. The evaluator block stays authoritative; our block adds policy-precondition, preference-lookup, and hallucination-guard rules. |
| Scenario configs | `scenarios/track_1_agent_under_test/*.toml` |
| Output of evaluations | `output/track_1_agent_under_test/*.json` (one JSON per run) |
| CAR-bench dependency | `third_party/car-bench/` (cloned by `scripts/setup_car_bench.sh`, gitignored) |

## Important configuration mechanics

The Track 1 agent server accepts the LLM via **both** CLI flag and env var. The
priority in `server.py:84` is `--agent-llm` (CLI) > `AGENT_LLM` (env) > default
`gemini/gemini-2.5-flash`. The scenario TOML files put `--agent-llm` directly
into the `[agent_under_test].cmd` string — so editing `.env` alone does NOT
change the model. To change the model, edit the scenario TOML or remove the
flag from `cmd`.

Same pattern for `AGENT_TEMPERATURE`, `AGENT_THINKING`, `AGENT_REASONING_EFFORT`,
`AGENT_INTERLEAVED_THINKING`.

## Eval baseline (so we can measure deltas)

Smoke set: 1 base + 1 hallucination + 1 disambiguation task, train split, 1 trial.

| Run timestamp | Model | Pass rate | Notes |
|---|---|---|---|
| 2026-05-28 05:58 | `gemini/gemini-2.5-flash` | 0.0% (0/3) | All 3 failed: skipped `get_weather` (base, hallucination), hallucinated sunshade action (hallucination), asked user instead of using preference (disambiguation) |
| 2026-05-28 06:17 | `gemini/gemini-3.5-flash` | 66.7% (2/3) | Base ✓, Disambiguation ✓, Hallucination ✗ (soft-hallucination: acknowledged missing tool but proceeded anyway) |

The hallucination split is the hardest for our current agent and the obvious
next target.

## Working style for this repo

- For UI-style smoke tests, the entry is `uv run car-bench-run scenarios/track_1_agent_under_test/<scenario>.toml --show-logs`.
- Outputs land under `output/track_1_agent_under_test/` with filenames that
  encode timestamp, scenario, task selection, and model. Always read the
  newest file when answering "why did the last run look like that."
- Do not run the local `test_set` scenarios without a reason — they are slower
  and burn API quota. Smoke first.
- Never edit `tests/test_scenario_contract.py` casually — the model strings
  there are fixture data, not config.
- Never commit `.env` or anything under `third_party/`.

## When proposing changes

1. Add the idea to `IDEAS.md` first (or update its status if it's already there).
2. Make the code/config change.
3. Append the change to `MODIFICATIONS.md` with the score-delta from a smoke
   run if applicable.
4. Keep code edits scoped — don't bundle prompt experiments with refactors.
