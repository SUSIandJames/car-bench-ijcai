"""Server entry point for CAR-bench agent under test."""
import argparse
import sys
from pathlib import Path
import warnings

import uvicorn
from starlette.applications import Starlette

# Suppress Pydantic serialization warnings from litellm types
# These occur because litellm's Message/Choices types don't set all optional fields
warnings.filterwarnings(
    "ignore",
    message=".*Pydantic serializer warnings.*",
    category=UserWarning,
    module="pydantic.main"
)

from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.server.routes import create_jsonrpc_routes, create_agent_card_routes
from a2a.types import AgentCard

from car_bench_agent import CARBenchAgentExecutor

sys.path.insert(0, str(Path(__file__).parent.parent))
from logging_utils import configure_logger
sys.path.pop(0)

logger = configure_logger(role="agent_under_test", context="server")


def prepare_agent_card(url: str) -> AgentCard:
    """Create the agent card for the CAR-bench agent under test."""
    card = AgentCard(
        name="car_bench_agent",
        description="In-car voice assistant agent for CAR-bench evaluation",
        version="1.0.0",
        default_input_modes=["text/plain", "application/json"],
        default_output_modes=["text/plain", "application/json"],
    )

    # A2A 1.0 supported interface.
    iface = card.supported_interfaces.add()
    iface.url = url
    iface.protocol_binding = "JSONRPC"
    iface.protocol_version = "1.0"

    # Capabilities — explicitly declare all
    card.capabilities.streaming = False
    card.capabilities.push_notifications = False
    card.capabilities.extended_agent_card = False

    # Skills
    skill = card.skills.add()
    skill.id = "car_assistant"
    skill.name = "In-Car Voice Assistant"
    skill.description = "Helps drivers with navigation, communication, charging, and other in-car tasks"
    skill.tags.extend(["benchmark", "car-bench", "voice-assistant"])

    return card


def main():
    parser = argparse.ArgumentParser(description="Run the CAR-bench agent (agent under test).")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host to bind the server")
    parser.add_argument("--port", type=int, default=8080, help="Port to bind the server")
    parser.add_argument("--card-url", type=str, help="External URL for the agent card")
    parser.add_argument(
        "--agent-llm",
        type=str,
        default=None,  # Will use env var or fallback
        help="LLM model (can also be set via AGENT_LLM env var)"
    )
    parser.add_argument("--temperature", type=float, default=0.0, help="Temperature for the LLM")
    parser.add_argument("--thinking", action="store_true", help="Enable thinking mode for the LLM")
    parser.add_argument("--reasoning-effort", type=str, default="medium", help="Reasoning effort level for the LLM")
    parser.add_argument("--interleaved-thinking", action="store_true", help="Enable interleaved thinking for the LLM")
    parser.add_argument("--self-consistency-n", type=int, default=None, help="Sample N candidates per turn and vote on the action (1 = off)")
    parser.add_argument("--self-consistency-temp", type=float, default=None, help="Sampling temperature for self-consistency candidates")
    parser.add_argument("--verify", action="store_true", help="(legacy alias for --verify-mode llm)")
    parser.add_argument("--verify-mode", type=str, default=None, choices=["off", "code", "llm"], help="Grounding verification: off | code (instant structural, latency-aware) | llm (always one re-examination call)")
    parser.add_argument("--suppress-tools", type=str, default=None, help="Comma-separated tool names to hide from the LLM (e.g. planning_tool)")
    parser.add_argument("--api-base", type=str, default=None, help="OpenAI-compatible endpoint base URL (e.g. an HF Inference Endpoint /v1). Use with --agent-llm openai/<model>.")
    parser.add_argument("--api-key-env", type=str, default=None, help="Name of the env var holding the API key for --api-base (keeps the token out of the command line/TOML)")
    parser.add_argument("--sanitize-tool-schemas", action="store_true", help="Strip additionalProperties from tool schemas for any provider (needed for strict TGI/vLLM tool parsers)")
    parser.add_argument("--openrouter-provider", type=str, default=None, help="Pin OpenRouter to one backend provider (e.g. DeepInfra) that accepts the full 57-tool schema")
    args = parser.parse_args()

    # Support both command-line args and environment variables
    # Priority: CLI args > env vars > default
    import os
    agent_llm = args.agent_llm or os.getenv("AGENT_LLM", "gemini/gemini-2.5-flash")
    completion_kwargs = {
        "temperature": args.temperature or float(os.getenv("AGENT_TEMPERATURE", 0.0)),
        "thinking": args.thinking or (os.getenv("AGENT_THINKING", "false").lower() == "true"),
        "reasoning_effort": args.reasoning_effort or os.getenv("AGENT_REASONING_EFFORT", "medium"),
        "interleaved_thinking": args.interleaved_thinking or (os.getenv("AGENT_INTERLEAVED_THINKING", "false").lower() == "true"),
        "self_consistency_n": args.self_consistency_n if args.self_consistency_n is not None else int(os.getenv("AGENT_SELF_CONSISTENCY_N", "1")),
        "self_consistency_temp": args.self_consistency_temp if args.self_consistency_temp is not None else float(os.getenv("AGENT_SELF_CONSISTENCY_TEMP", "0.7")),
        "verify_mode": (
            args.verify_mode
            or os.getenv("AGENT_VERIFY_MODE")
            or ("llm" if (args.verify or os.getenv("AGENT_VERIFY", "false").lower() == "true") else "off")
        ),
        "suppress_tools": [
            s.strip() for s in (args.suppress_tools or os.getenv("AGENT_SUPPRESS_TOOLS", "")).split(",") if s.strip()
        ],
        "api_base": args.api_base or os.getenv("AGENT_API_BASE") or None,
        "api_key": (os.getenv(args.api_key_env) if args.api_key_env else os.getenv("AGENT_API_KEY")) or None,
        "sanitize_tool_schemas": args.sanitize_tool_schemas or (os.getenv("AGENT_SANITIZE_TOOL_SCHEMAS", "false").lower() == "true"),
        "openrouter_provider": args.openrouter_provider or os.getenv("AGENT_OPENROUTER_PROVIDER") or None,
    }

    logger.info(
        "Starting CAR-bench agent",
        model=agent_llm,
        temperature=completion_kwargs["temperature"],
        thinking=completion_kwargs["thinking"],
        reasoning_effort=completion_kwargs["reasoning_effort"],
        interleaved_thinking=completion_kwargs["interleaved_thinking"],
        self_consistency_n=completion_kwargs["self_consistency_n"],
        self_consistency_temp=completion_kwargs["self_consistency_temp"],
        verify_mode=completion_kwargs["verify_mode"],
        suppress_tools=completion_kwargs["suppress_tools"],
        api_base=completion_kwargs["api_base"],
        sanitize_tool_schemas=completion_kwargs["sanitize_tool_schemas"],
        openrouter_provider=completion_kwargs["openrouter_provider"],
        host=args.host,
        port=args.port
    )

    card = prepare_agent_card(args.card_url or f"http://{args.host}:{args.port}/")

    request_handler = DefaultRequestHandler(
        agent_executor=CARBenchAgentExecutor(
            model=agent_llm,
            temperature=completion_kwargs["temperature"],
            thinking=completion_kwargs["thinking"],
            reasoning_effort=completion_kwargs["reasoning_effort"],
            interleaved_thinking=completion_kwargs["interleaved_thinking"],
            self_consistency_n=completion_kwargs["self_consistency_n"],
            self_consistency_temp=completion_kwargs["self_consistency_temp"],
            verify_mode=completion_kwargs["verify_mode"],
            suppress_tools=completion_kwargs["suppress_tools"],
            api_base=completion_kwargs["api_base"],
            api_key=completion_kwargs["api_key"],
            sanitize_tool_schemas=completion_kwargs["sanitize_tool_schemas"],
            openrouter_provider=completion_kwargs["openrouter_provider"],
            ),
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )

    routes = create_jsonrpc_routes(request_handler, "/", enable_v0_3_compat=True)
    card_routes = create_agent_card_routes(card)

    app = Starlette(routes=routes + card_routes)

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        timeout_keep_alive=1000,
    )


if __name__ == "__main__":
    main()
