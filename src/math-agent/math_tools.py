"""Arithmetic tools exposed to the model through OpenAI function calling."""

from typing import Callable

Number = int | float


def _normalize(value: float) -> Number:
    return int(value) if float(value).is_integer() else value


def add(a: float, b: float) -> dict:
    return {"result": _normalize(a + b)}


def subtract(a: float, b: float) -> dict:
    return {"result": _normalize(a - b)}


def multiply(a: float, b: float) -> dict:
    return {"result": _normalize(a * b)}


def divide(a: float, b: float) -> dict:
    if b == 0:
        return {"error": "Division by zero is undefined."}
    return {"result": _normalize(a / b)}


MATH_FUNCTIONS: dict[str, Callable[[float, float], dict]] = {
    "add": add,
    "subtract": subtract,
    "multiply": multiply,
    "divide": divide,
}

# Called by the model when the request is not an arithmetic problem.
CANNOT_RESOLVE_TOOL = "cannot_resolve"


def _binary_tool(name: str, description: str) -> dict:
    return {
        "type": "function",
        "name": name,
        "description": description,
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "a": {"type": "number", "description": "First operand."},
                "b": {"type": "number", "description": "Second operand."},
            },
            "required": ["a", "b"],
            "additionalProperties": False,
        },
    }


# Only function tools are declared, so hosted tools such as web_search are never available.
TOOL_DEFINITIONS: list[dict] = [
    _binary_tool("add", "Add two numbers: a + b."),
    _binary_tool("subtract", "Subtract b from a: a - b."),
    _binary_tool("multiply", "Multiply two numbers: a * b."),
    _binary_tool("divide", "Divide a by b: a / b."),
    {
        "type": "function",
        "name": CANNOT_RESOLVE_TOOL,
        "description": (
            "Call this when the user's request is NOT an arithmetic problem that can be "
            "solved with add, subtract, multiply or divide."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    },
]
