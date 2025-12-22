import os

from common import config as common_config  # Makes sure .env is loaded  # pylint: disable=unused-import
from common.utils import env_var_to_bool


# NOTE: If any of the three env vars below are set to an empty string, the
# defaults will NOT be used. The defaults are used only when these env vars are
# not set at all. This is intentional - setting them to empty strings should
# result in no remapping.
REMAP_CLAUDE_HAIKU_TO = os.getenv("REMAP_CLAUDE_HAIKU_TO", "gpt-5.1-codex-mini-reason-none")
REMAP_CLAUDE_SONNET_TO = os.getenv("REMAP_CLAUDE_SONNET_TO", "gpt-5-codex-reason-medium")
REMAP_CLAUDE_OPUS_TO = os.getenv("REMAP_CLAUDE_OPUS_TO", "gpt-5.1-reason-high")

ENFORCE_ONE_TOOL_CALL_PER_RESPONSE = env_var_to_bool(os.getenv("ENFORCE_ONE_TOOL_CALL_PER_RESPONSE"), "true")

# TODO Move these two constants to common/config.py ?
ALWAYS_USE_RESPONSES_API = env_var_to_bool(os.getenv("ALWAYS_USE_RESPONSES_API"), "false")
RESPAPI_ONLY_MODELS = (
    "codex-mini-latest",
    "computer-use-preview",
    "gpt-5-codex",
    "gpt-5-pro",
    "gpt-5.1-codex",
    "gpt-5.1-codex-mini",
    "gpt-oss-120b",
    "gpt-oss-20b",
    "o1-pro",
    "o3-deep-research",
    "o3-pro",
    "o4-mini-deep-research",
)

ANTHROPIC = "anthropic"
GEMINI = "gemini"
OPENAI = "openai"
