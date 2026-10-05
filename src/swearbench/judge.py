"""LLM judge: labels each reaction with anger, anger modes and satisfaction. Results are cached on disk."""
from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from concurrent.futures import ThreadPoolExecutor

RUBRIC_VERSION = "1"
CACHE = os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")), "swearbench", "labels.jsonl")

RUBRIC = """You are labelling a developer's chat messages to AI coding agents, to measure how frustrated
the developer was with the AI. Each item has `prev` (tail of the AI's last reply) and `msg` (the
developer's next message). Judge `msg` as a reaction to the AI's work.

Return ONLY a JSON array, one object per item, same order:
{"id": str,
 "agent_authored": bool,   // msg is clearly written by another AI/agent (long structured brief, "You are...", tool-dispatch prose), not a human
 "anger": 0-4,             // 0 calm/neutral, 1 mild annoyance, 2 clearly irritated, 3 angry, 4 furious
 "target": "model"|"external"|"self"|"none",  // who the frustration is aimed at; tools/vendors/infra/third parties = external
 "modes": [..],            // zero or more, only when target=="model":
    // "profanity"  swearing directed at the work or the model
    // "insult"     calling the model stupid/useless/lazy/idiot etc.
    // "shouting"   caps, !!!, ??? for emphasis
    // "repeat"     had to repeat an instruction / "I already told you" / "again"
    // "ignored"    model ignored or violated an explicit instruction or rule
    // "fabrication" model claimed success/facts that were false, hallucinated, lied
    // "incomplete" lazy, half-done, stopped early, left TODOs, didn't verify
    // "regression" model broke something that worked
    // "overreach"  did unrequested/destructive things, scope creep, touched what it shouldn't
    // "slow"       too slow, too many questions, too verbose, wasted time
    // "sarcasm"    sarcastic/passive-aggressive phrasing
    // "giving_up"  abandons the model/approach, "I'll do it myself", "forget it", threatens to switch
 "satisfaction": -2..2,    // -2 rejects the work, -1 wants fixes, 0 neutral/new task, 1 accepts, 2 explicit praise/delight
 "quote": str              // <=80 char excerpt that best shows the anger (or "" if anger==0)
}
Profanity used positively ("fucking cool") is not anger. Terse instructions are not anger. A new
unrelated task after a reply implies mild acceptance (satisfaction 0 or 1), not anger.

ITEMS:
"""

DEFAULT_MODELS = {"claude-cli": "claude-sonnet-5-5", "codex-cli": None, "anthropic": "claude-sonnet-5-5", "openai": "gpt-5.5"}


def key(r):
    return hashlib.sha1(f"{RUBRIC_VERSION}\0{r.prev_reply[-500:]}\0{r.text[:1500]}".encode()).hexdigest()


def load_cache():
    out = {}
    if os.path.exists(CACHE):
        with open(CACHE) as f:
            for line in f:
                try:
                    d = json.loads(line)
                    out[d["key"]] = d
                except (ValueError, KeyError):
                    pass
    return out


def detect_backend():
    if shutil.which("claude"):
        return "claude-cli"
    if shutil.which("codex"):
        return "codex-cli"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    return None


def _post(url, headers, body):
    req = urllib.request.Request(url, json.dumps(body).encode(), {"content-type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.loads(r.read())


def call(backend, model, cmd, prompt):
    if backend == "command":
        return subprocess.run(shlex.split(cmd), input=prompt, capture_output=True, text=True, timeout=900).stdout
    if backend == "claude-cli":
        args = ["claude", "-p", "--tools", ""] + (["--model", model] if model else [])
        return subprocess.run(args, input=prompt, capture_output=True, text=True, timeout=900).stdout
    if backend == "codex-cli":
        with tempfile.NamedTemporaryFile("r", suffix=".txt") as out:
            args = ["codex", "exec", "--skip-git-repo-check", "--sandbox", "read-only", "-o", out.name]
            subprocess.run(args + (["-m", model] if model else []) + ["-"], input=prompt,
                           capture_output=True, text=True, timeout=900)
            return out.read()
    if backend == "anthropic":
        r = _post("https://api.anthropic.com/v1/messages",
                  {"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"},
                  {"model": model, "max_tokens": 16000, "messages": [{"role": "user", "content": prompt}]})
        return "".join(b.get("text", "") for b in r["content"])
    if backend == "openai":
        r = _post("https://api.openai.com/v1/chat/completions",
                  {"authorization": "Bearer " + os.environ["OPENAI_API_KEY"]},
                  {"model": model, "messages": [{"role": "user", "content": prompt}]})
        return r["choices"][0]["message"]["content"]
    raise ValueError(f"unknown judge backend {backend}")


def _label_batch(batch, backend, model, cmd):
    items = [{"id": str(i), "prev": r.prev_reply[-500:], "msg": r.text[:1500]} for i, r in enumerate(batch)]
    prompt = RUBRIC + json.dumps(items, ensure_ascii=False)
    err = "unparseable output"
    for _ in range(3):
        try:
            txt = call(backend, model, cmd, prompt) or ""
            arr = json.loads(txt[txt.index("["):txt.rindex("]") + 1])
            got = {str(a.get("id")): a for a in arr if isinstance(a, dict)}
            if len(got) >= len(batch) * 0.9:
                return [(key(r), got[str(i)]) for i, r in enumerate(batch) if str(i) in got]
        except Exception as e:  # noqa: BLE001
            err = e
    print(f"  judge batch failed after 3 tries: {err}", file=sys.stderr)
    return []


def label(reactions, backend, model, cmd=None, batch=30, workers=8):
    cache = load_cache()
    todo = [r for r in {key(r): r for r in reactions}.values() if key(r) not in cache]
    if todo:
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        batches = [todo[i:i + batch] for i in range(0, len(todo), batch)]
        print(f"Judging {len(todo)} new messages in {len(batches)} batches with {backend}"
              f"{' / ' + model if model else ''} ...", file=sys.stderr)
        with open(CACHE, "a") as f, ThreadPoolExecutor(workers) as ex:
            for n, res in enumerate(ex.map(lambda b: _label_batch(b, backend, model, cmd), batches), 1):
                for k, lab in res:
                    lab = {**lab, "key": k, "judge": f"{backend}:{model or 'default'}"}
                    cache[k] = lab
                    f.write(json.dumps(lab, ensure_ascii=False) + "\n")
                f.flush()
                print(f"  {n}/{len(batches)}", file=sys.stderr)
    return {r.id: cache[key(r)] for r in reactions if key(r) in cache}
