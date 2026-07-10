# Models & Appearance

---

## Model providers

Configure providers in **⚙ Settings**. AgentOS works with local and cloud models, and you can switch
between them from the chat window's model dropdown at any time.

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

The **🧠 Model Manager** app manages your local Ollama models and shows your hardware:

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

**⚙ Settings → Appearance** offers several themes that recolor the entire interface instantly:

- **AgentOS** (teal, default)
- **Ubuntu** dark (Yaru palette, Ubuntu orange accent)
- **Ubuntu** light
- **Dracula**
- **Nord**

Your selection is remembered across sessions.

---

## Wallpapers

The **🖼 Personalize** app manages the desktop background:

- **Use Ubuntu wallpaper** — adopts the current host desktop background so AgentOS matches your
  system.
- **Generate wallpaper** — creates a background from a text description using a built-in AI image
  service. Every generated image is saved to a **local gallery** you can re-apply or delete later.
- **Reset** — return to the built-in background.

The agent can set wallpapers too: *"use my Ubuntu wallpaper," "change my wallpaper to a snowy forest,"
or "set my wallpaper to <a photo file or image URL>"* (the latter gives you full-resolution control).

> The built-in generator uses a free image service that caps resolution. For a crisp, full-resolution
> background, point the agent at a local photo or an image URL with `set_wallpaper`.
