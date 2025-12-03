from copy import deepcopy
from typing import AsyncGenerator, Callable, Generator, Optional, Union

import httpx
import litellm
from litellm import (
    BaseResponsesAPIStreamingIterator,
    CustomLLM,
    CustomStreamWrapper,
    GenericStreamingChunk,
    HTTPHandler,
    ModelResponse,
    ModelResponseStream,
    AsyncHTTPHandler,
    ResponsesAPIResponse,
    ResponsesAPIStreamingResponse,
)

from claude_code_proxy.route_model import ModelRoute
from common.config import WRITE_TRACES_TO_FILES
from common.tracing_in_markdown import (
    write_request_trace,
    write_response_trace,
    write_streaming_chunks_trace,
)
from common.utils import (
    ProxyError,
    # convert_chat_messages_to_respapi,
    # convert_chat_params_to_respapi,
    # convert_respapi_to_model_response,
    generate_timestamp_utc,
    model_response_stream_to_generic_streaming_chunks,
)


class RoutedRequest:
    def __init__(
        self,
        *,
        calling_method: str,
        model: str,
        messages_original: list,
        params_original: dict,
        stream: bool,
    ) -> None:
        self.timestamp = generate_timestamp_utc()
        self.calling_method = calling_method
        self.model_route = ModelRoute(model)

        self.messages_original = messages_original
        self.params_original = params_original

        self.messages_complapi = deepcopy(self.messages_original)
        self.params_complapi = deepcopy(self.params_original)

        self.params_complapi.update(self.model_route.extra_params)
        self.params_complapi["stream"] = stream

        if self.model_route.use_responses_api:
            # TODO What's a more reasonable way to decide when to unset
            #  temperature ?
            self.params_complapi.pop("temperature", None)

        # For Langfuse
        trace_name = f"{self.timestamp}-OUTBOUND-{self.calling_method}"
        self.params_complapi.setdefault("metadata", {})["trace_name"] = trace_name

        if not self.model_route.is_target_anthropic:
            self._adapt_complapi_for_non_anthropic_models()

        if self.model_route.use_responses_api:
            self.messages_respapi = convert_chat_messages_to_respapi(self.messages_complapi)
            self.params_respapi = convert_chat_params_to_respapi(self.params_complapi)
        else:
            self.messages_respapi = None
            self.params_respapi = None

        if WRITE_TRACES_TO_FILES:
            write_request_trace(
                timestamp=self.timestamp,
                calling_method=self.calling_method,
                messages_original=self.messages_original,
                params_original=self.params_original,
                messages_complapi=self.messages_complapi,
                params_complapi=self.params_complapi,
                messages_respapi=self.messages_respapi,
                params_respapi=self.params_respapi,
            )

    def _adapt_complapi_for_non_anthropic_models(self) -> None:
        """
        Perform necessary prompt injections to adjust certain requests to work with
        non-Anthropic models.
        """
        # Claude Code 2.x sends `context_management` on /v1/messages, but
        # OpenAI's ChatCompletions and Responses APIs do not support it
        # TODO How to reproduce the problem that the line below is fixing ?
        #  (This fix was contributed)
        self.params_complapi.pop("context_management", None)

        if (
            self.params_complapi.get("max_tokens") == 1
            and len(self.messages_complapi) == 1
            and self.messages_complapi[0].get("role") == "user"
            and self.messages_complapi[0].get("content") in ["quota", "test"]
        ):
            # This is a "connectivity test" request by Claude Code => we need
            # to make sure non-Anthropic models don't fail because of exceeding
            # max_tokens
            self.params_complapi["max_tokens"] = 100
            self.messages_complapi[0]["role"] = "system"
            self.messages_complapi[0][
                "content"
            ] = "The intention of this request is to test connectivity. Please respond with a single word: OK"


class ClaudeCodeRouter(CustomLLM):
    # pylint: disable=too-many-positional-arguments,too-many-locals

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
            routed_request = RoutedRequest(
                calling_method="completion",
                model=model,
                messages_original=messages,
                params_original=optional_params,
                stream=False,
            )

            if routed_request.model_route.use_responses_api:
                response_respapi: ResponsesAPIResponse = litellm.responses(
                    # TODO Make sure all params are supported
                    model=routed_request.model_route.target_model,
                    input=routed_request.messages_respapi,
                    logger_fn=logger_fn,
                    headers=headers or {},
                    timeout=timeout,
                    client=client,
                    **routed_request.params_respapi,
                )
                response_complapi: ModelResponse = convert_respapi_to_model_response(response_respapi)

            else:
                response_respapi = None
                response_complapi: ModelResponse = litellm.completion(
                    model=routed_request.model_route.target_model,
                    messages=routed_request.messages_complapi,
                    logger_fn=logger_fn,
                    headers=headers or {},
                    timeout=timeout,
                    client=client,
                    # Drop any params that are not supported by the provider
                    drop_params=True,
                    **routed_request.params_complapi,
                )

            if WRITE_TRACES_TO_FILES:
                write_response_trace(
                    timestamp=routed_request.timestamp,
                    calling_method=routed_request.calling_method,
                    response_respapi=response_respapi,
                    response_complapi=response_complapi,
                )

            return response_complapi

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
            routed_request = RoutedRequest(
                calling_method="acompletion",
                model=model,
                messages_original=messages,
                params_original=optional_params,
                stream=False,
            )

            if routed_request.model_route.use_responses_api:
                response_respapi: ResponsesAPIResponse = await litellm.aresponses(
                    # TODO Make sure all params are supported
                    model=routed_request.model_route.target_model,
                    input=routed_request.messages_respapi,
                    logger_fn=logger_fn,
                    headers=headers or {},
                    timeout=timeout,
                    client=client,
                    **routed_request.params_respapi,
                )
                response_complapi: ModelResponse = convert_respapi_to_model_response(response_respapi)

            else:
                response_respapi = None
                response_complapi: ModelResponse = await litellm.acompletion(
                    model=routed_request.model_route.target_model,
                    messages=routed_request.messages_complapi,
                    logger_fn=logger_fn,
                    headers=headers or {},
                    timeout=timeout,
                    client=client,
                    # Drop any params that are not supported by the provider
                    drop_params=True,
                    **routed_request.params_complapi,
                )

            if WRITE_TRACES_TO_FILES:
                write_response_trace(
                    timestamp=routed_request.timestamp,
                    calling_method=routed_request.calling_method,
                    response_respapi=response_respapi,
                    response_complapi=response_complapi,
                )

            return response_complapi

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
            routed_request = RoutedRequest(
                calling_method="streaming",
                model=model,
                messages_original=messages,
                params_original=optional_params,
                stream=True,
            )

            if routed_request.model_route.use_responses_api:
                resp_stream: BaseResponsesAPIStreamingIterator = litellm.responses(
                    # TODO Make sure all params are supported
                    model=routed_request.model_route.target_model,
                    input=routed_request.messages_respapi,
                    logger_fn=logger_fn,
                    headers=headers or {},
                    timeout=timeout,
                    client=client,
                    **routed_request.params_respapi,
                )

            else:
                resp_stream: CustomStreamWrapper = litellm.completion(
                    model=routed_request.model_route.target_model,
                    messages=routed_request.messages_complapi,
                    logger_fn=logger_fn,
                    headers=headers or {},
                    timeout=timeout,
                    client=client,
                    # Drop any params that are not supported by the provider
                    drop_params=True,
                    **routed_request.params_complapi,
                )

            for chunk_idx, chunk in enumerate[ModelResponseStream | ResponsesAPIStreamingResponse](resp_stream):
                generic_chunks = list[GenericStreamingChunk](model_response_stream_to_generic_streaming_chunks(chunk))

                if WRITE_TRACES_TO_FILES:
                    if routed_request.model_route.use_responses_api:
                        respapi_chunk, complapi_chunk = chunk, None
                    else:
                        respapi_chunk, complapi_chunk = None, chunk

                    write_streaming_chunks_trace(
                        timestamp=routed_request.timestamp,
                        calling_method=routed_request.calling_method,
                        chunk_idx=chunk_idx,
                        respapi_chunk=respapi_chunk,
                        complapi_chunk=complapi_chunk,
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
            routed_request = RoutedRequest(
                calling_method="astreaming",
                model=model,
                messages_original=messages,
                params_original=optional_params,
                stream=True,
            )

            if routed_request.model_route.use_responses_api:
                resp_stream: BaseResponsesAPIStreamingIterator = await litellm.aresponses(
                    # TODO Make sure all params are supported
                    model=routed_request.model_route.target_model,
                    input=routed_request.messages_respapi,
                    logger_fn=logger_fn,
                    headers=headers or {},
                    timeout=timeout,
                    client=client,
                    **routed_request.params_respapi,
                )

            else:
                resp_stream: CustomStreamWrapper = await litellm.acompletion(
                    model=routed_request.model_route.target_model,
                    messages=routed_request.messages_complapi,
                    logger_fn=logger_fn,
                    headers=headers or {},
                    timeout=timeout,
                    client=client,
                    # Drop any params that are not supported by the provider
                    drop_params=True,
                    **routed_request.params_complapi,
                )

            chunk_idx = 0
            async for chunk in resp_stream:
                generic_chunks = list[GenericStreamingChunk](model_response_stream_to_generic_streaming_chunks(chunk))

                if WRITE_TRACES_TO_FILES:
                    if routed_request.model_route.use_responses_api:
                        respapi_chunk, complapi_chunk = chunk, None
                    else:
                        respapi_chunk, complapi_chunk = None, chunk

                    write_streaming_chunks_trace(
                        timestamp=routed_request.timestamp,
                        calling_method=routed_request.calling_method,
                        chunk_idx=chunk_idx,
                        respapi_chunk=respapi_chunk,
                        complapi_chunk=complapi_chunk,
                        generic_chunks=generic_chunks,
                    )

                for generic_chunk in generic_chunks:
                    yield generic_chunk
                chunk_idx += 1

        except Exception as e:
            raise ProxyError(e) from e


claude_code_router = ClaudeCodeRouter()
