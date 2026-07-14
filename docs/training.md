# Train — fine-tune your own models (TrainForge)

AgentOS's Train pillar is **TrainForge**: a self-hosted training platform that AgentOS manages
as a local service and embeds as the **Train** desktop app. Everything happens on your
machine — datasets, training, evaluation, weights. Nothing leaves unless *you* publish it.

## Starting it

Three ways, pick any:

- Open the **Train** app and click **Start TrainForge**.
- Ask the agent: *"start the training service"* (the `trainforge_service` tool).
- It starts implicitly when you ask for training work: *"fine-tune a model on my notes"*.

AgentOS always binds TrainForge to `127.0.0.1` (it has no auth of its own) on port `8377`.
Configure the checkout location and port in `config.json` under `trainforge`
(auto-detected when the `doneitrightai` project sits in a known location).

## What you can do

| Capability | In the Train app | By asking the agent |
|---|---|---|
| Find & import datasets | Datasets tab (HF Hub search, URL, upload) | `train_datasets` — *"import the imdb dataset, cap 2000 rows"* |
| Train / fine-tune | New Job form (hyperparameters auto-tuned) | `train_job` — *"train a text classifier on dataset 3"* |
| **LoRA fine-tune an LLM** | task `causal-lm` | *"LoRA-fine-tune qwen-0.5b on my Q&A pairs"* |
| Watch progress | live loss charts + streaming logs | `train_job action=logs/metrics` |
| Evaluate | built-in playground; every model is a live endpoint | `train_model action=predict` |
| Publish | one click → Hugging Face Hub | `train_model action=publish` |
| Full auto | **Autopilot**: goal → dataset → train → register | `train_autopilot` — *"train a sentiment model for movie reviews"* |

Training jobs are isolated OS processes: stoppable, crash-safe, one at a time on a single GPU.
TrainForge coordinates VRAM with Ollama automatically — it pauses resident chat models before
a run and reloads them after, so training and your agent share one GPU politely.

## The loop that matters

The differentiating story of an agentic OS that trains: **teach your agent in weights, not
just memory.**

1. Collect examples — conversations, corrections, domain documents — into a dataset
   (CSV/JSONL import, or exported from your workspace by the agent).
2. `causal-lm` LoRA fine-tune on a small base model (a 0.5–8B model trains comfortably on a
   16 GB consumer GPU).
3. Evaluate against the live endpoint (`train_model action=predict`) until it behaves.
4. Export to Ollama (GGUF) and select it in **Settings → default model** — your agent now
   *runs on the model you trained*.
5. Memory keeps handling facts; the fine-tune handles tone, format, and domain reflexes.

## Approval & safety

- Starting/checking the service, listing, and predicting are **safe** (no prompt).
- Importing external datasets, launching training runs, and Autopilot are **approval-gated**
  (they download data / occupy the GPU for a long time).
- Publishing to the Hub is **approval-gated** (it leaves the machine).
