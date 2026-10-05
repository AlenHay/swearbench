"""Turn labels into leaderboards."""
from __future__ import annotations

import random
import re
from collections import Counter, defaultdict

MODE_WEIGHT = {
    "fabrication": 3, "overreach": 3, "giving_up": 3, "regression": 2.5,
    "ignored": 2, "repeat": 2, "incomplete": 1.5, "insult": 1.5,
    "profanity": 1, "shouting": 0.5, "sarcasm": 0.5, "slow": 0.5,
}
INTERRUPT_RAGE = 1.5
SWEAR = re.compile(r"\b(fuck\w*|shit\w*|wtf|damn\w*|crap\w*|bullshit|stupid|idiot\w*|dumb\w*|moron\w*|"
                   r"bitch\w*|asshole|sucks?)\b", re.I)


def rage(lab):
    if lab.get("agent_authored") or lab.get("target") != "model" or lab.get("anger", 0) < 1:
        return 0.0
    return lab["anger"] + sum(MODE_WEIGHT.get(m, 0) for m in lab.get("modes", []))


def _friction(rows, n_int):
    n = len(rows)
    total = sum(rage(l) for _, l in rows) + INTERRUPT_RAGE * n_int
    clean = sum(1 for _, l in rows if rage(l) == 0 and l.get("satisfaction", 0) >= 0)
    sat = sum(l.get("satisfaction", 0) for _, l in rows) / n
    rage100 = 100 * total / n
    clean_pct = 100 * clean / n
    return {
        "n": n, "friction": clean_pct - 0.5 * rage100 + 10 * sat, "clean_pct": clean_pct, "rage100": rage100,
        "angry_pct": 100 * sum(rage(l) > 0 for _, l in rows) / n, "sat": sat,
        "int100": 100 * n_int / n,
        "swears100": 100 * sum(len(SWEAR.findall(r.text)) for r, _ in rows) / n,
    }


def _landed(rows):
    last = rows[-1][1]
    return last.get("satisfaction", 0) >= 1 and rage(last) == 0


def _stats(sessions, n_int, merged):
    rows = [x for s in sessions for x in s]
    st = _friction(rows, n_int)
    st["sessions"] = len(sessions)
    st["outcome"] = 100 * sum(_landed(s) for s in sessions) / len(sessions)
    tracked = [s for s in sessions if merged["since"] and s[0][0].ts >= merged["since"]]
    st["merged_n"] = len(tracked)
    st["merged_pct"] = 100 * sum(s[0][0].session in merged["ids"] for s in tracked) / len(tracked) if tracked else None
    st["score"] = (st["friction"] + st["outcome"]) / 2
    return st


def _ci(sessions, n_int, merged, field, k=300):
    rng = random.Random(0)
    xs = sorted(_stats(rng.choices(sessions, k=len(sessions)), n_int, merged)[field] for _ in range(k))
    return xs[int(k * .05)], xs[int(k * .95)]


def modes_share(rows):
    c = Counter()
    for _, l in rows:
        if rage(l) > 0:
            for m in l.get("modes", []):
                c[m] += MODE_WEIGHT.get(m, 0)
    total = sum(c.values()) or 1
    return {m: c[m] / total for m in MODE_WEIGHT if c[m]}


def build(corpus, labels, min_reactions=40, exclude=()):
    per = defaultdict(list)
    for r in corpus.reactions:
        lab = labels.get(r.id)
        if lab and not lab.get("agent_authored") and r.model and r.model not in exclude:
            per[r.model].append((r, lab))
    ints = Counter(i.model for i in corpus.interrupts)

    board = []
    for model, rows in per.items():
        if len(rows) < min_reactions:
            continue
        by_session = defaultdict(list)
        for r, l in sorted(rows, key=lambda x: x[0].ts):
            by_session[r.session].append((r, l))
        sessions = list(by_session.values())
        merged = {"ids": corpus.merged, "since": corpus.pr_tracking_since}
        s = _stats(sessions, ints[model], merged)
        s["model"], s["modes"] = model, modes_share(rows)
        s["ci"] = _ci(sessions, ints[model], merged, "score")
        s["outcome_ci"] = _ci(sessions, ints[model], merged, "outcome")
        s["worst"] = [l for _, l in sorted(rows, key=lambda x: -rage(x[1]))[:3] if rage(l) > 0]
        board.append(s)
    board.sort(key=lambda s: -s["score"])

    tokens = []
    for model, rows in per.items():
        you = corpus.usage.tokens.get(model, {}).get("you")
        start = corpus.usage.first_ts.get(model)
        if not you or not you[1] or not start:
            continue
        win = [(r, l) for r, l in rows if r.ts >= start]
        if len(win) < min_reactions:
            continue
        n_int = sum(1 for i in corpus.interrupts if i.model == model and i.ts >= start)
        out_m = you[1] / 1e6
        tokens.append({
            "model": model, "out_m": out_m, "agents_out_m": corpus.usage.tokens[model].get("agents", [0, 0, 0])[1] / 1e6,
            "total_b": sum(you) / 1e9, "n": len(win),
            "rage_per_m": (sum(rage(l) for _, l in win) + INTERRUPT_RAGE * n_int) / out_m,
            "angry_per_m": sum(rage(l) > 0 for _, l in win) / out_m, "out_per_reaction": you[1] / len(win),
        })
    tokens.sort(key=lambda t: t["rage_per_m"])

    sent = set(per)
    agent_only = sorted(m for m, o in corpus.usage.tokens.items() if m not in sent)
    small = sorted((m, len(r)) for m, r in per.items() if len(r) < min_reactions)
    return {"board": board, "tokens": tokens, "agent_only": agent_only, "small": small,
            "n_reactions": sum(len(r) for r in per.values()), "n_interrupts": len(corpus.interrupts)}


def _merged_cell(s):
    return "—" if s["merged_pct"] is None else f"{s['merged_pct']:.0f}% of {s['merged_n']}"


def markdown(res, quotes=True):
    o = ["# SwearBench\n",
         f"{res['n_reactions']} of your reactions to AI replies, {res['n_interrupts']} interrupts.\n",
         "| # | Model | SwearBench ↑ | 90% CI | Lands | Friction | Sessions | Merged PR* | Reactions | Clean turns | Rage /100 turns | "
         "Angry msgs | Interrupts /100 | Swears /100 | Avg satisfaction |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for i, s in enumerate(res["board"], 1):
        o.append(f"| {i} | {s['model']} | **{s['score']:.1f}** | {s['ci'][0]:.0f}–{s['ci'][1]:.0f} | {s['outcome']:.0f}% | {s['friction']:.1f} | "
                 f"{s['sessions']} | "
                 f"{_merged_cell(s)} | {s['n']} | "
                 f"{s['clean_pct']:.0f}% | {s['rage100']:.1f} | {s['angry_pct']:.1f}% | {s['int100']:.1f} | "
                 f"{s['swears100']:.1f} | {s['sat']:+.2f} |")
    if res["tokens"]:
        o += ["\n## Per token of work\n",
              "Output tokens the model produced in sessions you drove; reactions counted from the first logged token on.\n",
              "| # | Model | Your output tok | Agent-run output tok | Your total tok | Reactions | Rage per 1M out tok ↓ | "
              "Angry msgs per 1M | Out tok per reaction |",
              "|---|---|---|---|---|---|---|---|---|"]
        for i, t in enumerate(res["tokens"], 1):
            o.append(f"| {i} | {t['model']} | {t['out_m']:.1f}M | {t['agents_out_m']:.1f}M | {t['total_b']:.2f}B | {t['n']} | "
                     f"**{t['rage_per_m']:.1f}** | {t['angry_per_m']:.1f} | {t['out_per_reaction'] / 1000:.1f}k |")
    o += ["\n## How you get mad at each model (share of rage points)\n",
          "| Model | " + " | ".join(MODE_WEIGHT) + " |", "|---|" + "---|" * len(MODE_WEIGHT)]
    for s in res["board"]:
        o.append(f"| {s['model']} | " + " | ".join(f"{100 * s['modes'][m]:.0f}%" if m in s["modes"] else "·"
                                                    for m in MODE_WEIGHT) + " |")
    if quotes:
        o.append("\n## Hall of shame\n\n> Contains your own words. Review before sharing.\n")
        for s in res["board"]:
            o.append(f"**{s['model']}**")
            o += [f"- [{l['anger']}/4, {', '.join(l.get('modes', [])) or '—'}] “{l.get('quote', '')}”" for l in s["worst"]]
            o.append("")
    if res["small"]:
        o.append("Too few reactions to rank: " + ", ".join(f"{m} ({n})" for m, n in res["small"]))
    if res["agent_only"]:
        o.append("\nOnly ever ran as subagents / headless runs (never ranked): " + ", ".join(res["agent_only"]))
    o.append("\nSwearBench = (Friction + Lands) / 2. Friction = clean-turn % − 0.5 × rage per 100 turns + 10 × avg "
             "satisfaction; rage = anger (1–4) + mode weights, only when aimed at the model; each interrupt adds 1.5. "
             "Lands = % of sessions whose last reaction accepts the work. "
             "*Merged PR is informational (T3 Code only, sessions after it started tracking PRs) and not in the score. "
             "Intervals bootstrap over sessions. See chart.svg for swearing vs. result.")
    return "\n".join(o) + "\n"
