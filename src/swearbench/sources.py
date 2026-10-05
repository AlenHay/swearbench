"""Readers for local agent logs. Each yields human reactions, interrupts and token usage."""
from __future__ import annotations

import glob
import json
import os
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field

HOME = os.path.expanduser("~")


@dataclass
class Reaction:
    id: str
    source: str
    session: str
    ts: str
    text: str
    prev_reply: str
    model: str


@dataclass
class Interrupt:
    source: str
    session: str
    ts: str
    model: str


@dataclass
class Usage:
    """Per model and origin ("you" = sessions a human drove, "agents" = subagents/headless runs)."""
    tokens: dict = field(default_factory=lambda: defaultdict(lambda: defaultdict(lambda: [0, 0, 0])))
    first_ts: dict = field(default_factory=dict)

    def add(self, model, origin, ts, inp, out, cache):
        model = norm(model)
        t = self.tokens[model][origin]
        t[0] += inp
        t[1] += out
        t[2] += cache
        if origin == "you" and ts and (model not in self.first_ts or ts < self.first_ts[model]):
            self.first_ts[model] = ts


@dataclass
class Corpus:
    reactions: list = field(default_factory=list)
    interrupts: list = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    found: list = field(default_factory=list)
    merged: set = field(default_factory=set)
    pr_tracking_since: str | None = None


def norm(model):
    if not model:
        return None
    model = model.strip().lower()
    if model.startswith("claude-"):
        model = model.replace(".", "-")
    return model


def ms_to_iso(ms):
    import datetime
    return datetime.datetime.fromtimestamp(ms / 1000, datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def _jsonl(path):
    with open(path, errors="replace") as f:
        for line in f:
            try:
                yield json.loads(line)
            except ValueError:
                continue


def _ro(path):
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


# --- Claude Code -----------------------------------------------------------------------------

HEADLESS_ENTRYPOINTS = {"sdk-cli", "sdk-py"}


def _claude_text(content):
    if isinstance(content, str):
        return content
    if any(isinstance(p, dict) and p.get("type") == "tool_result" for p in content):
        return None
    parts = [p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"]
    return "\n".join(parts) if parts else None


def read_claude(corpus, root, skip_session=lambda entrypoint: False, exclude_dirs=()):
    files = glob.glob(os.path.join(root, "**", "*.jsonl"), recursive=True)
    if not files:
        return
    corpus.found.append(f"Claude Code: {len(files)} transcripts")
    for path in files:
        excluded = any(d in path for d in exclude_dirs)
        subagent = "/subagents/" in path
        entrypoint = None
        model = None
        reply = ""
        usage = {}
        pending = []
        for d in _jsonl(path):
            kind = d.get("type")
            msg = d.get("message") or {}
            if kind == "assistant":
                if msg.get("model") and msg["model"] != "<synthetic>":
                    model = msg["model"]
                    if msg.get("usage"):
                        usage[msg.get("id") or d.get("uuid")] = (model, msg["usage"], d.get("isSidechain"), d.get("timestamp"))
                text = _claude_text(msg.get("content") or [])
                if text and text.strip():
                    reply = text
            elif kind == "user" and not d.get("isSidechain") and not d.get("isMeta"):
                entrypoint = entrypoint or d.get("entrypoint")
                text = _claude_text(msg.get("content") or "")
                if not text or d.get("promptSource") == "system":
                    continue
                text = text.strip()
                if text.startswith("[Request interrupted by user"):
                    if model:
                        corpus.interrupts.append(Interrupt("claude", path, d.get("timestamp", ""), norm(model)))
                    continue
                if text.startswith(("<", "Caveat:")) or not model:
                    continue
                pending.append(Reaction(d.get("uuid", ""), "claude", path, d.get("timestamp", ""), text,
                                        reply[-900:], norm(model)))
                reply = ""
        headless = entrypoint in HEADLESS_ENTRYPOINTS
        human = not (subagent or headless or excluded)
        if human and not skip_session(entrypoint):
            corpus.reactions += pending
        for model_id, u, side, ts in usage.values():
            if excluded:
                continue
            origin = "you" if human and not side else "agents"
            corpus.usage.add(model_id, origin, ts, u.get("input_tokens", 0), u.get("output_tokens", 0),
                             u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0))


# --- Codex -------------------------------------------------------------------------------------

def read_codex(corpus, root, skip_originator=lambda originator: False):
    files = glob.glob(os.path.join(root, "**", "*.jsonl"), recursive=True)
    if not files:
        return
    corpus.found.append(f"Codex: {len(files)} sessions")
    for path in files:
        human, skip, model, reply = False, False, None, ""
        for d in _jsonl(path):
            p = d.get("payload") or {}
            kind = d.get("type")
            if kind == "session_meta":
                source = p.get("source")
                human = isinstance(source, str) and source != "exec" and p.get("originator") != "codex_exec"
                skip = skip_originator(p.get("originator") or "")
            elif kind == "turn_context":
                model = p.get("model") or model
            elif kind == "event_msg":
                t = p.get("type")
                if t == "agent_message":
                    reply = p.get("message") or reply
                elif t == "user_message" and human and not skip and model:
                    text = (p.get("message") or "").strip()
                    if text and not text.startswith("<"):
                        corpus.reactions.append(Reaction(f"{path}:{d.get('timestamp')}", "codex", path,
                                                         d.get("timestamp", ""), text, reply[-900:], norm(model)))
                    reply = ""
                elif t == "turn_aborted" and human and not skip and model:
                    corpus.interrupts.append(Interrupt("codex", path, d.get("timestamp", ""), norm(model)))
                elif t == "token_count" and model and (p.get("info") or {}).get("last_token_usage"):
                    u = p["info"]["last_token_usage"]
                    cached = u.get("cached_input_tokens", 0)
                    corpus.usage.add(model, "you" if human else "agents", d.get("timestamp"),
                                     u.get("input_tokens", 0) - cached, u.get("output_tokens", 0), cached)


# --- OpenCode ----------------------------------------------------------------------------------

def read_opencode(corpus, db, skip_sessions=frozenset()):
    if not os.path.exists(db):
        return
    c = _ro(db)
    try:
        sessions = dict(c.execute("select id, parent_id from session"))
    except sqlite3.Error:
        return
    corpus.found.append(f"OpenCode: {len(sessions)} sessions")
    texts = defaultdict(list)
    for mid, data in c.execute("select message_id, data from part order by time_created"):
        p = json.loads(data)
        if p.get("type") == "text" and not p.get("synthetic"):
            texts[mid].append(p.get("text", ""))
    state = {}
    for mid, sid, created, data in c.execute(
            "select id, session_id, time_created, data from message order by session_id, time_created"):
        d = json.loads(data)
        model, reply = state.get(sid, (None, ""))
        human = sessions.get(sid) is None
        ts = ms_to_iso(created)
        text = "\n".join(texts.get(mid, [])).strip()
        if d.get("role") == "assistant":
            model = "opencode/" + d.get("modelID", "?")
            t = d.get("tokens") or {}
            corpus.usage.add(model, "you" if human else "agents", ts, t.get("input", 0),
                             t.get("output", 0) + t.get("reasoning", 0), (t.get("cache") or {}).get("read", 0))
            if (d.get("error") or {}).get("name") == "MessageAbortedError" and human and sid not in skip_sessions:
                corpus.interrupts.append(Interrupt("opencode", sid, ts, norm(model)))
            state[sid] = (model, text or reply)
        elif d.get("role") == "user":
            if human and model and text and sid not in skip_sessions:
                corpus.reactions.append(Reaction(mid, "opencode", sid, ts, text, reply[-900:], norm(model)))
            state[sid] = (model, "")


# --- T3 Code (optional; gives exact per-turn model attribution across providers) ----------------

def t3_db():
    base = os.path.join(HOME, ".config", "t3", "userdata")
    for name in ("statev2.sqlite", "state.sqlite"):
        path = os.path.join(base, name)
        if os.path.exists(path):
            return path
    return None


def t3_provider_sessions(db):
    out = defaultdict(set)
    for provider, cursor in _ro(db).execute("select provider_name, resume_cursor_json from provider_session_runtime"):
        cur = json.loads(cursor or "{}")
        out[provider].add(cur.get("sessionId") or cur.get("threadId"))
    return out


def read_t3(corpus, db):
    c = _ro(db)
    children = {r[0] for r in c.execute("select child_thread_id from orchestration_v2_projection_subagents "
                                        "where child_thread_id is not null")} if _has(c, "orchestration_v2_projection_subagents") else set()
    turn_model = {}
    for mid, payload in c.execute("select json_extract(payload_json,'$.messageId'), payload_json from orchestration_events "
                                  "where event_type='thread.turn-start-requested'"):
        turn_model[mid] = (json.loads(payload).get("modelSelection") or {}).get("model")
    by_thread = defaultdict(list)
    for mid, tid, role, text, ts in c.execute("select message_id, thread_id, role, text, created_at from projection_thread_messages "
                                              "where role in ('user','assistant') order by created_at"):
        if tid not in children:
            by_thread[tid].append((mid, role, text or "", ts))
    corpus.found.append(f"T3 Code: {len(by_thread)} threads")
    sent = defaultdict(list)
    for tid, msgs in by_thread.items():
        current, reply = None, ""
        for mid, role, text, ts in msgs:
            if role == "assistant":
                reply = text if text.strip() else reply
                continue
            if current and text.strip():
                corpus.reactions.append(Reaction(mid, "t3", tid, ts, text.strip(), reply[-900:], norm(current)))
            current = turn_model.get(mid) or current
            sent[tid].append((ts, current))
            reply = ""
    if _has(c, "projection_thread_pull_requests"):
        corpus.merged |= {tid for tid, state in c.execute(
            "select thread_id, json_extract(snapshot_json,'$.state') from projection_thread_pull_requests") if state == "merged"}
        corpus.pr_tracking_since = c.execute("select min(linked_at) from projection_thread_pull_requests").fetchone()[0]
    for tid, ts in c.execute("select json_extract(payload_json,'$.threadId'), occurred_at from orchestration_events "
                             "where event_type='thread.turn-interrupt-requested'"):
        before = [m for t, m in sent.get(tid, []) if t <= ts]
        if before and before[-1]:
            corpus.interrupts.append(Interrupt("t3", tid, ts, norm(before[-1])))


def _has(c, table):
    return c.execute("select 1 from sqlite_master where name=?", (table,)).fetchone() is not None


def collect(use_t3=True, exclude_dirs=()):
    corpus = Corpus()
    db = t3_db() if use_t3 else None
    t3_sessions = t3_provider_sessions(db) if db else {}
    if db:
        read_t3(corpus, db)
    read_claude(corpus, os.path.join(HOME, ".claude", "projects"),
                skip_session=(lambda ep: ep == "sdk-ts") if db else (lambda ep: False), exclude_dirs=exclude_dirs)
    read_codex(corpus, os.path.join(HOME, ".codex", "sessions"),
               skip_originator=(lambda o: "t3" in o.lower()) if db else (lambda o: False))
    read_opencode(corpus, os.path.join(HOME, ".local", "share", "opencode", "opencode.db"),
                  skip_sessions=frozenset(t3_sessions.get("opencode", ())))
    return corpus
