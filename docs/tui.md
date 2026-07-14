# The TUI — AgentOS in a terminal

`agentos tui` runs a full-screen terminal UI (Textual) — the same OS, over SSH or on a
machine without a browser. If Textual isn't installed it falls back to a plain REPL
(`clitui`) with the same chat + approval flow.

```bash
uv run agentos tui        # or just: agentos tui (installed package)
```

The TUI talks to the same server and the same WebSocket event stream as the browser desktop,
so conversations, memory, approvals, and running turns are shared across every surface — a
turn you start in the TUI streams into the browser too, and vice versa.

## Tabs

| Tab | What it does |
|---|---|
| **Chat** | Talk to the agent — replies stream live (line by line), tool calls and failures shown inline, approval prompts pop as modals |
| **System** | Live CPU/RAM bars and processes |
| **Models** | Installed Ollama models, GPU state, switch the active model |
| **Apps** | Launch native desktop applications |
| **Tasks** | Scheduled jobs and their last results |
| **Team** | Subagents & workflow observability |
| **Logs** | The system log, live |
| **Docs** | This manual, rendered in the terminal |
| **Config** | Providers, autonomy, agent name |

## Notes

- Chat streams incrementally and shows model heartbeats ("waiting for the model — 20s…")
  while a local model loads or evaluates a long prompt, plus failed tool calls in red.
- Approvals raised anywhere (including Telegram or the browser) can be answered from the TUI.
- The TUI auto-starts the server if it isn't already running — and respects an existing one
  (the port-conflict guard means it never fights another instance).
