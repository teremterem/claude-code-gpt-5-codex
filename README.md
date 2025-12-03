<p align="center">
    <img alt="Claude Code with GPT-5 Codex"
        src="https://raw.githubusercontent.com/teremterem/claude-code-gpt-5-codex/main/images/claude-code-gpt-5-codex2.jpeg">
</p>

This repository lets you use Anthropic's **Claude Code CLI** with OpenAI models such as **GPT-5-Codex, GPT-5.1, and others** via a local LiteLLM proxy.

> **⚠️ ATTENTION ⚠️**
>
> If you're here to set up `your own LiteLLM Server` with `LibreChat` as the web UI (or any other OpenAI / Anthropic API compatible client, for that matter), head over to the [litellm-server-boilerplate](https://github.com/teremterem/litellm-server-boilerplate) repository. It contains a "boilerplate" version of this repo with Claude Code CLI stuff stripped away, **an optional `LibreChat` set up, and a `README` which specifically explains how to build `your own AI agents and assistants` on top of it.**

## Quick Start ⚡

### Prerequisites

- [OpenAI API key 🔑](https://platform.openai.com/settings/organization/api-keys)
- [Anthropic API key 🔑](https://console.anthropic.com/settings/keys) - optional (if you decide not to remap some Claude models to OpenAI)
- Either [uv](https://docs.astral.sh/uv/getting-started/installation/) or [Docker Desktop](https://docs.docker.com/desktop/), depending on your preferred setup method

### First time using GPT-5 via API?

If you are going to use GPT-5 via API for the first time, **OpenAI may require you to verify your identity via Persona.** You may encounter an OpenAI error asking you to “verify your organization.” To resolve this, you can go through the verification process here:
- [OpenAI developer platform - Organization settings](https://platform.openai.com/settings/organization/general)

### Setup 🛠️

1. **Clone this repository:**

   ```bash
   git clone https://github.com/teremterem/claude-code-gpt-5-codex.git
   cd claude-code-gpt-5-codex
   ```

2. **Configure Environment Variables:**

   Copy the template file to create your `.env`:
   ```bash
   cp .env.template .env
   ```

   Edit `.env` and add your OpenAI API key:

   ```dotenv
   OPENAI_API_KEY=your-openai-api-key-here
   # Optional: only needed if you plan to use Anthropic models
   # ANTHROPIC_API_KEY=your-anthropic-api-key-here

   # Optional (see .env.template for details):
   # LITELLM_MASTER_KEY=your-master-key-here

   # Optional: specify the remaps explicitly if you need to (the values you see
   # below are the defaults - see .env.template for more info)
   # REMAP_CLAUDE_HAIKU_TO=gpt-5.1-codex-mini-reason-none
   # REMAP_CLAUDE_SONNET_TO=gpt-5-codex-reason-medium
   # REMAP_CLAUDE_OPUS_TO=gpt-5.1-reason-high

   # Some more optional settings (see .env.template for details)
   ...
   ```

3. **Run the proxy:**

   1) **EITHER via `uv`** (make sure to install [uv](https://docs.astral.sh/uv/getting-started/installation/) first):

      **OPTION 1:** Use a script for `uv`:

      ```bash
      ./uv-run.sh
      ```

      **OPTION 2:** Run via a direct `uv` command:

      ```bash
      uv run litellm --config config.yaml
      ```

   2) **OR via `Docker`** (make sure to install [Docker Desktop](https://docs.docker.com/desktop/) first):

      **OPTION 3:** Run `Docker` in the foreground:

      ```bash
      ./run-docker.sh
      ```

      **OPTION 4:** Run `Docker` in the background:

      ```bash
      ./deploy-docker.sh
      ```

      **OPTION 5:** Run `Docker` via a direct command:

      ```bash
      docker run -d \
         --name claude-code-gpt-5 \
         -p 4000:4000 \
         --env-file .env \
         --restart unless-stopped \
         ghcr.io/teremterem/claude-code-gpt-5:latest
      ```

      > **NOTE:** To run with this command in the foreground instead of the background, remove the `-d` flag.

      To see the logs, run:

      ```bash
      docker logs -f claude-code-gpt-5
      ```

      To stop and remove the container, run:
      ```bash
      ./kill-docker.sh
      ```

      > **NOTE:** The `Docker` options above will pull the latest image from `GHCR` and will ignore all your local files except `.env`. For more detailed `Docker` deployment instructions and more options (like building `Docker` image from source yourself, using `Docker Compose`, etc.), see [docs/DOCKER_TIPS.md](docs/DOCKER_TIPS.md)

### Using with Claude Code 🎮

1. **Install Claude Code** (if you haven't already):

   ```bash
   npm install -g @anthropic-ai/claude-code
   ```

2. **Connect it to the proxy:**

   ```bash
   ANTHROPIC_BASE_URL=http://localhost:4000 claude
   ```

   If you set `LITELLM_MASTER_KEY` in your `.env` file (see `.env.template` for details), pass it as the Anthropic API key for the CLI:
   ```bash
   ANTHROPIC_API_KEY="<LITELLM_MASTER_KEY>" \
   ANTHROPIC_BASE_URL=http://localhost:4000 \
   claude
   ```

   > **NOTE:** In this case, if you've previously authenticated, run `claude /logout` first.

**That's it!** Your Claude Code client will now use the **OpenAI models** that this repo recommends by default (unless you explicitly specified different choices in your `.env` file). 🎯

---

### Model aliases

You can find the full list of available OpenAI models in the [OpenAI API documentation](https://platform.openai.com/docs/models). Additionally, this proxy allows you to control the reasoning effort level for each model by appending it to the model name following the pattern `-reason-<effort>` (or `-reasoning-<effort>`, if you prefer). Here are some examples:

- `gpt-5.1-codex-mini-reason-none`
- `gpt-5.1-codex-mini-reason-medium`
- `gpt-5.1-codex-mini-reason-high`

If you don't specify the reasoning effort level (i.e. only specify the model name, like `gpt-5.1-codex-mini`), it will use the default level for the model.

> **NOTE:** Theoretically, you can use arbitrary models from [arbitrary providers](https://docs.litellm.ai/docs/providers), but for providers other than OpenAI or Anthropic, you will need to specify the provider as a prefix in the model name, e.g. `gemini/gemini-pro`, `gemini/gemini-pro-reason-disable` etc. (as well as set the respective API key for that provider in your `.env` file).

## KNOWN PROBLEM

The `Web Search` tool currently does not work with this setup. You may see an error like:

```text
API Error (500 {"error":{"message":"Error calling litellm.acompletion for non-Anthropic model: litellm.BadRequestError: OpenAIException - Invalid schema for function 'web_search': 'web_search_20250305' is not valid under any of the given schemas.","type":"None","param":"None","code":"500"}}) · Retrying in 1 seconds… (attempt 1/10)
```

This is planned to be fixed soon.

> **NOTE:** The `Fetch` tool (getting web content from specific URLs) is not affected and works normally.

## P. S. You are welcome to join our [MiniAgents Discord Server 👥](https://discord.gg/ptSvVnbwKt)

## And if you like the project, please give it a Star 💫

<p align="center">
<a href="https://www.star-history.com/#teremterem/claude-code-gpt-5-codex&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=teremterem/claude-code-gpt-5-codex&type=date&theme=dark&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=teremterem/claude-code-gpt-5-codex&type=date&legend=top-left" />
   <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=teremterem/claude-code-gpt-5-codex&type=date&legend=top-left" />
 </picture>
</a>
</p>
