# Models & Appearance

---

## The brain: an executor and one of its models

Two dropdowns, next to each other in the chat window and in **Settings → AI providers**. The first
is the **executor** — who answers; the second lists only the models that executor can actually run.
The menu bar states the pair at all times, so "what is this machine running on" never needs asking.

| Executor | Who answers | Models offered |
|---|---|---|
| **Ollama** | the built-in agent, on your own machine | whatever you have pulled |
| **Anthropic · OpenAI · Google · OpenRouter** | the built-in agent, over that API | pinned + whatever the provider lists |
| **llama.cpp / LM Studio / vLLM** | the built-in agent, via the custom OpenAI-compatible URL | whatever you pinned |
| **Claude Code** | Anthropic's CLI, on your Claude subscription | `opus`, `sonnet`, `haiku`, or its own default |
| **Hermes · OpenClaw** | that agent, with its own configuration | its own |

Picking an agent as the executor makes this machine forward every turn a person starts — chat, the
prompt bar, copilot panels, Telegram, the API, scheduled turns. Apps and App Studio keep using the
built-in agent, because they depend on its tools. Each executor remembers its own model, so
switching away and back does not lose the choice.

Headless? `bento brain` prints the same list — what could answer, what it would run on, and what
would fix anything missing — and `bento brain <executor> [model]` sets it. `bento doctor` reports
the pair as one of its checks. In chat, an admin can just say *"answer with Claude Code on opus"*.

---

## Model providers

Configure providers in **Settings**. AgentOS works with local and cloud models, and you can switch
between them from the chat window's dropdowns at any time.

| Provider | Notes |
|---|---|
| **Ollama** (local) | Auto-discovered when running. Fully private — nothing leaves your machine. |
| **Anthropic** | Paste an API key; list the models you want. |
| **OpenAI** | Paste an API key; list the models you want. |
| **OpenRouter** | One key, hundreds of models (e.g. `anthropic/claude-…`, `google/gemini-…`). |
| **Custom** | Any OpenAI-compatible endpoint (LM Studio, vLLM, Groq, …) — set the base URL. |

These environment variables are picked up automatically if set: `ANTHROPIC_API_KEY`,
`OPENAI_API_KEY`, `OPENROUTER_API_KEY`.

> **Tool capability matters.** The agent works by calling tools. Choose a model that supports
> tool/function calling — any `qwen` model locally, or a cloud model. Some small local models won't
> call tools reliably.

---

## The Model Manager

The **Model Manager** app manages your local Ollama models and shows your hardware:

- **GPU** — name, VRAM used / total, and utilization (via `nvidia-smi` when available).
- **Installed models** — each with its size, parameter count, and a "loaded" indicator when running;
  delete any with one click.
- **Download** — pull a new model by name (with suggestions). Downloads run in the background and show
  live progress.

This lets you keep model choices within what your GPU can hold — for example, a ~14B model typically
needs roughly 9–10 GB of VRAM. The agent can manage models too: *"pull qwen2.5:14b," "remove buddy,"
"what models do I have?"*

---

## Themes

**Settings → Appearance** offers several themes that recolor the entire interface instantly:

- **AgentOS** (teal, default)
- **Ember** dark (warm orange accent)
- **Ember** light
- **Dracula**
- **Nord**

Your selection is remembered across sessions.

---

## Wallpapers

The **Personalize** app manages the desktop background:

- **Use system wallpaper** — adopts the current host desktop background so AgentOS matches your
  system.
- **Generate wallpaper** — creates a background from a text description using a built-in AI image
  service. Every generated image is saved to a **local gallery** you can re-apply or delete later.
- **Reset** — return to the built-in background.

The agent can set wallpapers too: *"use my system wallpaper," "change my wallpaper to a snowy forest,"
or "set my wallpaper to <a photo file or image URL>"* (the latter gives you full-resolution control).

> The built-in generator uses a free image service that caps resolution. For a crisp, full-resolution
> background, point the agent at a local photo or an image URL with `set_wallpaper`.


## Local model concurrency

Ollama runs **one request at a time per model** by default; concurrent chats are accepted by
AgentOS but queue inside Ollama. Cloud providers (Anthropic/OpenAI/OpenRouter) handle requests
in parallel — no queueing. To let Ollama serve several requests at once (VRAM permitting), set
`OLLAMA_NUM_PARALLEL=2` (and optionally `OLLAMA_MAX_LOADED_MODELS=2`) in Ollama's environment
and restart it. AgentOS's own background work (auto-learn, maintenance) always yields to live
conversations on local models, and never waits when pointed at a cloud model.
