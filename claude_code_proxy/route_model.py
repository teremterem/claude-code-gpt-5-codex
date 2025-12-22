import re
from typing import Any

from claude_code_proxy.proxy_config import (
    ALWAYS_USE_RESPONSES_API,
    ANTHROPIC,
    GEMINI,
    OPENAI,
    REMAP_CLAUDE_HAIKU_TO,
    REMAP_CLAUDE_OPUS_TO,
    REMAP_CLAUDE_SONNET_TO,
    RESPAPI_ONLY_MODELS,
)


class ModelRoute:
    requested_model: str  # May or may not have a provider prefix
    remapped_to: str  # May or may not have a provider prefix
    target_model: str  # ALWAYS has a provider prefix ("provider/model_name")
    extra_params: dict[str, Any]
    is_target_anthropic: bool
    is_target_gemini: bool
    use_responses_api: bool

    def __init__(self, requested_model: str) -> None:
        self.requested_model = requested_model.strip()

        self._remap_model()
        self._finalize_model_route_object()

        self._log_model_route()

    def _remap_model(self) -> str:
        self.remapped_to = self.requested_model

        if self.requested_model.startswith("claude-"):
            # If the model name contains "haiku", "opus", or "sonnet", remap it
            # to the appropriate model (provided the remap is configured)
            if "haiku" in self.requested_model:
                if REMAP_CLAUDE_HAIKU_TO:
                    self.remapped_to = REMAP_CLAUDE_HAIKU_TO
            elif "opus" in self.requested_model:
                if REMAP_CLAUDE_OPUS_TO:
                    self.remapped_to = REMAP_CLAUDE_OPUS_TO
            elif REMAP_CLAUDE_SONNET_TO:
                # Here we assume the requested model is a Sonnet model (but
                # also fallback to this remap in case it is some new, unknown
                # model by Anthropic)
                # TODO Add a warning if the requested model is unknown ?
                self.remapped_to = REMAP_CLAUDE_SONNET_TO

        self.remapped_to = self.remapped_to.strip()

    def _finalize_model_route_object(self) -> None:
        """
        Resolve and prepend provider to the model name if not already present,
        set other attributes to finish initializing this ModelRoute object.
        """
        if "/" in self.remapped_to:
            explicit_provider, model_name_only = self.remapped_to.split("/", 1)
        else:
            # Provider is not mentioned in the model name explicitly
            explicit_provider, model_name_only = None, self.remapped_to

        # Check if it is one of our GPT-5 model aliases with a reasoning effort
        # specified in the model name
        reasoning_effort_alias_match = re.fullmatch(
            r"(?P<name>.+)-reason(ing)?(-effort)?-(?P<effort>\w+)", model_name_only
        )
        if reasoning_effort_alias_match:
            model_name_only = reasoning_effort_alias_match.group("name")
            self.extra_params = {"reasoning_effort": reasoning_effort_alias_match.group("effort")}
        else:
            self.extra_params = {}

        # Autocorrect `gpt5` to `gpt-5` for convenience
        model_name_only = re.sub(r"\bgpt5\b", "gpt-5", model_name_only)

        if explicit_provider:
            self.target_model = f"{explicit_provider}/{model_name_only}"
        elif model_name_only.startswith("claude-"):
            self.target_model = f"{ANTHROPIC}/{model_name_only}"
        else:
            # Default to OpenAI if it is not a Claude model (and the provider
            # was not specified explicitly)
            self.target_model = f"{OPENAI}/{model_name_only}"

        self.is_target_anthropic = self.target_model.startswith(f"{ANTHROPIC}/")
        self.is_target_gemini = self.target_model.startswith(f"{GEMINI}/")

        if self.is_target_anthropic:
            self.use_responses_api = False
        else:
            self.use_responses_api = ALWAYS_USE_RESPONSES_API or any(
                model in model_name_only for model in RESPAPI_ONLY_MODELS
            )

    def _log_model_route(self) -> None:
        log_message = f"\033[1m\033[32m{self.requested_model}\033[0m -> " f"\033[1m\033[36m{self.target_model}\033[0m"
        if self.extra_params:
            log_message += f" [\033[1m\033[33m{self._repr_extra_params()}\033[0m]"
        # TODO Make it possible to disable this print ? (Turn it into a log
        #  record ?)
        print(log_message)

    def _repr_extra_params(self) -> str:
        return ", ".join([f"{k}: {v}" for k, v in self.extra_params.items()])
