import json
from typing import Collection, Optional

from litellm import ModelResponse, ResponsesAPIResponse

from common.config import TRACES_DIR


def write_request_trace(  # pylint: disable=unused-argument
    *,
    timestamp: str,
    calling_method: str,
    messages_original: Optional[list] = None,
    params_original: Optional[dict] = None,
    messages_complapi: Optional[list] = None,
    params_complapi: Optional[dict] = None,
    messages_respapi: Optional[list] = None,
    params_respapi: Optional[dict] = None,
) -> None:
    TRACES_DIR.mkdir(parents=True, exist_ok=True)
    file = TRACES_DIR / f"{timestamp}_REQUEST.md"
    if file.exists():
        # TODO Replace with a warning instead ?
        raise FileExistsError(f"File {file} already exists")

    with file.open("w", encoding="utf-8") as f:
        f.write(f"# {calling_method.upper()}\n\n")

        f.write("## Request Messages\n\n")

        # # TODO Any way to make the difference between the original and the
        # #  other messages more intuitive ?
        # if messages_original is not None and (messages_complapi is None or messages_original != messages_complapi):
        #     f.write("### Original:\n")
        #     f.write(f"```json\n{json.dumps(messages_original, indent=2)}\n```\n\n")

        if messages_complapi is not None:
            f.write("### ChatCompletions API:\n")
            f.write(f"```json\n{json.dumps(messages_complapi, indent=2)}\n```\n\n")

        if messages_respapi is not None:
            f.write("### Responses API:\n")
            f.write(f"```json\n{json.dumps(messages_respapi, indent=2)}\n```\n")

        f.write("## Request Params\n\n")

        # # TODO Any way to make the difference between the original and the
        # #  other parameters more intuitive ?
        # if params_original is not None and (params_complapi is None or params_original != params_complapi):
        #     f.write("### Original:\n")
        #     f.write(f"```json\n{json.dumps(params_original, indent=2)}\n```\n\n")

        if params_complapi is not None:
            f.write("### ChatCompletions API:\n")
            f.write(f"```json\n{json.dumps(params_complapi, indent=2)}\n```\n\n")

        if params_respapi is not None:
            f.write("### Responses API:\n")
            f.write(f"```json\n{json.dumps(params_respapi, indent=2)}\n```\n")


def write_response_trace(
    *,
    timestamp: str,
    calling_method: str,
    response_respapi: Optional[ResponsesAPIResponse] = None,
    response_complapi: Optional[ModelResponse] = None,
) -> None:
    TRACES_DIR.mkdir(parents=True, exist_ok=True)
    file = TRACES_DIR / f"{timestamp}_RESPONSE.md"
    if file.exists():
        # TODO Replace with a warning instead ?
        raise FileExistsError(f"File {file} already exists")

    with file.open("w", encoding="utf-8") as f:
        f.write(f"# {calling_method.upper()}\n\n")

        f.write("## Response\n\n")

        if response_respapi is not None:
            f.write("### Responses API:\n")
            f.write(f"```json\n{response_respapi.model_dump_json(indent=2)}\n```\n\n")

        if response_complapi is not None:
            f.write("### ChatCompletions API:\n")
            f.write(f"```json\n{response_complapi.model_dump_json(indent=2)}\n```\n")


def write_streaming_chunks_trace(
    *,
    timestamp: str,
    calling_method: str,
    chunk_idx: int,
    respapi_chunk: Optional[ResponsesAPIResponse] = None,
    complapi_chunk: Optional[ModelResponse] = None,
    generic_chunks: Optional[Collection[dict]] = None,
) -> None:
    TRACES_DIR.mkdir(parents=True, exist_ok=True)
    file = TRACES_DIR / f"{timestamp}_RESPONSE_STREAM.md"
    text_file = TRACES_DIR / f"{timestamp}_RESPONSE_TEXT.md"

    # If file doesn't exist, create it with the main header
    if not file.exists():
        with file.open("a", encoding="utf-8") as f:
            f.write(f"# {calling_method.upper()}\n\n")

    # Append the chunk to the file
    with file.open("a", encoding="utf-8") as f:
        f.write(f"## Response Chunk #{chunk_idx}\n\n")

        if respapi_chunk is not None:
            f.write(f"### Responses API:\n```json\n{respapi_chunk.model_dump_json(indent=2)}\n```\n\n")

        if complapi_chunk is not None:
            f.write(f"### ChatCompletions API:\n```json\n{complapi_chunk.model_dump_json(indent=2)}\n```\n\n")

        if generic_chunks:
            f.write("### GenericStreamingChunk(s):\n")
            for generic_chunk in generic_chunks:
                f.write(f"```json\n{json.dumps(generic_chunk, indent=2)}\n```\n\n")

                if generic_chunk["text"]:
                    # Append the text of the chunk to the text file
                    with text_file.open("a", encoding="utf-8") as text_f:
                        text_f.write(generic_chunk["text"])
