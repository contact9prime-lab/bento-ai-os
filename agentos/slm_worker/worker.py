"""The training worker: one process per job, in the training stack's own Python.

Started by `agentos/slm.py` as `python -I -u slm_worker/worker.py <op> <dir>`. It lives in a folder of its own
because a script is run with its folder first on the import path, and beside Bento's modules
`import platform` found agentos/platform and torch could not start. It is a script on its
own: it imports nothing of Bento, because the Python that runs it is the training stack's
(torch, transformers, peft, installed on request in a folder of its own) and Bento is not
in there. Everything it is told is in `<dir>/job.json`; everything it says is in files in
that folder, which the engine reads back:

    status.json     where it is: state, step, total, error      (replaced atomically)
    metrics.jsonl   one line per logged step
    job.log         stdout and stderr (the engine wires the pipe)
    eval.json       held-back examples: what was wanted, the base model's answer, the
                    tuned model's answer, and the scores
    output/         the model (or the folder job.json names as `out`)

Ported from doneitrightai's `server/workers/tasks/causal_lm.py` (MIT, the owner's own):
the LoRA recipe is that one. Four things changed. The loss is counted on the answer only. Rows are prompt and response pairs
written with the base model's own chat template, so the result answers the way it was
trained when Ollama or transformers serves it. Some examples are held back and answered
before and after training, because "the loss went down" does not say whether it learned
the job. And the device may be Apple's GPU as well as NVIDIA's.

Ops: train, try (answer prompts with a trained model), publish (upload to Hugging Face).
"""

import json
import os
import re
import sys
import time
from pathlib import Path

TEMPLATE = "### Instruction:\n{prompt}\n\n### Response:\n"


def _write(path: Path, data) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    os.replace(tmp, path)


class Job:
    def __init__(self, folder: str):
        self.dir = Path(folder)
        self.spec = json.loads((self.dir / "job.json").read_text(encoding="utf-8"))
        self.state = {"state": "running", "step": 0, "total": 0, "phase": "starting",
                      "pid": os.getpid(), "started": time.time()}
        self._metrics = None

    def status(self, **kw):
        self.state.update(kw)
        self.state["at"] = time.time()
        _write(self.dir / "status.json", self.state)

    def say(self, text: str):
        print(f"[train] {text}", flush=True)

    def metric(self, point: dict):
        if self._metrics is None:
            self._metrics = open(self.dir / "metrics.jsonl", "a", encoding="utf-8")
        self._metrics.write(json.dumps({"time": time.time(), **point}) + "\n")
        self._metrics.flush()


def rows_of(path) -> list[dict]:
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if isinstance(r, dict) and str(r.get("prompt") or "").strip():
                out.append(r)
    return out


def messages(row: dict, system: str, answer: bool) -> list[dict]:
    msgs = []
    sys_text = str(row.get("system") or system or "").strip()
    if sys_text:
        msgs.append({"role": "system", "content": sys_text})
    msgs.append({"role": "user", "content": str(row["prompt"])})
    if answer:
        msgs.append({"role": "assistant", "content": str(row.get("response") or "")})
    return msgs


def text_of(tok, row: dict, system: str, answer: bool) -> str:
    """One example as the base model reads a conversation. A model with no chat template
    (a plain GPT-2) gets the instruction layout doneitrightai used."""
    if getattr(tok, "chat_template", None):
        try:
            return tok.apply_chat_template(messages(row, system, answer), tokenize=False,
                                           add_generation_prompt=not answer)
        except Exception:
            # some templates refuse a system turn: say it inside the question
            sys_text = str(row.get("system") or system or "").strip()
            merged = {**row, "system": "", "prompt": (sys_text + "\n\n" if sys_text else "") + str(row["prompt"])}
            return tok.apply_chat_template(messages(merged, "", answer), tokenize=False,
                                           add_generation_prompt=not answer)
    sys_text = str(row.get("system") or system or "").strip()
    head = (sys_text + "\n\n" if sys_text else "") + TEMPLATE.format(prompt=row["prompt"])
    return head + (str(row.get("response") or "") + (tok.eos_token or "") if answer else "")


# ---- scoring: counted, never judged -------------------------------------------------

def _norm(s: str) -> list[str]:
    return re.sub(r"[^\w\s]", " ", str(s or "").lower()).split()


def score(want: str, got: str) -> dict:
    """Exact (the same words, case and punctuation aside) and word overlap (F1). Two
    counts of how close an answer is to the reference; neither is a judgement of quality."""
    w, g = _norm(want), _norm(got)
    if not w or not g:
        return {"exact": int(w == g), "overlap": float(w == g)}
    left = list(w)
    same = 0
    for t in g:
        if t in left:
            left.remove(t)
            same += 1
    if not same:
        return {"exact": 0, "overlap": 0.0}
    p, r = same / len(g), same / len(w)
    return {"exact": int(w == g), "overlap": round(2 * p * r / (p + r), 4)}


def device_of(torch):
    if torch.cuda.is_available():
        return "cuda"
    mps = getattr(torch.backends, "mps", None)
    if mps is not None and mps.is_available():
        return "mps"
    return "cpu"


def encode(tok, text: str, max_length: int) -> list[int]:
    """A chat template writes its own start token into the text, so the tokenizer must not
    add a second one; a plain model gets the tokenizer's own."""
    return tok(text, truncation=True, max_length=max_length,
               add_special_tokens=not getattr(tok, "chat_template", None))["input_ids"]


def stops(tok) -> list[int]:
    """Where an answer ends: the model's end token, and the end of a chat turn."""
    ids = {tok.eos_token_id}
    for t in ("<|im_end|>", "<|end|>", "<|eot_id|>", "<end_of_turn>"):
        i = tok.convert_tokens_to_ids(t)
        if isinstance(i, int) and i >= 0 and i != tok.unk_token_id:
            ids.add(i)
    return [i for i in ids if i is not None]


def answer(torch, model, tok, rows, system, max_new, dev, tick=None) -> list[str]:
    outs = []
    model.eval()
    end = stops(tok)
    for i, row in enumerate(rows):
        ids = torch.tensor([encode(tok, text_of(tok, row, system, False), 2048)], device=dev)
        enc = {"input_ids": ids, "attention_mask": torch.ones_like(ids)}
        with torch.no_grad():
            got = model.generate(**enc, max_new_tokens=max_new, do_sample=False,
                                 pad_token_id=tok.pad_token_id, eos_token_id=end)
        outs.append(tok.decode(got[0][enc["input_ids"].shape[1]:], skip_special_tokens=True).strip())
        if tick:
            tick(i + 1)
    return outs


def load(torch, name, dev):
    from transformers import AutoModelForCausalLM, AutoTokenizer
    # never a repository's own code: a model is weights, and this runs with the person's files
    tok = AutoTokenizer.from_pretrained(name, trust_remote_code=False)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    dtype = torch.bfloat16 if (dev == "cuda" and torch.cuda.is_bf16_supported()) else torch.float32
    model = AutoModelForCausalLM.from_pretrained(name, torch_dtype=dtype, trust_remote_code=False)
    return tok, model.to(dev), dtype


def train(job: Job) -> None:
    import torch
    from peft import LoraConfig, get_peft_model
    from transformers import Trainer, TrainerCallback, TrainingArguments

    spec, hp = job.spec, job.spec["hp"]
    system = spec.get("system") or ""
    rows = rows_of(spec["data"])
    held = rows_of(spec["heldout"]) if spec.get("heldout") and os.path.exists(spec["heldout"]) else []
    if not rows:
        raise RuntimeError("The dataset has no examples with a prompt and a response.")
    dev = device_of(torch)
    job.say(f"job {spec['id']} '{spec['name']}': {len(rows)} examples to learn from, "
            f"{len(held)} held back, base {spec['base']}, device {dev}")
    if dev == "cpu":
        job.say("no GPU is visible: this runs on the processor, which only suits the smallest models")
    job.status(phase="loading the base model", device=dev)
    tok, model, dtype = load(torch, spec["base"], dev)
    max_new = int(hp.get("max_new_tokens") or 96)

    before = []
    if held:
        job.status(phase="answering the held-back examples before training", total=len(held), step=0)
        before = answer(torch, model, tok, held, system, max_new, dev, lambda n: job.status(step=n))

    model.config.use_cache = False
    lora = LoraConfig(r=int(hp["lora_r"]), lora_alpha=int(hp["lora_alpha"]), lora_dropout=0.05,
                      task_type="CAUSAL_LM", target_modules="all-linear")
    model = get_peft_model(model, lora)
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    job.say(f"LoRA: {trainable:,} of {total:,} parameters are trained ({100 * trainable / total:.2f}%)")

    class Rows(torch.utils.data.Dataset):
        """Each example with the loss on the ANSWER only. Counted over the whole text, most
        of the learning went into predicting the prompts, and a 135M model taught to sort
        mail learned the labels but not where to stop ("billing\n\nother": 6 of 24)."""
        def __init__(self, items):
            self.items = []
            limit = int(hp["max_length"])
            for r in items:
                ids = encode(tok, text_of(tok, r, system, True), limit)
                head = encode(tok, text_of(tok, r, system, False), limit)
                n = len(head) if ids[:len(head)] == head and len(head) < len(ids) else 0
                self.items.append({"input_ids": ids, "labels": [-100] * n + ids[n:]})

        def __len__(self):
            return len(self.items)

        def __getitem__(self, i):
            return self.items[i]

    data = Rows(rows)

    def collate(batch):
        width = max(len(b["input_ids"]) for b in batch)
        pad = tok.pad_token_id
        return {"input_ids": torch.tensor([b["input_ids"] + [pad] * (width - len(b["input_ids"])) for b in batch]),
                "attention_mask": torch.tensor([[1] * len(b["input_ids"]) + [0] * (width - len(b["input_ids"])) for b in batch]),
                "labels": torch.tensor([b["labels"] + [-100] * (width - len(b["labels"])) for b in batch])}

    class Tell(TrainerCallback):
        def on_train_begin(self, args, state, control, **kw):
            job.status(phase="training", total=int(state.max_steps or 0), step=0)

        def on_step_end(self, args, state, control, **kw):
            job.status(step=int(state.global_step))

        def on_log(self, args, state, control, logs=None, **kw):
            point = {k: v for k, v in (logs or {}).items() if isinstance(v, (int, float))}
            if point:
                job.metric({"step": state.global_step, "epoch": round(state.epoch or 0, 3), **point})

    args = TrainingArguments(
        output_dir=str(job.dir / "checkpoints"), num_train_epochs=float(hp["epochs"]),
        learning_rate=float(hp["learning_rate"]), per_device_train_batch_size=int(hp["batch_size"]),
        gradient_accumulation_steps=int(hp["gradient_accumulation"]),
        gradient_checkpointing=(dev == "cuda"), save_strategy="no", disable_tqdm=True, logging_steps=int(hp.get("logging_steps") or 5),
        seed=int(hp.get("seed") or 42), bf16=(dtype == torch.bfloat16), report_to=[],
        use_cpu=(dev == "cpu"), dataloader_pin_memory=(dev == "cuda"))
    trainer = Trainer(model=model, args=args, train_dataset=data,
                      data_collator=collate, callbacks=[Tell()])
    result = trainer.train()
    metrics = {"train_loss": round(float(result.training_loss), 4), "train_rows": len(rows),
               "trainable_params": trainable, "params": total, "device": dev,
               "seconds": round(time.time() - job.state["started"], 1)}

    out = Path(spec.get("out") or job.dir / "output")
    out.mkdir(parents=True, exist_ok=True)
    tuned = trainer.model
    if hp.get("merge_adapter", True):
        job.status(phase="merging the adapter into the model")
        tuned = tuned.merge_and_unload()
    tuned.config.use_cache = True
    if held:
        job.status(phase="answering the held-back examples after training", total=len(held), step=0)
        after = answer(torch, tuned, tok, held, system, max_new, dev, lambda n: job.status(step=n))
        items, b_ex, a_ex, b_ov, a_ov = [], 0, 0, 0.0, 0.0
        for row, b, a in zip(held, before, after):
            sb, sa = score(row.get("response"), b), score(row.get("response"), a)
            b_ex += sb["exact"]; a_ex += sa["exact"]; b_ov += sb["overlap"]; a_ov += sa["overlap"]
            items.append({"prompt": row["prompt"], "want": row.get("response") or "", "before": b,
                          "after": a, "exact_before": sb["exact"], "exact_after": sa["exact"],
                          "overlap_before": sb["overlap"], "overlap_after": sa["overlap"]})
        n = len(held)
        ev = {"n": n, "exact_before": b_ex, "exact_after": a_ex,
              "overlap_before": round(b_ov / n, 4), "overlap_after": round(a_ov / n, 4)}
        _write(job.dir / "eval.json", {**ev, "items": items})
        metrics["eval"] = ev
    job.status(phase="saving the model")
    tuned.save_pretrained(str(out))
    tok.save_pretrained(str(out))
    _write(out / "bento-train.json", {"base": spec["base"], "system": system, "lora_r": hp["lora_r"],
                                      "merged": bool(hp.get("merge_adapter", True)), "job": spec["id"]})
    job.status(state="done", phase="done", metrics=metrics, finished=time.time())
    job.say("done: " + json.dumps(metrics))


def try_it(job: Job) -> None:
    """Answer a few prompts with a saved model. spec: model (a folder), prompts, system."""
    import torch
    spec = job.spec
    dev = device_of(torch)
    meta = {}
    marker = Path(spec["model"]) / "bento-train.json"
    if marker.exists():
        meta = json.loads(marker.read_text(encoding="utf-8"))
    if meta and not meta.get("merged", True):
        from peft import AutoPeftModelForCausalLM
        from transformers import AutoTokenizer
        tok = AutoTokenizer.from_pretrained(spec["model"], trust_remote_code=False)
        model = AutoPeftModelForCausalLM.from_pretrained(spec["model"], trust_remote_code=False).to(dev)
    else:
        tok, model, _ = load(torch, spec["model"], dev)
    rows = [{"prompt": p} for p in spec.get("prompts") or []]
    system = spec.get("system") if spec.get("system") is not None else meta.get("system", "")
    t0 = time.time()
    outs = answer(torch, model, tok, rows, system or "", int(spec.get("max_new_tokens") or 200), dev)
    _write(job.dir / "answers.json", {"answers": outs, "seconds": round(time.time() - t0, 2), "device": dev})
    job.status(state="done", phase="done")


def publish(job: Job) -> None:
    """Upload the model's folder to the Hugging Face Hub. The token arrives in the
    environment for this one process and is written nowhere."""
    from huggingface_hub import HfApi
    spec = job.spec
    token = os.environ.get("HF_TOKEN") or ""
    if not token:
        raise RuntimeError("No Hugging Face token was given.")
    api = HfApi(token=token)
    api.create_repo(repo_id=spec["repo"], repo_type="model", private=bool(spec.get("private", True)),
                    exist_ok=True)
    api.upload_folder(folder_path=spec["model"], repo_id=spec["repo"], repo_type="model",
                      commit_message=f"Upload {spec.get('name') or 'model'} (trained with Bento Box AI)")
    job.status(state="done", phase="done", repo=spec["repo"])


OPS = {"train": train, "try": try_it, "publish": publish}


def main(argv) -> int:
    if len(argv) != 3 or argv[1] not in OPS:
        print("usage: worker.py train|try|publish <folder>", file=sys.stderr)
        return 2
    job = Job(argv[2])
    job.status()
    try:
        OPS[argv[1]](job)
        return 0
    except BaseException as e:   # a stop is a signal, and it is written down like a failure
        import traceback
        traceback.print_exc()
        stopped = isinstance(e, (KeyboardInterrupt, SystemExit))
        job.status(state="stopped" if stopped else "failed", phase="stopped" if stopped else "failed",
                   error="" if stopped else f"{type(e).__name__}: {e}"[:2000], finished=time.time())
        return 1


if __name__ == "__main__":
    import signal
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    sys.exit(main(sys.argv))
