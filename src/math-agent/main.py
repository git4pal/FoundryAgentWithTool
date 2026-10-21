"""MathAgent - a Microsoft Foundry hosted agent that solves arithmetic using function tools.

Every request is forced through tool calling (tool_choice="required"). Requests that cannot
be routed to add / subtract / multiply / divide get FALLBACK_MESSAGE.
"""

import asyncio
import json
import logging
import os
from pathlib import Path

from azure.ai.agentserver.responses import (
    CreateResponse,
    ResponseContext,
    ResponsesAgentServerHost,
    ResponsesServerOptions,
    TextResponse,
)
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

from math_tools import MATH_FUNCTIONS, TOOL_DEFINITIONS

load_dotenv(Path(__file__).with_name(".env"))

logger = logging.getLogger("MathAgent")

AGENT_NAME = "MathAgent"
FALLBACK_MESSAGE = "Sorry could not resolve your request"
MAX_TOOL_ROUNDS = 6
ALLOWED_OUTPUT_TYPES = {"function_call", "message", "reasoning"}

SYSTEM_PROMPT = """You are MathAgent, an arithmetic assistant.
Rules:
1. You MUST use the provided tools for every calculation. Never calculate in your head.
2. Available operations: add, subtract, multiply, divide. Break multi-step expressions into
   individual tool calls and respect standard operator precedence.
3. If the request is not an arithmetic problem solvable with these four operations, call the
   cannot_resolve tool.
4. After you receive the tool results, reply with a short final answer, e.g. "2 + 5 = 7".
"""

_model = os.environ["AZURE_AI_MODEL_DEPLOYMENT_NAME"]
_responses_client = (
    AIProjectClient(
        endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"],
        credential=DefaultAzureCredential(),
    )
    .get_openai_client()
    .responses
)


def _run_tool(name: str, arguments: str) -> dict:
    args = json.loads(arguments or "{}")
    return MATH_FUNCTIONS[name](float(args["a"]), float(args["b"]))


def solve(user_input: str) -> str:
    """Run the model <-> tool loop and return the final answer text."""
    previous_response_id = None
    next_input: list | str = user_input
    used_math_tool = False

    for round_number in range(MAX_TOOL_ROUNDS):
        response = _responses_client.create(
            model=_model,
            instructions=SYSTEM_PROMPT,
            input=next_input,
            tools=TOOL_DEFINITIONS,
            # First turn must be a tool call; later turns may return the final text.
            tool_choice="required" if round_number == 0 else "auto",
            previous_response_id=previous_response_id,
        )

        if any(item.type not in ALLOWED_OUTPUT_TYPES for item in response.output):
            logger.warning("Blocked non-function tool output: %s", [i.type for i in response.output])
            return FALLBACK_MESSAGE

        calls = [item for item in response.output if item.type == "function_call"]
        if not calls:
            return response.output_text if used_math_tool and response.output_text else FALLBACK_MESSAGE

        tool_outputs = []
        for call in calls:
            if call.name not in MATH_FUNCTIONS:
                logger.info("Request not routable to a math tool (tool=%s)", call.name)
                return FALLBACK_MESSAGE
            try:
                result = _run_tool(call.name, call.arguments)
            except (ValueError, KeyError, TypeError, json.JSONDecodeError):
                logger.exception("Invalid arguments for tool %s: %s", call.name, call.arguments)
                return FALLBACK_MESSAGE
            logger.info("Tool %s(%s) -> %s", call.name, call.arguments, result)
            used_math_tool = True
            tool_outputs.append(
                {"type": "function_call_output", "call_id": call.call_id, "output": json.dumps(result)}
            )

        previous_response_id = response.id
        next_input = tool_outputs

    logger.warning("Exceeded %d tool rounds", MAX_TOOL_ROUNDS)
    return FALLBACK_MESSAGE


# configure_observability=None disables the SDK's OpenTelemetry/Azure Monitor setup,
# so console logging is configured here instead.
logging.basicConfig(level=logging.INFO)
app = ResponsesAgentServerHost(
    options=ResponsesServerOptions(),
    configure_observability=None,
)


@app.response_handler
async def handler(
    request: CreateResponse,
    context: ResponseContext,
    _cancellation_signal: asyncio.Event,
):
    user_input = (await context.get_input_text() or "").strip()
    if not user_input:
        return TextResponse(context, request, text=FALLBACK_MESSAGE)

    try:
        answer = await asyncio.get_running_loop().run_in_executor(None, solve, user_input)
    except Exception:
        logger.exception("%s failed to process the request", AGENT_NAME)
        answer = FALLBACK_MESSAGE

    return TextResponse(context, request, text=answer)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app.run()
