"""
CAR-bench Agent - Agent under test that solves CAR-bench tasks.

This is the agent being tested. It:
1. Receives task descriptions with available tools from the evaluator
2. Decides which tool to call or how to respond
3. Returns responses in the expected JSON format wrapped in <json>...</json> tags
"""
import argparse
import concurrent.futures
import copy
import json
import os
import time
from pathlib import Path
import sys
import uvicorn
from dotenv import load_dotenv

load_dotenv()

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.helpers.proto_helpers import new_message, new_text_part, new_data_part, new_task_from_user_message
from a2a.types import Role, TaskState
from google.protobuf.json_format import MessageToDict
from litellm import completion
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent))
from logging_utils import configure_logger
from tool_call_types import ToolCall, ToolCallsData
from turn_metrics import TURN_METRICS_KEY, PROMPT_TOKENS, COMPLETION_TOKENS, COST, MODEL, THINKING_TOKENS, NUM_LLM_CALLS, AVG_LLM_CALL_TIME_MS, NUM_PASSES
sys.path.pop(0)

logger = configure_logger(role="agent_under_test", context="-")


def _strip_additional_properties(node):
    """Recursively delete every ``additionalProperties`` key from a tool
    schema, in place.

    Ollama's tool-call parser is strict: it expects every value under
    ``properties`` to be a schema object. Some CAR-bench tool schemas (e.g.
    ``calculate_datetime``) place ``additionalProperties`` *inside*
    ``properties`` (malformed — one indentation level too deep), which makes
    Ollama fail with "cannot unmarshal bool into Go struct field
    ...properties of type api.ToolProperty". Hosted providers (Gemini,
    Anthropic) tolerate it. ``additionalProperties`` is advisory for tool
    calling, so we simply remove it everywhere for Ollama."""
    if isinstance(node, dict):
        node.pop("additionalProperties", None)
        for value in node.values():
            _strip_additional_properties(value)
    elif isinstance(node, list):
        for value in node:
            _strip_additional_properties(value)

SYSTEM_PROMPT = """Additional operating rules. The policy and tool list provided
above are authoritative; the rules below supplement them and apply at all times.

1. Honor policy preconditions before acting.
   If a policy or tool description states a precondition for an action
   (for example: check the weather before opening the sunroof; check vehicle
   state before sending a command), call the corresponding precondition tool
   first — even if the user did not ask for it. Skipping a stated precondition
   is a policy violation regardless of whether the final action succeeds.

2. Consult user preferences whenever a preference-relevant value is involved.
   Before any action whose parameters could be governed by preferences —
   numeric settings (sunroof %, fan level), categorical choices (which beams,
   which contact, which route), communication actions (email recipients,
   CC lists), or vehicle-personalization actions (ambient color, climate
   targets) — read the relevant entry in `user_preferences`, or call
   `get_user_preferences` if available, BEFORE acting. Apply the preference
   value if one exists. Only ask the user to clarify if preferences do not
   resolve the ambiguity.

3. Never fabricate tool calls or their effects (hallucination guard).
   Only describe actions that were actually executed via a tool call in this
   conversation. If a tool you would need is not in the provided tools list,
   do NOT improvise a workaround, do NOT claim the action happened "in
   parallel" or "as part of" another tool, and do NOT silently drop it. Instead,
   tell the user explicitly that this specific capability is unavailable in the
   current system, and stop attempting the unsupported step.

4. Report what actually happened, not what you intended.
   After tool calls, summarize the real outcome based on the tool results. If a
   step failed, was skipped, or was unavailable, say so plainly to the user
   instead of glossing over it. Your final user-facing message must be
   consistent with the last tool results (e.g. if the destination is Munich,
   do not refer to it as Milan in the summary).

5. Treat "unknown" tool-result fields as missing information, never as defaults.
   If a tool returns a field with the literal value `"unknown"` (or null /
   missing for a field that should be present), that field is unavailable
   information, not a default. Do not invent a substitute value, do not derive
   one from a related field, and do not act on a policy or computation that
   depends on that field. Either ask the user for the value, or tell the user
   that the precondition cannot be verified and refuse the dependent action.

6. Do not pass parameters that are not in a tool's schema.
   Inspect each tool's parameter schema before calling it. If the user
   requests setting a value via a parameter that the tool does not expose
   (e.g. the user wants to set a specific `level` but `level` is absent from
   the schema), do NOT pass the parameter, do NOT silently call the tool
   without it and report success for the unset value, and do NOT claim you
   set it. Tell the user that this specific control is not available in the
   current system.

7. Do not substitute a missing tool with a hand-calculation from other tools.
   If the user asks for a result that requires a specific named tool, and
   that tool is not in the provided tools list, do NOT call related tools
   and compute the answer yourself by multiplying / adding / interpolating
   their outputs. Refuse the specific computation and state that the
   required tool is unavailable. (Example: if `get_distance_by_soc` is
   absent, do not call `get_charging_specs_and_status` and multiply range
   by SoC fraction.)
"""


class CARBenchAgentExecutor(AgentExecutor):
    """Executor for the CAR-bench agent under test using native tool calling."""

    def __init__(self, model: str, temperature: float = 0.0, thinking: bool = False, reasoning_effort: str = "medium", interleaved_thinking: bool = False,
                 self_consistency_n: int = 1, self_consistency_temp: float = 0.7, verify_mode: str = "off",
                 suppress_tools=None, api_base=None, api_key=None, sanitize_tool_schemas: bool = False,
                 openrouter_provider=None):
        self.model = model
        self.temperature = temperature
        self.thinking = thinking
        self.reasoning_effort = reasoning_effort  # Can be 'none', 'disable', 'low', 'medium', 'high', or integer token budget
        self.interleaved_thinking = interleaved_thinking  # Whether to use interleaved thinking
        # Self-consistency (#1): sample N candidates per turn (temp>0, run
        # concurrently) and pick the majority action.
        # Verify mode (#2 / #6): "off" = none; "llm" = always one LLM
        # re-examination pass; "code" = instant deterministic grounding check
        # that only spends a corrective LLM call when it flags a problem
        # (latency-aware, deployment-faithful). Defaults off → single call.
        self.self_consistency_n = max(1, self_consistency_n)
        self.self_consistency_temp = self_consistency_temp
        self.verify_mode = verify_mode if verify_mode in ("off", "code", "llm") else "off"
        # Tool names to hide from our LLM (e.g. the optional `planning_tool`,
        # whose malformed-schema retry storms hurt reliability). The evaluator
        # still provides them; we simply choose not to expose them — a harness
        # decision, not a benchmark-state inspection.
        self.suppress_tools = set(suppress_tools or [])
        # OpenAI-compatible custom endpoint (e.g. an HF Inference Endpoint
        # serving via TGI/vLLM). When api_base is set, the completion call is
        # routed there with api_key. All None/False by default → no effect on
        # the existing Gemini/Anthropic/Ollama paths.
        self.api_base = api_base
        self.api_key = api_key
        # Strip `additionalProperties` from tool schemas regardless of provider
        # (TGI's tool parser, like Ollama's, can reject the malformed in-CAR-bench
        # placement). Off by default.
        self.sanitize_tool_schemas = sanitize_tool_schemas
        # Pin OpenRouter routing to one backend provider (e.g. "DeepInfra") so
        # we always hit one that accepts the full 57-tool schema. None = off.
        self.openrouter_provider = openrouter_provider
        self.ctx_id_to_messages: dict[str, list[dict]] = {}
        self.ctx_id_to_tools: dict[str, list[dict]] = {}
        # Per-context turn metrics accumulation (reset when final response is sent)
        self.ctx_id_to_turn_metrics: dict[str, dict] = {}

    def _ensure_turn_metrics(self, context):
        if context.context_id not in self.ctx_id_to_turn_metrics:
            self.ctx_id_to_turn_metrics[context.context_id] = {
                PROMPT_TOKENS: 0,
                COMPLETION_TOKENS: 0,
                THINKING_TOKENS: 0,
                COST: 0.0,
                NUM_LLM_CALLS: 0,
                "_total_llm_time_ms": 0.0,
            }
        return self.ctx_id_to_turn_metrics[context.context_id]

    @staticmethod
    def _raw_completion(messages, completion_kwargs):
        """A single blocking completion call (thread-safe; touches no shared
        state) → (response, elapsed_ms). Used for concurrent candidates."""
        start = time.perf_counter()
        response = completion(messages=messages, **completion_kwargs)
        return response, (time.perf_counter() - start) * 1000.0

    def _accumulate(self, response, elapsed_ms, context, ctx_logger):
        """Fold one response's usage into the per-context turn metrics
        (main thread only — not thread-safe)."""
        turn_m = self._ensure_turn_metrics(context)
        usage = getattr(response, "usage", None)
        if usage:
            turn_m[PROMPT_TOKENS] += getattr(usage, "prompt_tokens", 0) or 0
            turn_m[COMPLETION_TOKENS] += getattr(usage, "completion_tokens", 0) or 0
            details = getattr(usage, "completion_tokens_details", None)
            if details:
                turn_m[THINKING_TOKENS] += getattr(details, "reasoning_tokens", 0) or 0
            cache_creation = getattr(usage, "cache_creation_input_tokens", 0) or 0
            cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
            if cache_creation or cache_read:
                ctx_logger.info(
                    f"Prompt cache usage: creation={cache_creation} read={cache_read}",
                    cache_creation_tokens=cache_creation,
                    cache_read_tokens=cache_read,
                )
        turn_m[COST] += getattr(response, "_hidden_params", {}).get("response_cost", 0.0) or 0.0
        turn_m[NUM_LLM_CALLS] += 1
        turn_m["_total_llm_time_ms"] += elapsed_ms

    def _invoke_llm(self, messages, completion_kwargs, context, ctx_logger):
        """Make ONE completion call and accumulate metrics (sequential path).
        Metrics dict is created before the call so a failure still leaves it
        for the caller's except path to pop."""
        self._ensure_turn_metrics(context)
        response, elapsed_ms = self._raw_completion(messages, completion_kwargs)
        self._accumulate(response, elapsed_ms, context, ctx_logger)
        return response

    @staticmethod
    def _response_signature(response):
        """Action-shape signature for self-consistency voting: a turn either
        emits a specific set of tool calls or it is a text reply. We vote on
        that consequential decision (act-vs-ask and which tools), not on exact
        wording."""
        ac = response.choices[0].message.model_dump(exclude_unset=True)
        tcs = ac.get("tool_calls")
        if tcs:
            sig = []
            for tc in tcs:
                fn = tc.get("function", {})
                args = fn.get("arguments")
                try:
                    norm = json.dumps(json.loads(args), sort_keys=True)
                except Exception:
                    norm = str(args)
                sig.append((fn.get("name"), norm))
            return ("tools", tuple(sorted(sig)))
        return ("text",)

    def _vote(self, candidates, ctx_logger):
        """Pick the candidate whose action shape is the majority (#1)."""
        from collections import Counter
        sigs = [self._response_signature(c) for c in candidates]
        counts = Counter(sigs)
        winner, votes = counts.most_common(1)[0]
        ctx_logger.info(
            "Self-consistency vote",
            n=len(candidates),
            winner_kind=winner[0],
            winner_votes=votes,
            distinct=len(counts),
        )
        for c, s in zip(candidates, sigs):
            if s == winner:
                return c
        return candidates[0]

    def _verify_and_revise(self, messages, completion_kwargs, response, context, ctx_logger):
        """Grounding self-verification pass (#2). Shows the model its own draft
        and asks it to re-examine for grounding errors, then emit the final
        reply. This checks the agent's response for INTERNAL consistency and
        grounding in the provided tool results/tools — it does NOT reference or
        simulate the evaluator's scoring metrics (which would be prohibited
        iterative repair)."""
        ac = response.choices[0].message.model_dump(exclude_unset=True)
        draft_text = ac.get("content") or "(no text)"
        tcs = ac.get("tool_calls") or []
        if tcs:
            draft_actions = "; ".join(
                f"{tc.get('function', {}).get('name')}({tc.get('function', {}).get('arguments')})"
                for tc in tcs
            )
        else:
            draft_actions = "(no tool calls)"
        check = (
            "INTERNAL SELF-CHECK (not shown to the user). You are about to reply with:\n"
            f"- text: {draft_text}\n"
            f"- tool calls: {draft_actions}\n\n"
            "Re-examine this draft for grounding errors, then output your FINAL reply "
            "(text and/or tool calls) for this turn. Apply these checks:\n"
            "1. If your reply states or implies an action was performed, you MUST include the "
            "matching tool call in this same reply. Deciding to act is not acting.\n"
            "2. Every concrete value you state must come from a tool result in this conversation; "
            "do not invent values.\n"
            "3. Treat any tool-result field equal to \"unknown\" (or missing) as unavailable; do not "
            "substitute it or derive it from other fields.\n"
            "4. Only call tools and parameters that exist in the provided tools list; if a needed one "
            "is unavailable, tell the user it is unavailable instead of acting.\n"
            "5. If the request was ambiguous, make sure you resolved it from preferences/context "
            "(or by asking the user) before acting.\n"
            "Output only your corrected final reply."
        )
        # Avoid two consecutive user turns: fold into the last user message if present.
        if messages and messages[-1].get("role") == "user":
            merged = {"role": "user", "content": (messages[-1].get("content") or "") + "\n\n" + check}
            verify_messages = messages[:-1] + [merged]
        else:
            verify_messages = messages + [{"role": "user", "content": check}]
        revised = self._invoke_llm(verify_messages, completion_kwargs, context, ctx_logger)
        ctx_logger.info("Grounding verify pass applied")
        return revised

    @staticmethod
    def _structural_issues(response, tools):
        """Deterministic, instant grounding checks (no LLM). Returns a list of
        human-readable issues. (a)/(b) are exact (zero false positives);
        (c) is a conservative premature-closure heuristic."""
        ac = response.choices[0].message.model_dump(exclude_unset=True)
        tcs = ac.get("tool_calls") or []
        content = ac.get("content")
        issues = []
        # Build {tool_name -> set(parameter names)} from the provided schemas.
        toolmap = {}
        for t in (tools or []):
            fn = t.get("function", {}) if isinstance(t, dict) else {}
            params = (fn.get("parameters") or {}).get("properties") or {}
            toolmap[fn.get("name")] = set(params.keys())
        for tc in tcs:
            fn = tc.get("function", {})
            name = fn.get("name")
            if name not in toolmap:
                issues.append(f"tool '{name}' is not in the provided tools list")
                continue
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except Exception:
                args = {}
            unknown = [k for k in (args or {}) if k not in toolmap[name]]
            if unknown:
                issues.append(f"tool '{name}' uses parameter(s) not in its schema: {unknown}")
        # (c) Premature closure: confirmation phrasing but no tool call this turn.
        if content and not tcs:
            low = content.lower()
            claim_words = (
                "done!", "all set", "i've ", "i have ", "i'm setting", "i am setting",
                "fan's on", "is now on", "is now off", "is now set", "is now open",
                "erledigt", "ist eingestellt", "ist jetzt", "habe ich",
            )
            if any(w in low for w in claim_words):
                issues.append("reply claims an action was performed but emits no tool call this turn")
        return issues

    def _code_grounding_check(self, messages, completion_kwargs, response, tools, context, ctx_logger):
        """Latency-aware verify (#6): instant structural check; only spend ONE
        corrective LLM call when it flags a problem. In the common, already-
        correct case it adds zero LLM calls."""
        issues = self._structural_issues(response, tools)
        if not issues:
            return response
        ctx_logger.info("Code grounding check flagged", issues="; ".join(issues))
        check = (
            "INTERNAL CHECK (not shown to the user) found grounding problems with your draft "
            "reply:\n- " + "\n- ".join(issues) + "\n\n"
            "Produce a corrected final reply for this turn:\n"
            "- Only call tools and parameters that exist in the provided tools list. If a needed "
            "tool/parameter is unavailable, tell the user that capability is unavailable instead "
            "of calling it.\n"
            "- If you state or imply an action was performed, you MUST include the matching tool "
            "call in this reply. Deciding to act is not acting.\n"
            "Output only your corrected final reply."
        )
        if messages and messages[-1].get("role") == "user":
            merged = {"role": "user", "content": (messages[-1].get("content") or "") + "\n\n" + check}
            verify_messages = messages[:-1] + [merged]
        else:
            verify_messages = messages + [{"role": "user", "content": check}]
        return self._invoke_llm(verify_messages, completion_kwargs, context, ctx_logger)

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        inbound_message = context.message
        ctx_logger = logger.bind(role="agent_under_test", context=f"ctx:{context.context_id[:8]}")

        # Initialize or get conversation history
        if context.context_id not in self.ctx_id_to_messages:
            self.ctx_id_to_messages[context.context_id] = []

        messages = self.ctx_id_to_messages[context.context_id]
        tools = self.ctx_id_to_tools.get(context.context_id, [])

        # Parse the incoming A2A Message with Parts (now protobuf)
        user_message_text = None
        incoming_tool_results = None  # Structured tool results from evaluator

        try:
            for part in inbound_message.parts:
                content_type = part.WhichOneof("content")
                if content_type == "text":
                    text = part.text
                    # Parse system prompt and user message from formatted text
                    if "System:" in text and "\n\nUser:" in text:
                        # First message with system prompt
                        parts_split = text.split("\n\nUser:", 1)
                        system_prompt = parts_split[0].replace("System:", "").strip()
                        user_message_text = parts_split[1].strip()
                        if not messages:  # Only add system prompt once
                            combined_system_prompt = f"{system_prompt}\n\n{SYSTEM_PROMPT}"
                            messages.append({"role": "system", "content": combined_system_prompt})
                    else:
                        # Regular user message
                        user_message_text = text

                elif content_type == "data":
                    # Extract tools or tool results from data Part
                    data = MessageToDict(part.data)
                    if "tools" in data:
                        tools = data["tools"]
                        if self.suppress_tools:
                            tools = [
                                t for t in tools
                                if t.get("function", {}).get("name") not in self.suppress_tools
                            ]
                        self.ctx_id_to_tools[context.context_id] = tools
                    elif "tool_results" in data:
                        # Structured tool results from the evaluator
                        incoming_tool_results = data["tool_results"]

            # Fallback if no text part and no structured tool results found
            if not user_message_text and not incoming_tool_results:
                user_message_text = context.get_user_input()

            ctx_logger.info(
                "Received user message",
                context_id=context.context_id[:8],
                turn=len(messages) + 1,
                message_preview=(user_message_text[:100] if user_message_text else
                                 f"[{len(incoming_tool_results)} tool results]" if incoming_tool_results else "")
            )
            ctx_logger.debug(
                "Message details",
                context_id=context.context_id[:8],
                message=user_message_text,
                num_parts=len(inbound_message.parts),
                has_tools=bool(tools),
                num_tools=len(tools) if tools else 0,
                has_tool_results=bool(incoming_tool_results),
                num_tool_results=len(incoming_tool_results) if incoming_tool_results else 0
            )

        except Exception as e:
            logger.warning(f"Failed to parse message parts: {e}, using fallback")
            user_message_text = context.get_user_input()

        # Check if previous message had tool calls - if so, format as tool results
        if messages and messages[-1].get("role") == "assistant" and messages[-1].get("tool_calls"):
            prev_tool_calls = messages[-1]["tool_calls"]

            if incoming_tool_results:
                # Structured tool results from evaluator — match each result
                # to its corresponding tool_call_id by tool name
                tool_call_by_name = {}
                for tc in prev_tool_calls:
                    name = tc["function"]["name"]
                    # If multiple calls to the same tool, use a list
                    tool_call_by_name.setdefault(name, []).append(tc)

                tool_results = []
                for tr in incoming_tool_results:
                    tr_name = tr.get("tool_name", "") if isinstance(tr, dict) else tr.get("toolName", "")
                    matching_calls = tool_call_by_name.get(tr_name, [])
                    if matching_calls:
                        # Pop the first matching call to handle duplicate tool names
                        matched_tc = matching_calls.pop(0)
                        tool_results.append({
                            "role": "tool",
                            "tool_call_id": matched_tc["id"],
                            "content": tr.get("content", ""),
                        })
                    else:
                        # Fallback: no matching tool_call found, use first unmatched
                        ctx_logger.warning(
                            "No matching tool_call_id for tool result",
                            tool_name=tr_name,
                        )
                        tool_results.append({
                            "role": "tool",
                            "tool_call_id": tr.get("tool_call_id", tr.get("toolCallId", f"unknown_{tr_name}")),
                            "content": tr.get("content", ""),
                        })
            else:
                # Fallback: no structured tool results, use the text message
                # for all tool calls (legacy behavior)
                tool_results = []
                for tc in prev_tool_calls:
                    tool_results.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": user_message_text or "",
                    })

            # Add all tool result messages
            messages.extend(tool_results)

            ctx_logger.debug(
                "Formatted tool results",
                num_tools=len(tool_results),
                tool_call_ids=[tr["tool_call_id"] for tr in tool_results]
            )
        else:
            # Regular user message
            messages.append({"role": "user", "content": user_message_text})

        # Call LLM with native tool calling
        try:
            # Configure prompt caching. `cache_control` is Anthropic-only
            # semantics; other providers (Gemini, Ollama, …) either ignore it
            # or reject the marker, so only inject it for Anthropic/Claude
            # models. Placement matters: Anthropic/LiteLLM read `cache_control`
            # at the TOOL level (sibling of "type"/"function") and inside a
            # SYSTEM-message content block — not as a top-level message key.
            # This caches the large static prefix (57 tool schemas + system
            # prompt), which is re-sent on every turn. Verified empirically:
            # call 2 returns cache_read_input_tokens > 0. Idempotent across
            # turns. (Guards against empty lists.)
            if "anthropic" in self.model or "claude" in self.model:
                if tools:
                    tools[-1]["cache_control"] = {"type": "ephemeral"}
                if messages and messages[0].get("role") == "system":
                    sys_content = messages[0].get("content")
                    if isinstance(sys_content, str):
                        messages[0]["content"] = [
                            {
                                "type": "text",
                                "text": sys_content,
                                "cache_control": {"type": "ephemeral"},
                            }
                        ]
                    elif isinstance(sys_content, list) and sys_content:
                        # already in block form — ensure the last block is cached
                        if isinstance(sys_content[-1], dict):
                            sys_content[-1]["cache_control"] = {"type": "ephemeral"}

            send_tools = tools if tools else None
            # Ollama's tool-schema parser rejects `additionalProperties`
            # (and chokes on the malformed in-`properties` placement in some
            # CAR-bench schemas). Strip it for Ollama, on a deep copy so the
            # stored tool definitions stay intact.
            if send_tools and ("ollama" in self.model or self.sanitize_tool_schemas):
                send_tools = copy.deepcopy(send_tools)
                for _tool in send_tools:
                    _strip_additional_properties(_tool)

            completion_kwargs = {
                "model": self.model,
                "tools": send_tools,
            }
            # Route to an OpenAI-compatible custom endpoint when configured
            # (HF Inference Endpoint / TGI / vLLM). No-op otherwise.
            if self.api_base:
                completion_kwargs["api_base"] = self.api_base
            if self.api_key:
                completion_kwargs["api_key"] = self.api_key
            # Pin OpenRouter to a specific backend provider (some providers cap
            # tool definitions at 20; CAR-bench needs all 57). allow_fallbacks
            # off so it never silently routes to a capped provider. Also enable
            # LiteLLM retries to ride out transient 429s. No-op when unset.
            if self.openrouter_provider:
                # Comma-separated list → restrict routing to exactly these
                # providers (all must accept the full 57-tool schema) and fall
                # through them in order on rate-limit/error. allow_fallbacks off
                # = never route outside this verified-good set.
                _provs = [p.strip() for p in self.openrouter_provider.split(",") if p.strip()]
                completion_kwargs["extra_body"] = {
                    "provider": {"order": _provs, "allow_fallbacks": False}
                }
                completion_kwargs["num_retries"] = 4
            # Some newer models (e.g. Anthropic Opus 4.8) reject `temperature`
            # entirely ("temperature is deprecated for this model"). Only send
            # it for models that still accept it.
            TEMPERATURE_UNSUPPORTED = ("opus-4-8",)
            if not any(m in self.model for m in TEMPERATURE_UNSUPPORTED):
                completion_kwargs["temperature"] = self.temperature

            # Configure reasoning effort / thinking
            if self.thinking:
                    if "opus-4-8" in self.model:
                        # Opus 4.8 rejects both `reasoning_effort` and
                        # `thinking.type.enabled`. It uses adaptive thinking
                        # plus `output_config.effort` (low/medium/high).
                        # LiteLLM's registry doesn't know opus-4-8 supports
                        # these, so they must be allow-listed explicitly.
                        effort = self.reasoning_effort if self.reasoning_effort in (
                            "low", "medium", "high"
                        ) else "medium"
                        completion_kwargs["thinking"] = {"type": "adaptive"}
                        completion_kwargs["output_config"] = {"effort": effort}
                        completion_kwargs["allowed_openai_params"] = [
                            "thinking", "output_config"
                        ]
                    elif self.model == "claude-opus-4-6":
                        completion_kwargs["thinking"] = {
                            "type": "adaptive"
                        }
                    else:
                        if self.reasoning_effort in [
                            "none",
                            "disable",
                            "low",
                            "medium",
                            "high",
                        ]:
                            completion_kwargs["reasoning_effort"] = self.reasoning_effort
                        else:
                            try:
                                thinking_budget = int(self.reasoning_effort)
                            except ValueError:
                                raise ValueError(
                                    "reasoning_effort must be 'none', 'disable', 'low', 'medium', 'high', or an integer value"
                                )
                            completion_kwargs["thinking"] = {
                                "type": "enabled",
                                "budget_tokens": thinking_budget,
                            }
                        if self.interleaved_thinking:
                            completion_kwargs["extra_headers"] = {
                                    "anthropic-beta": "interleaved-thinking-2025-05-14"
                                }


            # Optional faithful prompt capture: when DUMP_PROMPT_DIR is set,
            # write the exact outbound payload (system + tools + full message
            # history) for this context, overwriting each turn so the file
            # ends as the complete conversation. Off by default.
            dump_dir = os.getenv("DUMP_PROMPT_DIR")
            if dump_dir:
                try:
                    os.makedirs(dump_dir, exist_ok=True)
                    dump_payload = {
                        "model": completion_kwargs.get("model"),
                        "thinking": completion_kwargs.get("thinking"),
                        "output_config": completion_kwargs.get("output_config"),
                        "reasoning_effort": completion_kwargs.get("reasoning_effort"),
                        "tools": completion_kwargs.get("tools"),
                        "messages": messages,
                    }
                    with open(os.path.join(dump_dir, f"{context.context_id[:8]}.json"), "w") as _f:
                        json.dump(dump_payload, _f, indent=2, default=str)
                except Exception:
                    pass

            # --- Generate the response, optionally with self-consistency
            #     voting (#1) and a grounding self-verification pass (#2).
            #     Both default off (n=1, verify=False) → single call as before.
            n = self.self_consistency_n
            if n > 1:
                cand_kwargs = dict(completion_kwargs)
                # Diversity needs temperature > 0; only set it for models that
                # accept `temperature` (Opus 4.8 rejects it, so it isn't in
                # completion_kwargs there — voting then relies on sampling noise).
                if "temperature" in cand_kwargs:
                    cand_kwargs["temperature"] = self.self_consistency_temp
                # Run candidates CONCURRENTLY (#6): per-turn wall time ≈ the
                # slowest call instead of the sum. completion() is blocking I/O,
                # so threads parallelize it well; metrics are accumulated after.
                self._ensure_turn_metrics(context)
                with concurrent.futures.ThreadPoolExecutor(max_workers=n) as ex:
                    results = list(ex.map(
                        lambda _: self._raw_completion(messages, cand_kwargs),
                        range(n),
                    ))
                for resp, elapsed_ms in results:
                    self._accumulate(resp, elapsed_ms, context, ctx_logger)
                candidates = [resp for resp, _ in results]
                response = self._vote(candidates, ctx_logger)
            else:
                response = self._invoke_llm(messages, completion_kwargs, context, ctx_logger)

            if self.verify_mode == "llm":
                response = self._verify_and_revise(
                    messages, completion_kwargs, response, context, ctx_logger
                )
            elif self.verify_mode == "code":
                response = self._code_grounding_check(
                    messages, completion_kwargs, response, tools, context, ctx_logger
                )

            # Get the message from LLM
            llm_message = response.choices[0].message
            assistant_content = llm_message.model_dump(exclude_unset=True)

            # Extract tool calls from assistant content
            tool_calls = assistant_content.get("tool_calls")

            ctx_logger.info(
                "LLM response received",
                has_tool_calls=bool(tool_calls),
                num_tool_calls=len(tool_calls) if tool_calls else 0,
                has_content=bool(assistant_content.get("content")),
                content_length=len(assistant_content.get("content") or ""),
                has_thinking=bool(assistant_content.get("thinking_blocks") or assistant_content.get("reasoning_content"))
            )
            ctx_logger.debug(
                "LLM response details",
                context_id=context.context_id[:8],
                content=assistant_content.get("content"),
                tool_calls=[{"name": tc["function"]["name"], "args": tc["function"]["arguments"]} for tc in tool_calls] if tool_calls else None,
                reasoning_content=assistant_content.get("reasoning_content")
            )

            # Build proper A2A Message with Parts (protobuf)
            parts = []

            # Add text Part if there's content
            if assistant_content.get("content"):
                parts.append(new_text_part(assistant_content["content"]))

            # Add data Part if there are tool calls
            if assistant_content.get("tool_calls"):
                tool_calls_list = [
                    ToolCall(
                        tool_name=tc["function"]["name"],
                        arguments=json.loads(tc["function"]["arguments"]),
                    )
                    for tc in assistant_content["tool_calls"]
                ]
                tool_calls_data = ToolCallsData(tool_calls=tool_calls_list)
                parts.append(new_data_part(tool_calls_data.model_dump()))

            # Add reasoning_content as data Part for debugging (if present)
            if assistant_content.get("reasoning_content"):
                parts.append(new_data_part({"reasoning_content": assistant_content["reasoning_content"]}))

            # If no parts, add empty text
            if not parts:
                parts.append(new_text_part(assistant_content.get("content", "")))

            ctx_logger.debug(
                "Sending response",
                context_id=context.context_id[:8],
                num_parts=len(parts),
            )

        except Exception as e:
            logger.error(f"LLM error: {e}")
            # Error response as Parts
            parts = [new_text_part(f"Error processing request: {str(e)}")]
            # Create a simple assistant_content for error case
            assistant_content = {"content": f"Error processing request: {str(e)}"}

        # Add to history - preserve complete assistant message including thinking blocks
        # Store the full assistant_content to preserve thinking blocks and reasoning_content
        assistant_message_for_history = {
            "role": "assistant",
            "content": assistant_content.get("content"),
        }

        # Preserve tool calls in proper format for LLM API
        if assistant_content.get("tool_calls"):
            assistant_message_for_history["tool_calls"] = assistant_content["tool_calls"]

        # Preserve thinking blocks and reasoning content for Claude extended thinking
        if assistant_content.get("thinking_blocks"):
            assistant_message_for_history["thinking_blocks"] = assistant_content["thinking_blocks"]
        if assistant_content.get("reasoning_content"):
            assistant_message_for_history["reasoning_content"] = assistant_content["reasoning_content"]

        messages.append(assistant_message_for_history)

        # Always return a Message — the agent under test is a conversational participant
        # in a multi-turn exchange. The evaluator decides when the task is done.
        response_message = new_message(
            parts=parts,
            context_id=context.context_id,
            role=Role.ROLE_AGENT,
        )

        # Attach turn_metrics on final response (no tool calls = turn complete)
        has_tool_calls = bool(assistant_content.get("tool_calls"))
        if not has_tool_calls and context.context_id in self.ctx_id_to_turn_metrics:
            turn_m = self.ctx_id_to_turn_metrics.pop(context.context_id)
            num_calls = turn_m[NUM_LLM_CALLS]
            avg_time = (turn_m["_total_llm_time_ms"] / num_calls) if num_calls > 0 else 0.0
            metrics_data = {
                PROMPT_TOKENS: turn_m[PROMPT_TOKENS],
                COMPLETION_TOKENS: turn_m[COMPLETION_TOKENS],
                COST: turn_m[COST],
                MODEL: self.model,
                THINKING_TOKENS: turn_m[THINKING_TOKENS],
                NUM_LLM_CALLS: num_calls,
                AVG_LLM_CALL_TIME_MS: round(avg_time, 1),
                NUM_PASSES: 1,
            }
            response_message.metadata.update({TURN_METRICS_KEY: metrics_data})
            ctx_logger.info(
                "Attached turn_metrics to final response",
                num_llm_calls=num_calls,
                avg_llm_call_time_ms=round(avg_time, 1),
                prompt_tokens=turn_m[PROMPT_TOKENS],
                completion_tokens=turn_m[COMPLETION_TOKENS],
            )

        await event_queue.enqueue_event(response_message)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        """Cancel the current execution."""
        logger.bind(role="agent_under_test", context=f"ctx:{context.context_id[:8]}").info(
            "Canceling context",
            context_id=context.context_id[:8]
        )
        if context.context_id in self.ctx_id_to_messages:
            del self.ctx_id_to_messages[context.context_id]
        if context.context_id in self.ctx_id_to_tools:
            del self.ctx_id_to_tools[context.context_id]
        if context.context_id in self.ctx_id_to_turn_metrics:
            del self.ctx_id_to_turn_metrics[context.context_id]
