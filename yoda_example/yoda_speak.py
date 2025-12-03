from typing import Any, AsyncGenerator, Callable, Generator, Optional, Union

import httpx
import litellm
from litellm import (
    CustomLLM,
    CustomStreamWrapper,
    GenericStreamingChunk,
    HTTPHandler,
    ModelResponse,
    ModelResponseStream,
    AsyncHTTPHandler,
)

from common.config import WRITE_TRACES_TO_FILES
from common.tracing_in_markdown import write_request_trace, write_response_trace, write_streaming_chunks_trace
from common.utils import ProxyError, generate_timestamp_utc, model_response_stream_to_generic_streaming_chunks


_YODA_SYSTEM_PROMPT = {
    "role": "system",
    "content": (
        "Regardless of the request, respond in Yoda-speak."
        " Short sentences, inverted syntax, and the wisdom of the Jedi, you must use."
    ),
}


class YodaSpeakLLM(CustomLLM):
    # pylint: disable=too-many-positional-arguments,too-many-locals,duplicate-code
    """
    Proxy wrapper that forces Yoda-speak responses from the underlying LLM.
    """

    def __init__(self, *, target_model: str = "openai/gpt-4o", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.target_model = target_model

    def completion(
        self,
        model: str,
        messages: list,
        api_base: str,
        custom_prompt_dict: dict,
        model_response: ModelResponse,
        print_verbose: Callable,
        encoding,
        api_key,
        logging_obj,
        optional_params: dict,
        acompletion=None,
        litellm_params=None,
        logger_fn=None,
        headers=None,
        timeout: Optional[Union[float, httpx.Timeout]] = None,
        client: Optional[HTTPHandler] = None,
    ) -> ModelResponse:
        try:
            timestamp = generate_timestamp_utc()
            calling_method = "completion"

            messages_modified = messages + [_YODA_SYSTEM_PROMPT]

            if WRITE_TRACES_TO_FILES:
                write_request_trace(
                    timestamp=timestamp,
                    calling_method=calling_method,
                    messages_original=messages,
                    messages_complapi=messages_modified,
                    params_complapi=optional_params,
                )

            response: ModelResponse = litellm.completion(
                model=self.target_model,
                messages=messages_modified,
                logger_fn=logger_fn,
                headers=headers or {},
                timeout=timeout,
                client=client,
                # Drop any params that are not supported by the provider
                drop_params=True,
                **optional_params,
            )

            if WRITE_TRACES_TO_FILES:
                write_response_trace(
                    timestamp=timestamp,
                    calling_method=calling_method,
                    response_complapi=response,
                )

            return response

        except Exception as e:
            raise ProxyError(e) from e

    async def acompletion(
        self,
        model: str,
        messages: list,
        api_base: str,
        custom_prompt_dict: dict,
        model_response: ModelResponse,
        print_verbose: Callable,
        encoding,
        api_key,
        logging_obj,
        optional_params: dict,
        acompletion=None,
        litellm_params=None,
        logger_fn=None,
        headers=None,
        timeout: Optional[Union[float, httpx.Timeout]] = None,
        client: Optional[AsyncHTTPHandler] = None,
    ) -> ModelResponse:
        try:
            timestamp = generate_timestamp_utc()
            calling_method = "acompletion"

            messages_modified = messages + [_YODA_SYSTEM_PROMPT]

            if WRITE_TRACES_TO_FILES:
                write_request_trace(
                    timestamp=timestamp,
                    calling_method=calling_method,
                    messages_original=messages,
                    messages_complapi=messages_modified,
                    params_complapi=optional_params,
                )

            response: ModelResponse = await litellm.acompletion(
                model=self.target_model,
                messages=messages_modified,
                logger_fn=logger_fn,
                headers=headers or {},
                timeout=timeout,
                client=client,
                # Drop any params that are not supported by the provider
                drop_params=True,
                **optional_params,
            )

            if WRITE_TRACES_TO_FILES:
                write_response_trace(
                    timestamp=timestamp,
                    calling_method=calling_method,
                    response_complapi=response,
                )

            return response

        except Exception as e:
            raise ProxyError(e) from e

    def streaming(
        self,
        model: str,
        messages: list,
        api_base: str,
        custom_prompt_dict: dict,
        model_response: ModelResponse,
        print_verbose: Callable,
        encoding,
        api_key,
        logging_obj,
        optional_params: dict,
        acompletion=None,
        litellm_params=None,
        logger_fn=None,
        headers=None,
        timeout: Optional[Union[float, httpx.Timeout]] = None,
        client: Optional[HTTPHandler] = None,
    ) -> Generator[GenericStreamingChunk, None, None]:
        try:
            timestamp = generate_timestamp_utc()
            calling_method = "streaming"

            messages_modified = messages + [_YODA_SYSTEM_PROMPT]

            if WRITE_TRACES_TO_FILES:
                write_request_trace(
                    timestamp=timestamp,
                    calling_method=calling_method,
                    messages_original=messages,
                    messages_complapi=messages_modified,
                    params_complapi=optional_params,
                )

            resp_stream: CustomStreamWrapper = litellm.completion(
                model=self.target_model,
                messages=messages_modified,
                logger_fn=logger_fn,
                headers=headers or {},
                timeout=timeout,
                client=client,
                # Drop any params that are not supported by the provider
                drop_params=True,
                **optional_params,
            )

            for chunk_idx, chunk in enumerate[ModelResponseStream](resp_stream):
                generic_chunks = list[GenericStreamingChunk](model_response_stream_to_generic_streaming_chunks(chunk))

                if WRITE_TRACES_TO_FILES:
                    write_streaming_chunks_trace(
                        timestamp=timestamp,
                        calling_method=calling_method,
                        chunk_idx=chunk_idx,
                        complapi_chunk=chunk,
                        generic_chunks=generic_chunks,
                    )

                yield from generic_chunks

        except Exception as e:
            raise ProxyError(e) from e

    async def astreaming(
        self,
        model: str,
        messages: list,
        api_base: str,
        custom_prompt_dict: dict,
        model_response: ModelResponse,
        print_verbose: Callable,
        encoding,
        api_key,
        logging_obj,
        optional_params: dict,
        acompletion=None,
        litellm_params=None,
        logger_fn=None,
        headers=None,
        timeout: Optional[Union[float, httpx.Timeout]] = None,
        client: Optional[AsyncHTTPHandler] = None,
    ) -> AsyncGenerator[GenericStreamingChunk, None]:
        try:
            timestamp = generate_timestamp_utc()
            calling_method = "astreaming"

            messages_modified = messages + [_YODA_SYSTEM_PROMPT]

            if WRITE_TRACES_TO_FILES:
                write_request_trace(
                    timestamp=timestamp,
                    calling_method=calling_method,
                    messages_original=messages,
                    messages_complapi=messages_modified,
                    params_complapi=optional_params,
                )

            resp_stream: CustomStreamWrapper = await litellm.acompletion(
                model=self.target_model,
                messages=messages_modified,
                logger_fn=logger_fn,
                headers=headers or {},
                timeout=timeout,
                client=client,
                # Drop any params that are not supported by the provider
                drop_params=True,
                **optional_params,
            )

            chunk_idx = 0
            async for chunk in resp_stream:
                generic_chunks = list[GenericStreamingChunk](model_response_stream_to_generic_streaming_chunks(chunk))

                if WRITE_TRACES_TO_FILES:
                    write_streaming_chunks_trace(
                        timestamp=timestamp,
                        calling_method=calling_method,
                        chunk_idx=chunk_idx,
                        complapi_chunk=chunk,
                        generic_chunks=generic_chunks,
                    )

                for generic_chunk in generic_chunks:
                    yield generic_chunk
                chunk_idx += 1

        except Exception as e:
            raise ProxyError(e) from e


yoda_speak_llm = YodaSpeakLLM()
