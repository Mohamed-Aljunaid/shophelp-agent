"""Build the tool specs the LLM sees ({"name", "description", "parameters"}) from the tool functions."""
import inspect
import typing

from tools.policy import TOOLS

_JSON_TYPES = {str: {"type": "string"}, list[str]: {"type": "array", "items": {"type": "string"}}}


def tool_spec(name: str) -> dict:
    """JSON-schema spec for one tool, from its signature and docstring (the `conn` arg is hidden)."""
    fn = TOOLS[name]
    hints = typing.get_type_hints(fn)
    params = [p for p in inspect.signature(fn).parameters if p != "conn"]
    # shortcut: no per-argument descriptions; add them if the model mixes up ids or formats.
    return {
        "name": name,
        "description": " ".join(inspect.getdoc(fn).split()),
        "parameters": {
            "type": "object",
            "properties": {p: dict(_JSON_TYPES[hints[p]]) for p in params},
            "required": params,
        },
    }


TOOL_SPECS = [tool_spec(name) for name in TOOLS]
