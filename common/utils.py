# pylint: disable=too-many-branches,too-many-locals,too-many-statements,too-many-return-statements
# pylint: disable=too-many-nested-blocks
import os
from datetime import UTC, datetime
from typing import Generator, Optional, Union

from litellm import GenericStreamingChunk, ModelResponseStream, StreamingChoices
from litellm.types.utils import Delta


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


def model_response_stream_to_generic_streaming_chunks(
    chunk: ModelResponseStream,
) -> Generator[GenericStreamingChunk, None, None]:
    """
    Convert a LiteLLM ModelResponseStream chunk into one or more
    GenericStreamingChunk(s).

    Args:
        chunk: The LiteLLM ModelResponseStream chunk to convert.

    Yields:
        The converted GenericStreamingChunk(s) - there may be more than one
        chunk if the original ModelResponseStream chunk contained multiple tool
        calls.
    """
    generic_chunk = GenericStreamingChunk(
        text="",
        tool_use=None,
        is_finished=False,
        finish_reason="",
        usage=None,  # TODO Where to read it from ?
        index=0,  # TODO Is this field important ?
        provider_specific_fields=chunk.provider_specific_fields,
    )
    yield from _populate_from_streaming_choices(generic_chunk, chunk.choices)


def _populate_from_streaming_choices(
    generic_chunk: GenericStreamingChunk,
    choices: list[StreamingChoices],
) -> Generator[GenericStreamingChunk, None, None]:
    if not choices:
        yield generic_chunk
        return
    choice = choices[0]
    # TODO Raise an error if there are more than one choice ?

    # TODO Where to put `choice.logprobs` ?
    # TODO Where to put `choice.enhancements` ?
    # TODO Where to put `choice.**params` (other arbitrary fields) ?
    generic_chunk["finish_reason"] = choice.finish_reason
    generic_chunk["is_finished"] = bool(choice.finish_reason)
    # TODO OpenAI GPT-5 (maybe other models too ?) sends one more chunk after the a "final" chunk with
    #  `finish_reason: "stop"` and that extra chunk will have `is_finished: False` because there will not be a finish
    #  reason anymore. Is this a problem ?
    yield from _populate_from_delta(generic_chunk, choice.delta)


def _populate_from_delta(
    generic_chunk: GenericStreamingChunk,
    delta: Optional[Delta],
) -> Generator[GenericStreamingChunk, None, None]:
    if not delta:
        yield generic_chunk
        return
    # TODO Where to put `delta.reasoning_content` ?
    # TODO Where to put `delta.thinking_blocks` ?
    # TODO Where to put `delta.role` ?
    # TODO Merge `delta.function_call` into `generic_chunk.tool_use` ?
    # TODO Where to put `delta.audio` ?
    # TODO Where to put `delta.images` ?
    # TODO Where to put `delta.annotations` ?
    # TODO Where to put `delta.**params` (other arbitrary fields) ?
    # TODO Merge `delta.provider_specific_fields` into `generic_chunk.provider_specific_fields` ?
    generic_chunk["text"] = delta.content
    # TODO generic_chunk.tool_use = delta.tool_calls
    yield from _populate_tool_use(generic_chunk, delta)


def _populate_tool_use(
    generic_chunk: GenericStreamingChunk,
    delta: Optional[Delta],
) -> Generator[GenericStreamingChunk, None, None]:
    if not delta:
        yield generic_chunk
        return

    # TODO TODO TODO

    yield generic_chunk
