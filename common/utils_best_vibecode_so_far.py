# pylint: disable=too-many-branches,too-many-locals,too-many-statements,too-many-return-statements
# pylint: disable=too-many-nested-blocks
"""
NOTE: The utilities in this module were mostly vibe-coded without review.
"""
import json
import os
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any, Optional, Union

from litellm import GenericStreamingChunk, ModelResponse, ResponsesAPIResponse
import json as _json_for_telemetry


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


# TODO Refactor to avoid using global state if possible
# Minimal state to accumulate Responses function_call arguments across chunks
_RESPONSES_TOOL_STATE: dict[str, dict[str, Any]] = {}
# Track which Responses tool item (by item_id) we have adopted for this turn.
# We only ever emit a single tool_use for the adopted item.
_RESPONSES_TOOL_ADOPTED: Optional[str] = None
_RESPONSES_TOOL_DEBUG = os.environ.get("RESPONSES_TOOL_DEBUG", "0") not in ("0", "", "false", "False")
_RESPONSES_TELEMETRY_ENABLED = os.environ.get("RESPONSES_TOOL_TELEMETRY", "0") not in ("0", "", "false", "False")

_RESPONSES_TELEMETRY: dict[str, Any] = {
    "saw_tool_items": 0,
    "extra_tool_items_ignored": 0,
    "adopted_item_id": None,
    "adopted_output_index": None,
}


def _log_responses_tool(msg: str) -> None:
    if not _RESPONSES_TOOL_DEBUG:
        return
    timestamp = datetime.now(UTC).isoformat()
    print(f"[responses_tool_debug {timestamp}] {msg}")


def _telemetry(event: str, **fields: Any) -> None:
    if not _RESPONSES_TELEMETRY_ENABLED:
        return
    payload = {"event": event, **fields}
    try:
        print(f"[responses_tool_telemetry] {_json_for_telemetry.dumps(payload, ensure_ascii=False)}")
    except Exception:
        print(f"[responses_tool_telemetry] {event} {fields}")


def _maybe_emit_tool(item_id: str, default_index: int = 0) -> Optional[dict[str, Any]]:
    state = _RESPONSES_TOOL_STATE.get(item_id)
    if not state or state.get("emitted"):
        return None
    if not state.get("args_done"):
        return None
    if not state.get("name"):
        return None

    args_str = state.get("args", "")
    if not isinstance(args_str, str):
        args_str = str(args_str)
    final_args = args_str if args_str else "{}"

    tool_use = {
        "index": state.get("index", default_index),
        "id": state.get("id"),
        "type": "function",
        "function": {
            "name": state.get("name"),
            "arguments": final_args,
        },
    }
    _log_responses_tool(f"emitting tool_use item_id={item_id} name={state.get('name')} index={tool_use['index']}")
    state["emitted"] = True
    return tool_use


def responses_eof_finalize_chunk() -> Optional[GenericStreamingChunk]:
    """
    Finalize a pending tool call if the stream ended without a terminal
    event. If we have buffered args for the adopted tool and they parse as
    JSON, emit a single tool_use. Otherwise emit an assistant-visible error.
    Always clears internal tool state.
    """
    try:
        adopted = _RESPONSES_TOOL_ADOPTED
        if not adopted or adopted not in _RESPONSES_TOOL_STATE:
            # Nothing pending
            return None
        state = _RESPONSES_TOOL_STATE.get(adopted, {})
        if state.get("emitted"):
            return None
        args_str = state.get("args", "")
        # Strict JSON parse if non-empty; empty means {} is fine
        if isinstance(args_str, str) and args_str:
            try:
                json.loads(args_str)
                args_ok = True
            except Exception:
                args_ok = False
        else:
            args_ok = True

        if args_ok:
            tool_use = {
                "index": state.get("index", 0),
                "id": state.get("id"),
                "type": "function",
                "function": {
                    "name": state.get("name"),
                    "arguments": args_str or "{}",
                },
            }
            chunk: GenericStreamingChunk = {
                "text": "",
                "is_finished": False,
                "finish_reason": "",
                "usage": None,
                "index": state.get("index", 0),
                "tool_use": tool_use,
                "provider_specific_fields": {"responses_type": "eof_fallback"},
            }
            return chunk
        # Emit an assistant-visible error if args could not be finalized
        err = "Provider ended stream before tool arguments were finalized."
        return {
            "text": err,
            "is_finished": False,
            "finish_reason": "error",
            "usage": None,
            "index": 0,
            "tool_use": None,
            "provider_specific_fields": {"responses_type": "eof_fallback_error"},
        }
    finally:
        # Clear state regardless
        try:
            _RESPONSES_TOOL_STATE.clear()
        except Exception:
            pass
        _RESPONSES_TOOL_ADOPTED = None


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


def to_generic_streaming_chunk(chunk: Any) -> GenericStreamingChunk:
    """
    Best-effort convert a LiteLLM ModelResponseStream chunk into
    GenericStreamingChunk.

    GenericStreamingChunk TypedDict keys:
      - text: str (required)
      - is_finished: bool (required)
      - finish_reason: str (required)
      - usage: Optional[ChatCompletionUsageBlock] (we pass None for incremental
        chunks)
      - index: int (default 0)
      - tool_use: Optional[ChatCompletionToolCallChunk] (default None)
      - provider_specific_fields: Optional[dict]
    """
    # Defaults
    text: str = ""
    finish_reason: str = ""
    is_finished: bool = False
    index: int = 0
    provider_specific_fields: Optional[dict[str, Any]] = None
    tool_use: Optional[dict[str, Any]] = None

    try:
        # chunk may be a pydantic object with attributes
        choices = getattr(chunk, "choices", None)
        provider_specific_fields = getattr(chunk, "provider_specific_fields", None)

        if isinstance(choices, list) and choices:
            choice = choices[0]
            # Try common OpenAI-like shapes
            delta = getattr(choice, "delta", None)
            if delta is not None:
                # delta might be an object or dict
                content = getattr(delta, "content", None)
                if content is None and isinstance(delta, dict):
                    content = delta.get("content")
                if isinstance(content, str):
                    text = content

                # TOOL CALLS (OpenAI-style incremental tool_calls on delta)
                # Attempt to normalize to a ChatCompletionToolCallChunk-like dict
                # Expected shape (best-effort):
                # { index: int, id: Optional[str], type: "function", function: {name: str|None, arguments: str|None} }
                tool_calls = getattr(delta, "tool_calls", None)
                if tool_calls is None and isinstance(delta, dict):
                    tool_calls = delta.get("tool_calls")
                if isinstance(tool_calls, list) and tool_calls:
                    tc = tool_calls[0]

                    # tc can be a dict or object with attributes
                    def _get(obj, key, default=None):
                        if isinstance(obj, dict):
                            return obj.get(key, default)
                        return getattr(obj, key, default)

                    tc_index = _get(tc, "index", 0)
                    tc_id = _get(tc, "id", None)
                    tc_type = _get(tc, "type", "function")
                    fn = _get(tc, "function", {})
                    fn_name = _get(fn, "name", None)
                    fn_args = _get(fn, "arguments", None)
                    # Ensure arguments is a string for streaming deltas
                    if fn_args is not None and not isinstance(fn_args, str):
                        try:
                            # Last resort stringification for partial structured args
                            fn_args = str(fn_args)
                        except Exception as e:
                            raise RuntimeError(
                                f"Failed to convert OpenAI tool_use to GenericStreamingChunk: {e}"
                            ) from e

                    tool_use = {
                        "index": tc_index if isinstance(tc_index, int) else 0,
                        "id": tc_id if isinstance(tc_id, str) else None,
                        "type": tc_type if isinstance(tc_type, str) else "function",
                        "function": {
                            "name": fn_name if isinstance(fn_name, str) else None,
                            "arguments": fn_args if isinstance(fn_args, str) else None,
                        },
                    }

                # Anthropic-style tool_use block on delta
                if tool_use is None:
                    a_tool_use = getattr(delta, "tool_use", None)
                    if a_tool_use is None and isinstance(delta, dict):
                        a_tool_use = delta.get("tool_use")
                    if a_tool_use is not None:

                        def _get(obj, key, default=None):
                            if isinstance(obj, dict):
                                return obj.get(key, default)
                            return getattr(obj, key, default)

                        tu_id = _get(a_tool_use, "id", None)
                        tu_name = _get(a_tool_use, "name", None)
                        tu_input = _get(a_tool_use, "input", None)
                        # Represent input as a string for arguments to keep consistency
                        if tu_input is not None and not isinstance(tu_input, str):
                            try:
                                tu_input = str(tu_input)
                            except Exception as e:
                                raise RuntimeError(
                                    f"Failed to convert Anthropic tool_use to GenericStreamingChunk: {e}"
                                ) from e

                        tool_use = {
                            "index": 0,
                            "id": tu_id if isinstance(tu_id, str) else None,
                            "type": "function",
                            "function": {
                                "name": tu_name if isinstance(tu_name, str) else None,
                                "arguments": tu_input if isinstance(tu_input, str) else None,
                            },
                        }

                # Older OpenAI-style function_call on delta
                if tool_use is None:
                    function_call = getattr(delta, "function_call", None)
                    if function_call is None and isinstance(delta, dict):
                        function_call = delta.get("function_call")
                    if function_call is not None:
                        # function_call can be dict-like or object-like
                        fn_name = None
                        fn_args = None
                        if isinstance(function_call, dict):
                            fn_name = function_call.get("name")
                            fn_args = function_call.get("arguments")
                        else:
                            fn_name = getattr(function_call, "name", None)
                            fn_args = getattr(function_call, "arguments", None)
                        if fn_args is not None and not isinstance(fn_args, str):
                            try:
                                fn_args = str(fn_args)
                            except Exception as e:
                                raise RuntimeError(
                                    f"Failed to convert OpenAI function_call to GenericStreamingChunk: {e}"
                                ) from e

                        tool_use = {
                            "index": 0,
                            "id": None,
                            "type": "function",
                            "function": {
                                "name": fn_name if isinstance(fn_name, str) else None,
                                "arguments": fn_args if isinstance(fn_args, str) else None,
                            },
                        }

            # Some providers use `text`
            if not text:
                content_text = getattr(choice, "text", None)
                if isinstance(content_text, str):
                    text = content_text

            # Finish reason & index if available
            fr = getattr(choice, "finish_reason", None)
            if isinstance(fr, str):
                finish_reason = fr
                is_finished = bool(fr)

            idx = getattr(choice, "index", None)
            if isinstance(idx, int):
                index = idx

        else:
            responses_data = _try_parse_responses_chunk(chunk)
            if responses_data is not None:
                text = responses_data["text"]
                finish_reason = responses_data["finish_reason"]
                is_finished = responses_data["is_finished"]
                index = responses_data["index"]
                if responses_data["tool_use"] is not None:
                    tool_use = responses_data["tool_use"]
                new_provider_fields = responses_data["provider_specific_fields"]
                if new_provider_fields is not None:
                    provider_specific_fields = new_provider_fields

        # Fallbacks
        # TODO Are these fallbacks ok ? Should we raise errors instead ?
        if not isinstance(text, str):
            text = ""
        if not isinstance(finish_reason, str):
            finish_reason = ""
        if not isinstance(index, int):
            index = 0

    except Exception as e:
        raise ProxyError(f"Failed to convert to GenericStreamingChunk: {e}") from e

    return {
        "text": text,
        "is_finished": is_finished,
        "finish_reason": finish_reason,
        "usage": None,  # TODO Do we have to put anything in here ?
        "index": index,
        "tool_use": tool_use,
        "provider_specific_fields": provider_specific_fields,
    }


_INPUT_TYPE_ALIASES = {
    "text": "input_text",
    "input_text": "input_text",
    "image": "input_image",
    "image_url": "input_image",
    "image_file": "input_image",
    "input_image": "input_image",
    "audio": "input_audio",
    "audio_url": "input_audio",
    "input_audio": "input_audio",
    "video": "input_video",
    "video_url": "input_video",
    "input_video": "input_video",
    "file": "input_file",
    "document": "input_file",
    "input_file": "input_file",
}


_OUTPUT_TYPE_ALIASES = {
    "text": "output_text",
    "output_text": "output_text",
    "image": "output_image",
    "image_url": "output_image",
    "output_image": "output_image",
    "audio": "output_audio",
    "audio_url": "output_audio",
    "output_audio": "output_audio",
    "video": "output_video",
    "video_url": "output_video",
    "output_video": "output_video",
}


_TOOL_TYPE_ALIASES = {
    "text": "tool_result",
    "tool_result": "tool_result",
    "input_text": "tool_result",
    "output_text": "tool_result",
}


_CONTENT_KEYS_TO_DROP = {"cache_control"}

# For regular messages we drop tool_calls / function_call content; tool_call_id is handled
# explicitly when role == "tool" and converted to function_call_output.
_MESSAGE_KEYS_TO_DROP = {"tool_calls", "function_call"}

_FUNCTION_METADATA_KEYS = ("description", "parameters", "strict")

_UNSUPPORTED_RESPONSES_PARAMS = {"stream_options"}


def convert_chat_params_to_respapi(optional_params: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of optional params adjusted for the Responses API."""

    if optional_params is None:
        return {}
    if not isinstance(optional_params, dict):
        raise TypeError("optional_params must be a dictionary when targeting the Responses API")

    params = deepcopy(optional_params)

    # Claude Code expects one tool call per turn; disable parallel tool calls
    # at the request level for Responses API.
    # Force disable parallel tool calls; Claude Code executes one tool per turn
    params["parallel_tool_calls"] = False

    tools = params.get("tools")
    if tools is not None:
        converted_tools = _convert_tools_list(tools)
        if converted_tools:
            params["tools"] = converted_tools
        else:
            params.pop("tools", None)

    functions = params.pop("functions", None)
    if functions:
        function_tools = _convert_functions_list(functions)
        if function_tools:
            params.setdefault("tools", [])
            params["tools"].extend(function_tools)

    tool_choice = params.get("tool_choice")
    if tool_choice is not None:
        converted_choice = _convert_tool_choice(tool_choice)
        if converted_choice is None:
            params.pop("tool_choice", None)
        else:
            params["tool_choice"] = converted_choice

    for key in list(params):
        if key in _UNSUPPORTED_RESPONSES_PARAMS:
            params.pop(key, None)

    return params


def convert_chat_messages_to_respapi(messages: list[Any]) -> list[dict[str, Any]]:
    """Convert Chat Completions style messages into Responses API compatible items."""

    if not isinstance(messages, list):
        raise TypeError("messages must be provided as a list")

    converted: list[dict[str, Any]] = []
    last_func_call_id: Optional[str] = None
    for idx, message in enumerate(messages):
        if not isinstance(message, dict):
            raise TypeError(f"Chat message at index {idx} must be a mapping")

        role = message.get("role")
        if not isinstance(role, str) or not role:
            raise ValueError(f"Chat message at index {idx} is missing a valid role")

        # Assistant tool calls -> function_call items
        if role == "assistant":
            tool_calls = message.get("tool_calls")
            if isinstance(tool_calls, list) and tool_calls:
                for tc in tool_calls:
                    try:
                        call_id = tc.get("id") or tc.get("call_id") or tc.get("tool_call_id")
                        fn = tc.get("function") or {}
                        name = fn.get("name") or tc.get("name")
                        arguments = fn.get("arguments") or tc.get("arguments") or ""
                        if not isinstance(arguments, str):
                            try:
                                arguments = json.dumps(arguments)
                            except Exception:
                                arguments = str(arguments)
                        # Fallback: if no call_id, synthesize a stable id for this turn
                        if not isinstance(call_id, str) or not call_id:
                            # Try to peek ahead for the next 'tool' message's tool_call_id
                            peek_id = None
                            for j in range(idx + 1, len(messages)):
                                mj = messages[j]
                                if isinstance(mj, dict) and mj.get("role") == "tool":
                                    peek_id = mj.get("tool_call_id") or mj.get("call_id")
                                    if peek_id:
                                        break
                            call_id = peek_id or f"fc_{idx}"
                        converted.append(
                            {
                                "type": "function_call",
                                "call_id": call_id,
                                "name": name,
                                "arguments": arguments,
                            }
                        )
                        last_func_call_id = call_id
                    except Exception:
                        continue

        # Tool results -> function_call_output items
        if role == "tool":
            call_id = message.get("tool_call_id") or message.get("call_id") or last_func_call_id or f"fc_{idx}"
            content = message.get("content")
            if isinstance(content, list):
                output_str = _flatten_responses_text(content)
            elif isinstance(content, str):
                output_str = content
            else:
                try:
                    output_str = json.dumps(content)
                except Exception:
                    output_str = str(content)

            converted.append(
                {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": output_str or "",
                }
            )
            continue

        # Drop tool_calls and function_call - Responses API doesn't support these in message content
        # We already emitted function_call / function_call_output items above.
        keys_to_exclude = {"content"} | _MESSAGE_KEYS_TO_DROP
        new_message: dict[str, Any] = {k: deepcopy(v) for k, v in message.items() if k not in keys_to_exclude}

        # Responses API supports: assistant, system, developer, user
        normalized_role = role

        content = message.get("content")
        new_message["content"] = _normalize_message_content(normalized_role, content)
        converted.append(new_message)

    return converted


def _normalize_message_content(role: str, content: Any) -> list[Any]:
    if isinstance(content, str):
        return [{"type": _default_content_type_for_role(role), "text": content}]

    if isinstance(content, dict):
        return [_convert_content_part(role, content)]

    if isinstance(content, list):
        normalized_parts: list[Any] = []
        for part in content:
            normalized_parts.append(_convert_content_part(role, part))
        return normalized_parts

    if content is None:
        return []

    # Fallback to string representation
    return [{"type": _default_content_type_for_role(role), "text": str(content)}]


def _convert_content_part(role: str, part: Any) -> dict[str, Any]:
    if isinstance(part, str):
        return {"type": _default_content_type_for_role(role), "text": part}

    if not isinstance(part, dict):
        return {"type": _default_content_type_for_role(role), "text": str(part)}

    new_part = deepcopy(part)
    for key in list(new_part):
        if key in _CONTENT_KEYS_TO_DROP:
            new_part.pop(key, None)
    part_type = new_part.get("type")
    normalized_type = _normalize_type_by_role(role, part_type)
    if normalized_type is not None:
        new_part["type"] = normalized_type
    elif "type" not in new_part:
        new_part["type"] = _default_content_type_for_role(role)
    else:
        new_part["type"] = str(new_part["type"])

    part_type_key = new_part["type"]

    if part_type_key in {"input_text", "output_text", "tool_result"}:
        if "text" not in new_part and "content" in new_part:
            new_part["text"] = new_part.pop("content")
        elif "text" not in new_part and "value" in new_part:
            new_part["text"] = new_part.pop("value")
        elif "text" not in new_part and "message" in new_part:
            new_part["text"] = new_part.pop("message")
        if "text" not in new_part:
            new_part["text"] = ""

    if part_type_key == "input_image":
        if "image_url" in new_part:
            image_payload = new_part["image_url"]
            if isinstance(image_payload, dict) and "url" in image_payload and len(image_payload) == 1:
                new_part["image_url"] = image_payload["url"]
        elif "image" in new_part:
            new_part["image_url"] = new_part.pop("image")

    if part_type_key == "input_audio" and "audio" in new_part and "audio_url" not in new_part:
        new_part["audio_url"] = new_part.pop("audio")

    if part_type_key == "input_video" and "video" in new_part and "video_url" not in new_part:
        new_part["video_url"] = new_part.pop("video")

    if part_type_key == "input_file" and "file" in new_part and "file_id" not in new_part:
        new_part["file_id"] = new_part.pop("file")

    return new_part


def _convert_tools_list(tools: Any) -> list[dict[str, Any]]:
    if tools is None:
        return []

    if isinstance(tools, dict):
        iterable = [tools]
    elif isinstance(tools, list):
        iterable = tools
    else:
        raise TypeError("tools must be a list or dict when targeting the Responses API")

    converted: list[dict[str, Any]] = []
    for idx, tool in enumerate(iterable):
        if not isinstance(tool, dict):
            raise TypeError(f"tool definition at index {idx} must be a mapping")

        # Already Responses format
        if tool.get("type") == "function" and "function" not in tool:
            name = tool.get("name")
            if isinstance(name, str) and name:
                converted.append(deepcopy(tool))
            continue

        if tool.get("type") == "function" or "function" in tool:
            fn_payload = tool.get("function") if isinstance(tool.get("function"), dict) else {}
            name = fn_payload.get("name") or tool.get("name")
            if not isinstance(name, str) or not name:
                continue

            new_tool = {k: deepcopy(v) for k, v in tool.items() if k not in {"function"}}
            new_tool["type"] = "function"
            new_tool["name"] = name

            for key in _FUNCTION_METADATA_KEYS:
                if key in fn_payload and key not in new_tool:
                    new_tool[key] = deepcopy(fn_payload[key])

            converted.append(new_tool)
            continue

        converted.append(deepcopy(tool))

    return converted


def _convert_functions_list(functions: Any) -> list[dict[str, Any]]:
    if functions is None:
        return []

    if isinstance(functions, dict):
        iterable = [functions]
    elif isinstance(functions, list):
        iterable = functions
    else:
        raise TypeError("functions must be a list or dict when targeting the Responses API")

    converted: list[dict[str, Any]] = []
    for idx, fn in enumerate(iterable):
        if not isinstance(fn, dict):
            raise TypeError(f"function definition at index {idx} must be a mapping")

        name = fn.get("name")
        if not isinstance(name, str) or not name:
            continue

        tool_def: dict[str, Any] = {"type": "function", "name": name}
        for key in _FUNCTION_METADATA_KEYS:
            if key in fn:
                tool_def[key] = deepcopy(fn[key])

        converted.append(tool_def)

    return converted


def _convert_tool_choice(tool_choice: Any) -> Optional[Any]:
    if isinstance(tool_choice, str):
        return tool_choice

    if isinstance(tool_choice, dict):
        if isinstance(tool_choice.get("function"), dict):
            fn_payload = tool_choice["function"]
            name = fn_payload.get("name")
            if not isinstance(name, str) or not name:
                return None

            converted = {"type": "function", "name": name}
            if "arguments" in fn_payload:
                converted["arguments"] = deepcopy(fn_payload["arguments"])
            if "output" in fn_payload:
                converted["output"] = deepcopy(fn_payload["output"])
            return converted

        if tool_choice.get("type") == "function":
            name = tool_choice.get("name")
            if not isinstance(name, str) or not name:
                return None
            converted = {"type": "function", "name": name}
            if "arguments" in tool_choice:
                converted["arguments"] = deepcopy(tool_choice["arguments"])
            if "output" in tool_choice:
                converted["output"] = deepcopy(tool_choice["output"])
            return converted

        return deepcopy(tool_choice)

    return None


def _normalize_type_by_role(role: str, part_type: Any) -> Optional[str]:
    if not isinstance(part_type, str):
        return None

    lowered = part_type.lower()
    if role == "assistant":
        return _OUTPUT_TYPE_ALIASES.get(lowered, lowered if lowered.startswith("output_") else None)
    if role == "tool":
        return _TOOL_TYPE_ALIASES.get(lowered, lowered if lowered.startswith("tool_") else None)
    return _INPUT_TYPE_ALIASES.get(lowered, lowered if lowered.startswith("input_") else None)


def _default_content_type_for_role(role: str) -> str:
    if role == "assistant":
        return "output_text"
    if role == "tool":
        return "tool_result"
    return "input_text"


def _try_parse_responses_chunk(chunk: Any) -> Optional[dict[str, Any]]:
    global _RESPONSES_TOOL_ADOPTED

    def _get(obj: Any, key: str, default: Any = None) -> Any:
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    chunk_type = _get(chunk, "type")
    if not isinstance(chunk_type, str) or not chunk_type:
        chunk_type = _get(chunk, "event")
    if not isinstance(chunk_type, str) or not chunk_type:
        return None
    if not chunk_type.startswith("response."):
        return None

    finish_reason = _get(chunk, "finish_reason")
    if not isinstance(finish_reason, str):
        finish_reason = ""

    index = _get(chunk, "output_index")
    if not isinstance(index, int):
        candidate_index = _get(chunk, "index")
        index = candidate_index if isinstance(candidate_index, int) else 0

    # Only stream assistant text for explicit output_text.delta events
    text = ""
    chunk_delta = _get(chunk, "delta")
    if chunk_type == "response.output_text.delta":
        if isinstance(chunk_delta, str):
            text = chunk_delta
        elif isinstance(chunk_delta, dict):
            delta_text = chunk_delta.get("text")
            if isinstance(delta_text, str):
                text = delta_text

    # Do not pull text from generic 'text' or 'content' fields; only output_text.delta carries assistant text

    # Never flatten aggregated output_text on structural events to avoid duplication

    tool_use = None

    def _extract_tool_identity(source: Any) -> tuple[Optional[str], Optional[str]]:
        if not source:
            return None, None
        tool_name = None
        call_id = None
        try:
            tool_name = _get(source, "name") or _get(source, "function_name") or _get(source, "tool_name")
            call_id = _get(source, "call_id") or _get(source, "tool_call_id") or _get(source, "id")
        except Exception:
            tool_name = None
            call_id = None
        return (
            tool_name if isinstance(tool_name, str) and tool_name else None,
            call_id if isinstance(call_id, str) and call_id else None,
        )

    def _apply_tool_identity(state: dict[str, Any], fallback: Any = None) -> None:
        if state is None:
            return
        raw_item = state.get("raw_item")
        tool_name = state.get("name")
        call_id = state.get("id")
        for candidate in (raw_item, fallback):
            if candidate is None:
                continue
            cand_name, cand_id = _extract_tool_identity(candidate)
            if not tool_name and cand_name:
                tool_name = cand_name
            if not call_id and cand_id:
                call_id = cand_id
            if tool_name and call_id:
                break
        state["name"] = tool_name
        state["id"] = call_id or state.get("item_id")

    # Suppress assistant text for tool argument events
    if chunk_type in {
        "response.function_call_arguments.delta",
        "response.function_call_arguments.done",
        "response.input_json.delta",
    }:
        text = ""

    # Handle Responses tool/function call start event: response.output_item.added
    if chunk_type == "response.output_item.added":
        item = _get(chunk, "item")
        if isinstance(item, dict):
            item_type = _get(item, "type")
            if item_type in {"function_call", "tool_call"}:
                name = _get(item, "name") or _get(item, "function_name")
                call_id = _get(item, "id") or _get(item, "call_id") or _get(item, "tool_call_id")
                # Track this function call by its item id
                item_id_for_state = _get(item, "id")
                if isinstance(item_id_for_state, str) and item_id_for_state:
                    state = _RESPONSES_TOOL_STATE[item_id_for_state]
                else:
                    state = {
                        "item_id": item_id_for_state,
                        "name": None,
                        "id": None,
                        "args": "",
                        "args_done": False,
                        "emitted": False,
                        "pending_emit": False,
                        "index": index,
                        "raw_item": None,
                    }
                    _RESPONSES_TOOL_STATE[item_id_for_state] = state

                state["name"] = state.get("name") or (name if isinstance(name, str) else None)
                state["id"] = state.get("id") or (call_id if isinstance(call_id, str) else None)
                state["raw_item"] = deepcopy(item)
                _log_responses_tool(
                    f"output_item.added item_id={item_id_for_state} name={state.get('name')} call_id={state.get('id')}"
                )
                _RESPONSES_TELEMETRY["saw_tool_items"] = _RESPONSES_TELEMETRY.get("saw_tool_items", 0) + 1
                if _RESPONSES_TOOL_ADOPTED is None and isinstance(item_id_for_state, str):
                    _RESPONSES_TELEMETRY["adopted_item_id"] = item_id_for_state
                    _RESPONSES_TELEMETRY["adopted_output_index"] = index
                elif (
                    _RESPONSES_TOOL_ADOPTED is not None
                    and isinstance(item_id_for_state, str)
                    and _RESPONSES_TOOL_ADOPTED != item_id_for_state
                ):
                    _RESPONSES_TELEMETRY["extra_tool_items_ignored"] = (
                        _RESPONSES_TELEMETRY.get("extra_tool_items_ignored", 0) + 1
                    )
                tool_use = _maybe_emit_tool(item_id_for_state, default_index=index)

    # Accumulate streaming function_call arguments
    if chunk_type == "response.function_call_arguments.delta":
        item_id = _get(chunk, "item_id")
        delta_text = _get(chunk, "delta")
        if isinstance(item_id, str) and isinstance(delta_text, str):
            state = _RESPONSES_TOOL_STATE.get(item_id)
            if state is None:
                state = {
                    "item_id": item_id,
                    "name": None,
                    "id": None,
                    "args": "",
                    "args_done": False,
                    "emitted": False,
                    "pending_emit": False,
                    "index": index,
                    "raw_item": None,
                }
                _RESPONSES_TOOL_STATE[item_id] = state
            # Adopt the first item we see args for
            if _RESPONSES_TOOL_ADOPTED is None:
                _RESPONSES_TOOL_ADOPTED = item_id
                _log_responses_tool(f"adopted tool item_id={item_id} via arguments.delta")
            state["args"] = (state.get("args") or "") + delta_text
            tool_use = _maybe_emit_tool(item_id, default_index=index)
            tool_use = _maybe_emit_tool(item_id, default_index=index)

    # Some providers may stream JSON arguments via input_json.delta
    if chunk_type == "response.input_json.delta":
        item_id = _get(chunk, "item_id")
        delta_text = _get(chunk, "delta")
        if isinstance(item_id, str) and isinstance(delta_text, str):
            state = _RESPONSES_TOOL_STATE.get(item_id)
            if state is None:
                state = {
                    "item_id": item_id,
                    "name": None,
                    "id": None,
                    "args": "",
                    "args_done": False,
                    "emitted": False,
                    "pending_emit": False,
                    "index": index,
                    "raw_item": None,
                }
                _RESPONSES_TOOL_STATE[item_id] = state
            if _RESPONSES_TOOL_ADOPTED is None:
                _RESPONSES_TOOL_ADOPTED = item_id
                _log_responses_tool(f"adopted tool item_id={item_id} via input_json.delta")
            state["args"] = (state.get("args") or "") + delta_text

    # Finalize args on done
    if chunk_type == "response.function_call_arguments.done":
        item_id = _get(chunk, "item_id")
        if isinstance(item_id, str) and item_id in _RESPONSES_TOOL_STATE:
            # If we haven't adopted yet (no deltas ever), adopt now
            if _RESPONSES_TOOL_ADOPTED is None:
                _RESPONSES_TOOL_ADOPTED = item_id
                _log_responses_tool(f"adopted tool item_id={item_id} via arguments.done")
            state = _RESPONSES_TOOL_STATE[item_id]
            if _RESPONSES_TOOL_ADOPTED == item_id and not state.get("emitted"):
                _apply_tool_identity(state)
                final_args = _get(chunk, "arguments")
                if isinstance(final_args, (dict, list)):
                    try:
                        final_args = json.dumps(final_args)
                    except Exception:
                        final_args = str(final_args)
                if isinstance(final_args, str) and final_args:
                    state["args"] = final_args
                if not isinstance(state.get("args"), str) or not state.get("args"):
                    state["args"] = state.get("args", "")
                state["args_done"] = True
                tool_use = _maybe_emit_tool(item_id, default_index=index)

    if chunk_type == "response.output_item.done":
        item = _get(chunk, "item")
        if isinstance(item, dict):
            item_type = _get(item, "type")
            if item_type in {"function_call", "tool_call"}:
                item_id = _get(item, "id")
                if isinstance(item_id, str) and item_id in _RESPONSES_TOOL_STATE:
                    state = _RESPONSES_TOOL_STATE[item_id]
                    if not state.get("emitted"):
                        _apply_tool_identity(state, fallback=item)
                        final_args = _get(item, "arguments")
                        if isinstance(final_args, (dict, list)):
                            try:
                                final_args = json.dumps(final_args)
                            except Exception:
                                final_args = str(final_args)
                        if isinstance(final_args, str) and final_args:
                            state["args"] = final_args
                        if not state.get("args_done"):
                            state["args_done"] = True
                        tool_use = _maybe_emit_tool(item_id, default_index=index)
                    try:
                        del _RESPONSES_TOOL_STATE[item_id]
                    except Exception:
                        pass
                    # Clear adoption if it was this item
                    if _RESPONSES_TOOL_ADOPTED == item_id:
                        _RESPONSES_TOOL_ADOPTED = None

    # Suppress generic function/tool_call emissions mid-stream; we only emit
    # once on *.arguments.done / output_item.done / completed fallback.

    # For completed responses, check response.output for tool calls
    if tool_use is None and chunk_type in {
        "response.completed",
        "response.failed",
        "response.canceled",
        "response.cancelled",
    }:
        response_obj = _get(chunk, "response")
        if response_obj is not None:
            output = _get(response_obj, "output")
            if isinstance(output, list):
                for item in output:
                    item_type = _get(item, "type")
                    if item_type in {"function_call", "tool_call"}:
                        name = _get(item, "name") or _get(item, "function_name")
                        arguments = _get(item, "arguments") or _get(item, "input") or _get(item, "input_json")
                        if arguments is not None and not isinstance(arguments, str):
                            try:
                                arguments = str(arguments)
                            except Exception as exc:
                                raise ProxyError(
                                    "Failed to convert Responses output tool_call arguments to string"
                                ) from exc
                        call_id = _get(item, "id") or _get(item, "call_id") or _get(item, "tool_call_id")
                        if _RESPONSES_TOOL_ADOPTED is None or _RESPONSES_TOOL_ADOPTED == _get(item, "id"):
                            final_args = arguments if isinstance(arguments, str) and arguments else "{}"
                            fallback_state = {
                                "item_id": _get(item, "id"),
                                "name": name if isinstance(name, str) else None,
                                "id": call_id if isinstance(call_id, str) else None,
                                "args": final_args,
                                "args_done": True,
                                "emitted": False,
                                "index": index,
                                "raw_item": deepcopy(item),
                            }
                            _RESPONSES_TOOL_STATE[_get(item, "id")] = fallback_state
                            tool_use = _maybe_emit_tool(_get(item, "id"), default_index=index)
                        break

    terminal_suffixes = (".completed", ".failed", ".cancelled", ".canceled")
    is_finished = any(chunk_type.endswith(suffix) for suffix in terminal_suffixes)
    if chunk_type in {"response.completed", "response.error", "response.canceled", "response.cancelled"}:
        is_finished = True

    if chunk_type == "response.error" and not finish_reason:
        finish_reason = "error"
    elif is_finished and not finish_reason:
        finish_reason = "stop"

    # Terminal cleanup: clear buffered tool state to avoid leaks across turns
    if chunk_type in {
        "response.completed",
        "response.failed",
        "response.canceled",
        "response.cancelled",
        "response.error",
    }:
        try:
            _RESPONSES_TOOL_STATE.clear()
        except Exception:
            pass
        _RESPONSES_TOOL_ADOPTED = None

    provider_specific_fields: dict[str, Any] = {"responses_type": chunk_type}
    for key in ("response_id", "output_index", "item_id", "id", "status"):
        value = _get(chunk, key)
        if value is not None:
            provider_specific_fields[key] = deepcopy(value)
    if isinstance(chunk_delta, dict):
        provider_specific_fields["delta"] = deepcopy(chunk_delta)
    if not provider_specific_fields:
        provider_specific_fields = None

    if not isinstance(text, str):
        text = ""

    return {  # TODO Wrap it into an actual GenericStreamingChunk object ?
        "text": text,
        "finish_reason": finish_reason,
        "is_finished": is_finished,
        "index": index,
        "tool_use": tool_use,
        "provider_specific_fields": provider_specific_fields,
    }


def convert_respapi_to_model_response(respapi_response: ResponsesAPIResponse) -> ModelResponse:
    """Best-effort convert a LiteLLM ResponsesAPIResponse into a ModelResponse."""

    if respapi_response is None:
        raise ValueError("respapi_response cannot be None")

    def _get(obj: Any, key: str, default: Any = None) -> Any:
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    model_response: dict[str, Any] = {}

    model_response["id"] = _get(respapi_response, "id")
    model_response["object"] = _get(respapi_response, "object", "chat.completion")
    model_response["created"] = _get(respapi_response, "created") or _get(respapi_response, "created_at")
    model_response["model"] = _get(respapi_response, "model")

    metadata = _get(respapi_response, "metadata")
    if metadata is not None:
        model_response["metadata"] = deepcopy(metadata)

    usage = _get(respapi_response, "usage")
    if isinstance(usage, dict):
        # Responses API uses input_tokens/output_tokens, Chat Completions uses prompt_tokens/completion_tokens
        prompt_tokens = usage.get("prompt_tokens") or usage.get("input_tokens")
        completion_tokens = usage.get("completion_tokens") or usage.get("output_tokens")
        total_tokens = usage.get("total_tokens")
        if prompt_tokens is not None and completion_tokens is not None and total_tokens is None:
            total_tokens = prompt_tokens + completion_tokens
        model_response["usage"] = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        }

    text_segments: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    function_call: Optional[dict[str, Any]] = None

    output = _get(respapi_response, "output")
    if isinstance(output, list):
        for item in output:
            item_type = _get(item, "type") or _get(item, "event")
            if item_type == "message":
                content = _get(item, "content")
                flattened = _flatten_responses_text(content)
                if flattened:
                    text_segments.append(flattened)
            elif item_type == "tool_call":
                # Convert to dict for _convert_responses_tool_call if needed
                item_dict = (
                    item if isinstance(item, dict) else {k: _get(item, k) for k in dir(item) if not k.startswith("_")}
                )
                maybe_tool = _convert_responses_tool_call(item_dict)
                if maybe_tool is not None:
                    tool_calls.append(maybe_tool)
            elif item_type == "function_call" and function_call is None:
                # Convert to dict for _convert_responses_tool_call if needed
                item_dict = (
                    item if isinstance(item, dict) else {k: _get(item, k) for k in dir(item) if not k.startswith("_")}
                )
                maybe_fn = _convert_responses_tool_call(item_dict)
                if maybe_fn is not None:
                    function_call = _get(maybe_fn, "function")

    message_content = "".join(text_segments) if text_segments else ""

    choice_message: dict[str, Any] = {
        "role": "assistant",
        "content": message_content,
    }
    if tool_calls:
        choice_message["tool_calls"] = tool_calls
    if function_call is not None:
        choice_message["function_call"] = function_call

    finish_reason: Optional[str] = None
    status = _get(respapi_response, "status")
    if isinstance(status, str):
        if status == "completed":
            finish_reason = "stop"
        elif status in {"canceled", "cancelled"}:
            finish_reason = "cancelled"
        elif status == "failed":
            finish_reason = "error"

    model_response["choices"] = [
        {
            "index": 0,
            "finish_reason": finish_reason,
            "message": choice_message,
        }
    ]

    provider_fields: dict[str, Any] = {}
    for key in ("response", "meta", "trace_id", "previous_response_id"):
        value = _get(respapi_response, key)
        if value is not None:
            provider_fields[key] = deepcopy(value)
    if provider_fields:
        model_response["provider_specific_fields"] = provider_fields

    return ModelResponse(**model_response)


def _flatten_responses_text(content: Any) -> str:
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        segments: list[str] = []
        for part in content:
            if isinstance(part, dict):
                for key in ("text", "input_text", "output_text"):
                    value = part.get(key)
                    if isinstance(value, str):
                        segments.append(value)
                        break
                else:
                    nested = part.get("content")
                    if nested is not None:
                        flattened = _flatten_responses_text(nested)
                        if flattened:
                            segments.append(flattened)
            elif isinstance(part, str):
                segments.append(part)
        return "".join(segments)

    if isinstance(content, dict):
        return _flatten_responses_text(content.get("content"))

    return "" if content is None else str(content)


def _convert_responses_tool_call(payload: dict[str, Any]) -> Optional[dict[str, Any]]:
    name = payload.get("name") or payload.get("function_name")
    if not isinstance(name, str) or not name:
        return None

    call_id = payload.get("id") or payload.get("call_id") or payload.get("tool_call_id")

    raw_arguments = payload.get("arguments")
    if raw_arguments is None:
        raw_arguments = payload.get("input") or payload.get("input_arguments")

    if isinstance(raw_arguments, str):
        arguments: Optional[str] = raw_arguments
    elif isinstance(raw_arguments, (list, dict)):
        flattened = _flatten_responses_text(raw_arguments)
        if flattened:
            arguments = flattened
        else:
            try:
                arguments = json.dumps(raw_arguments)
            except Exception as exc:
                raise ProxyError("Failed to JSON-encode Responses tool_call arguments") from exc
    else:
        arguments = str(raw_arguments) if raw_arguments is not None else None

    return {
        "id": call_id if isinstance(call_id, str) else None,
        "type": "function",
        "function": {
            "name": name,
            "arguments": arguments or "",
        },
    }
