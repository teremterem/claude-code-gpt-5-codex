# pylint: disable=too-many-branches,too-many-locals,too-many-statements,too-many-return-statements
# pylint: disable=too-many-nested-blocks
"""
NOTE: The utilities in this module were mostly vibe-coded without review.
"""
import os
from datetime import UTC, datetime
from typing import Any, Optional, Union

from litellm import GenericStreamingChunk


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
    Generate timestamp in format YYYYmmdd_HHMMSS_fff in UTC.

    An example of how these timestamps are used later:

    `.traces/20251005_140642_180_RESPONSE_STREAM.md`
    """
    now = datetime.now(UTC)
    # Keep only milliseconds (first 3 digits of microseconds)
    return now.strftime("%Y%m%d_%H%M%S_%f")[:-3]


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

        # Fallbacks
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
