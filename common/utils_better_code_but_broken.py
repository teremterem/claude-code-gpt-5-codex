# pylint: disable=too-many-branches,too-many-locals,too-many-statements,too-many-return-statements
# pylint: disable=too-many-nested-blocks
"""
NOTE: The utilities in this module were mostly vibe-coded without review.
"""
import os
from datetime import UTC, datetime
from typing import Any, Dict, Optional, Union

from litellm import GenericStreamingChunk, ModelResponseStream


class ProxyError(RuntimeError):
    def __init__(self, error: Union[BaseException, str], highlight: Optional[bool] = None):

        final_highlight: bool
        if highlight is None:
            # No value provided, read from env var (default 'True')
            env_val = os.environ.get("PROXY_ERROR_HIGHLIGHT", "True")
            final_highlight = env_val.lower() not in ("false", "0", "no")
        else:
            # Value was provided, use it
            final_highlight = highlight

        if final_highlight:
            # Highlight error messages in red, so the actual problems are
            # easier to spot in long tracebacks
            super().__init__(f"\033[1;31m{error}\033[0m")
        else:
            super().__init__(error)


def env_var_to_bool(value: Optional[str], default: str = "false") -> bool:
    """
    Convert environment variable string to boolean.

    Args:
        value: The environment variable value (or None if not set)
        default: Default value to use if value is None

    Returns:
        True if the value (or default) is a truthy string, False otherwise
    """
    return (value or default).lower() in ("true", "1", "on", "yes", "y")


def generate_timestamp_utc() -> str:
    """
    Generate timestamp in format YYYYmmdd_HHMMSS_fff_fff in UTC.

    An example of how these timestamps are used later:

    `.traces/20251005_140642_180_342_RESPONSE_STREAM.md`
    """
    now = datetime.now(UTC)

    str_repr = now.strftime("%Y%m%d_%H%M%S_%f")
    # Let's separate the milliseconds from the microseconds with an underscore
    # to make it more readable
    return f"{str_repr[:-3]}_{str_repr[-3:]}"


def to_generic_streaming_chunk(chunk: ModelResponseStream) -> GenericStreamingChunk:
    if hasattr(chunk, "model_dump"):
        chunk_data = chunk.model_dump(mode="python")
    else:
        chunk_data = chunk.dict()

    chunk_payload = _build_chunk_payload(chunk_data)
    return GenericStreamingChunk(**chunk_payload)


def _build_chunk_payload(chunk_data: Dict[str, Any]) -> Dict[str, Any]:
    choices_raw = chunk_data.get("choices") or []
    if not isinstance(choices_raw, list):
        choices_raw = [choices_raw]
    choices = [_build_choice(choice) for choice in choices_raw]

    payload: Dict[str, Any] = {
        "id": chunk_data.get("id"),
        "created": chunk_data.get("created"),
        "model": chunk_data.get("model"),
        "object": chunk_data.get("object"),
        "system_fingerprint": chunk_data.get("system_fingerprint"),
        "provider_specific_fields": chunk_data.get("provider_specific_fields"),
        "citations": chunk_data.get("citations"),
        "choices": choices,
    }

    if "usage" in chunk_data:
        payload["usage"] = chunk_data.get("usage")

    return payload


def _build_choice(choice: Dict[str, Any]) -> Dict[str, Any]:
    choice_dict = choice if isinstance(choice, dict) else {}
    delta_dict = _build_delta(choice_dict.get("delta") or {})

    if not delta_dict.get("content"):
        text_fallback = choice_dict.get("text")
        if text_fallback:
            delta_dict["content"] = str(text_fallback)

    return {
        "index": choice_dict.get("index"),
        "delta": delta_dict,
        "finish_reason": choice_dict.get("finish_reason"),
        "logprobs": choice_dict.get("logprobs"),
    }


def _build_delta(delta: Dict[str, Any]) -> Dict[str, Any]:
    delta_dict = delta if isinstance(delta, dict) else {}
    processed: Dict[str, Any] = {}
    collected_tool_calls: list[Dict[str, Any]] = []
    tool_calls_was_none = False

    for key, value in delta_dict.items():
        if key == "tool_calls":
            if value is None:
                tool_calls_was_none = True
            else:
                normalized_tool_calls = _build_tool_calls(value)
                if normalized_tool_calls:
                    collected_tool_calls.extend(normalized_tool_calls)
        elif key == "tool_use":
            anthropic_tool_call = _build_anthropic_tool_use(value)
            if anthropic_tool_call:
                collected_tool_calls.append(anthropic_tool_call)
                processed[key] = anthropic_tool_call
        elif key == "function_call":
            normalized_function_call = _build_function_call(value)
            if normalized_function_call:
                collected_tool_calls.append(_tool_call_from_function_call(normalized_function_call))
                processed[key] = normalized_function_call
        else:
            processed[key] = value

    if collected_tool_calls:
        processed["tool_calls"] = collected_tool_calls
    elif tool_calls_was_none:
        processed["tool_calls"] = None
    elif "tool_calls" in delta_dict:
        processed["tool_calls"] = []

    return processed


def _build_tool_calls(tool_calls: Any) -> Optional[list[Dict[str, Any]]]:
    if tool_calls is None:
        return None
    if not isinstance(tool_calls, list):
        tool_calls = [tool_calls]
    return [_build_tool_call_delta(call or {}) for call in tool_calls]


def _build_tool_call_delta(tool_call: Dict[str, Any]) -> Dict[str, Any]:
    tool_call_dict = tool_call if isinstance(tool_call, dict) else {}
    function_payload = _build_tool_call_function(tool_call_dict)

    index_value = tool_call_dict.get("index")
    try:
        index_normalized = int(index_value) if index_value is not None else 0
    except (TypeError, ValueError):
        index_normalized = 0

    type_value = tool_call_dict.get("type")
    type_normalized = type_value if isinstance(type_value, str) and type_value else "function"

    id_value = tool_call_dict.get("id")
    id_normalized = str(id_value) if id_value is not None and not isinstance(id_value, str) else id_value

    normalized: Dict[str, Any] = {
        "index": index_normalized,
        "id": id_normalized,
        "type": type_normalized,
        "function": function_payload,
    }

    for key, value in tool_call_dict.items():
        if key in ("index", "id", "type", "function"):
            continue
        normalized[key] = value

    return normalized


def _build_tool_call_function(tool_call_dict: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    function_value = tool_call_dict.get("function")
    if function_value is None and {"name", "arguments"} & tool_call_dict.keys():
        function_value = {
            "name": tool_call_dict.get("name"),
            "arguments": tool_call_dict.get("arguments"),
        }

    if function_value is None:
        return None

    if not isinstance(function_value, dict):
        return None

    name_value = function_value.get("name")
    name_normalized = name_value if isinstance(name_value, str) else None

    arguments_value = function_value.get("arguments")
    arguments_normalized = (
        arguments_value if isinstance(arguments_value, str) or arguments_value is None else str(arguments_value)
    )

    normalized_function: Dict[str, Any] = {
        "name": name_normalized,
        "arguments": arguments_normalized,
    }

    for key, value in function_value.items():
        if key in ("name", "arguments"):
            continue
        normalized_function[key] = value

    return normalized_function


def _build_anthropic_tool_use(tool_use: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not tool_use or not isinstance(tool_use, dict):
        return None

    synthetic_tool_call = {
        "index": tool_use.get("index", 0),
        "id": tool_use.get("id"),
        "type": tool_use.get("type", "function"),
        "function": {
            "name": tool_use.get("name"),
            "arguments": tool_use.get("input"),
        },
    }

    return _build_tool_call_delta(synthetic_tool_call)


def _build_function_call(function_call: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not function_call or not isinstance(function_call, dict):
        return None

    arguments_value = function_call.get("arguments")
    arguments_normalized = (
        arguments_value if isinstance(arguments_value, str) or arguments_value is None else str(arguments_value)
    )

    normalized: Dict[str, Any] = {
        "name": function_call.get("name") if isinstance(function_call.get("name"), str) else None,
        "arguments": arguments_normalized,
    }

    for key, value in function_call.items():
        if key in ("name", "arguments"):
            continue
        normalized[key] = value

    return normalized


def _tool_call_from_function_call(function_call: Dict[str, Any]) -> Dict[str, Any]:
    synthetic_tool_call = {
        "index": 0,
        "id": None,
        "type": "function",
        "function": function_call,
    }
    return _build_tool_call_delta(synthetic_tool_call)
