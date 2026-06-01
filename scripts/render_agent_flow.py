#!/usr/bin/env python3
"""Render a human-readable transcript of how the CAR-bench agent is driven.

Reads the faithful prompt dumps written by car_bench_agent.py when
DUMP_PROMPT_DIR is set (one <ctx8>.json per task, each holding the final
{model, thinking, tools, messages} payload), and a matching run output JSON
(to label each dump with its task type / instruction). Writes one readable
.txt per task type.

Usage:
  python scripts/render_agent_flow.py <dump_dir> <run_output.json> <out_dir>
"""
import json
import sys
import textwrap
from pathlib import Path


def first_user_text(messages):
    for m in messages:
        if m.get("role") == "user":
            c = m.get("content")
            if isinstance(c, str):
                return c.strip()
            if isinstance(c, list):
                return " ".join(b.get("text", "") for b in c if isinstance(b, dict)).strip()
    return ""


def sys_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict))
    return str(content)


def wrap(s, width=100, indent=""):
    out = []
    for line in str(s).splitlines() or [""]:
        out.extend(textwrap.wrap(line, width=width) or [""])
    return "\n".join(indent + l for l in out)


def render(dump, task_meta):
    L = []
    msgs = dump.get("messages", [])
    tools = dump.get("tools") or []
    L.append("=" * 100)
    L.append("HOW THE AGENT IS DRIVEN — one full flow")
    L.append("=" * 100)
    if task_meta:
        L.append(f"task_id      : {task_meta.get('task_id')}")
        L.append(f"task_type    : {task_meta.get('task_type')}")
        if task_meta.get("removed_part"):
            L.append(f"removed_part : {task_meta.get('removed_part')}  (capability/parameter the evaluator stripped)")
        if task_meta.get("disambiguation_element_internal"):
            L.append(f"disambig     : {task_meta.get('disambiguation_element_internal')} | {task_meta.get('disambiguation_element_note')}")
        L.append("")
        L.append("user goal (hidden from agent, drives the simulated user):")
        L.append(wrap(task_meta.get("instruction", ""), indent="    "))
        L.append("")
        L.append("persona (simulated user style):")
        L.append(wrap(task_meta.get("persona", ""), indent="    "))
    L.append(f"\nmodel        : {dump.get('model')}")
    if dump.get("thinking"):
        L.append(f"thinking     : {dump.get('thinking')}  output_config={dump.get('output_config')}  reasoning_effort={dump.get('reasoning_effort')}")
    L.append("")

    # ---- System prompt ----
    L.append("#" * 100)
    L.append("# SYSTEM PROMPT  (evaluator policy block + our SYSTEM_PROMPT supplement)")
    L.append("#" * 100)
    sysmsg = next((m for m in msgs if m.get("role") == "system"), None)
    if sysmsg:
        L.append(sys_text(sysmsg.get("content")))
    else:
        L.append("(no system message captured)")
    L.append("")

    # ---- Tools ----
    L.append("#" * 100)
    L.append(f"# TOOLS PROVIDED BY THE EVALUATOR  ({len(tools)} total)")
    L.append("#" * 100)
    names = [t.get("function", {}).get("name", "?") for t in tools]
    L.append(wrap(", ".join(names), indent="  "))
    if tools:
        L.append("\n--- full schema of the first tool as an example ---")
        L.append(json.dumps(tools[0], indent=2))
    L.append("")

    # ---- Conversation flow ----
    L.append("#" * 100)
    L.append("# CONVERSATION FLOW  (turn by turn, as the agent received/produced it)")
    L.append("#" * 100)
    n = 0
    for m in msgs:
        role = m.get("role")
        if role == "system":
            continue
        n += 1
        if role == "user":
            L.append(f"\n[{n}] ── USER (simulated by evaluator) ──")
            L.append(wrap(sys_text(m.get("content")), indent="    "))
        elif role == "assistant":
            L.append(f"\n[{n}] ── AGENT ──")
            if m.get("content"):
                L.append("  text:")
                L.append(wrap(sys_text(m.get("content")), indent="      "))
            for tc in (m.get("tool_calls") or []):
                fn = tc.get("function", {})
                L.append(f"  tool_call: {fn.get('name')}({fn.get('arguments')})")
        elif role == "tool":
            L.append(f"\n[{n}] ── TOOL RESULT ({m.get('name','?')}) [executed by evaluator] ──")
            L.append(wrap(sys_text(m.get("content")), indent="    "))
    return "\n".join(L)


def main():
    dump_dir, run_json, out_dir = sys.argv[1], sys.argv[2], sys.argv[3]
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    run = json.load(open(run_json))
    # map first-user-text -> task meta
    by_user = {}
    for split, tasks in run["final_result"]["detailed_results_by_split"].items():
        for t in tasks:
            tr = t.get("trajectory", [])
            u = next((x.get("content") for x in tr if isinstance(x, dict) and x.get("role") == "user"), "")
            meta = dict(t["task"])
            meta["task_type_split"] = split
            by_user[(u or "").strip()[:80]] = meta

    written = []
    for f in sorted(Path(dump_dir).glob("*.json")):
        dump = json.load(open(f))
        u = first_user_text(dump.get("messages", []))[:80]
        meta = by_user.get(u, {})
        split = meta.get("task_type_split", f.stem)
        text = render(dump, meta)
        outf = out / f"agent_flow_{split}.txt"
        outf.write_text(text)
        written.append(str(outf))
    print("wrote:")
    for w in written:
        print(" ", w)


if __name__ == "__main__":
    main()
