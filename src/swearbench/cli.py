"""swearbench: rank AI coding models by how much you got mad at them."""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import card, chart, judge, score, sources


def main(argv=None):
    ap = argparse.ArgumentParser(prog="swearbench", description=__doc__)
    ap.add_argument("--judge", choices=["claude-cli", "codex-cli", "anthropic", "openai", "command"],
                    help="who labels your messages (default: first available of claude, codex, ANTHROPIC_API_KEY, OPENAI_API_KEY)")
    ap.add_argument("--judge-model", help="model id for the judge backend")
    ap.add_argument("--judge-cmd", help="with --judge command: shell command that reads a prompt on stdin and prints the reply")
    ap.add_argument("--since", help="only reactions on/after this date (YYYY-MM-DD)")
    ap.add_argument("--min-reactions", type=int, default=40, help="reactions a model needs to be ranked (default 40)")
    ap.add_argument("--exclude", action="append", default=[], help="model id to leave out (repeatable)")
    ap.add_argument("--no-t3", action="store_true", help="ignore T3 Code's database even if present")
    ap.add_argument("--no-quotes", action="store_true", help="leave the hall of shame out of report.md")
    ap.add_argument("--out", default="swearbench-out", help="output directory (default ./swearbench-out)")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--dry-run", action="store_true", help="show what was found and what would be judged, then stop")
    ap.add_argument("-y", "--yes", action="store_true", help="don't ask before sending messages to the judge")
    a = ap.parse_args(argv)

    corpus = sources.collect(use_t3=not a.no_t3, exclude_dirs=["swearbench"])
    if a.since:
        corpus.reactions = [r for r in corpus.reactions if r.ts >= a.since]
        corpus.interrupts = [i for i in corpus.interrupts if i.ts >= a.since]
    print("Found: " + ("; ".join(corpus.found) or "no logs"), file=sys.stderr)
    if not corpus.reactions:
        print("No human messages found. Supported: Claude Code, Codex, OpenCode, T3 Code.", file=sys.stderr)
        return 1

    backend = a.judge or judge.detect_backend()
    if not backend:
        print("No judge available: install claude or codex CLI, or set ANTHROPIC_API_KEY / OPENAI_API_KEY, "
              "or use --judge command --judge-cmd '...'.", file=sys.stderr)
        return 1
    model = a.judge_model or judge.DEFAULT_MODELS.get(backend)
    cached = judge.load_cache()
    todo = len({judge.key(r) for r in corpus.reactions} - set(cached))
    print(f"{len(corpus.reactions)} messages from you; {todo} not judged yet. Judge: {backend}"
          f"{' / ' + model if model else ''}.", file=sys.stderr)
    if a.dry_run:
        return 0
    if todo and not a.yes:
        if input(f"Send {todo} of your messages (with the AI reply each one answers) to the judge? [y/N] ").lower() != "y":
            return 1

    labels = judge.label(corpus.reactions, backend, model, a.judge_cmd, workers=a.workers)
    res = score.build(corpus, labels, a.min_reactions, set(a.exclude))
    family = (model or backend).split("-")[0]
    if any(s["model"].startswith(family) for s in res["board"]):
        print(f"Note: the judge ({model or backend}) is from a family being ranked. "
              "Try a different --judge to check it isn't playing favourites.", file=sys.stderr)

    os.makedirs(a.out, exist_ok=True)
    report = score.markdown(res, quotes=not a.no_quotes)
    with open(os.path.join(a.out, "report.md"), "w") as f:
        f.write(report)
    with open(os.path.join(a.out, "card.svg"), "w") as f:
        f.write(card.svg(res))
    with open(os.path.join(a.out, "chart.svg"), "w") as f:
        f.write(chart.svg(res))
    with open(os.path.join(a.out, "results.json"), "w") as f:
        json.dump({k: v for k, v in res.items()}, f, indent=1, default=str)
    print(report.split("\n## ")[0])
    print(f"Wrote {a.out}/report.md, card.svg, chart.svg, results.json", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
