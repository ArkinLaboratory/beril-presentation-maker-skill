"""chrome.py — CRAFT output-signature renderer (Cycle-4, DP6).

The canonical reference renderer. Each CRAFT skill VENDORS a byte-identical
copy of this file (Family-F conformance), so it MUST stay dependency-free
(stdlib only) — no `wcwidth`, no `rich`. The presmaker shell shells out to
its own vendored copy per banner; the Python skills import theirs.

Two facts shape the design (proven in the Cycle-4 Phase-0 harness):

1. **Inside Claude, the message body is the legible signal, not this box.**
   The orchestrator's stdout is captured from a non-TTY subprocess and the
   transcript folds long output, so the rendered box is bare-terminal chrome
   + a data source. The SKILL.md contract has Claude RE-RENDER the structured
   contracts (run-record / decision.v1) as message text. This module produces
   the bare-terminal signature AND is the shared vocabulary (glyphs, labels,
   classes) both surfaces read from.

2. **The signature is structural, not chromatic.** Color is absent or garbage
   exactly where it would matter (non-TTY capture). So box-drawing + glyph +
   skill-ID label carry the whole distinction; color is a TTY-only bonus via
   the single `_color()` seam.

Four output classes (brief Pillar 1):
  STAGE    — boxed banner, single rule. Per-stage progress (from run-record).
  DECISION — boxed block, DOUBLE rule (most prominent). A decision.v1 with
             options shown COMPLETELY.
  RESULT   — terse one-liner (glyph + facts), no box.
  NOISE    — NOT rendered to stdout; `note_noise()` appends to an audit log
             (audit/orchestrator.log). Half the "distinct from noise" win.

Alignment: padding is by DISPLAY WIDTH (`_display_width`), not `len()`. The
signature is glyph-heavy (◆ ★ · Δ — ✎ ⚔) and the box-drawing chars are all
East-Asian "Ambiguous" width; len()-padding misaligns the right border in any
terminal that renders those as 2 cells. `_display_width` is a compact,
stdlib-only (unicodedata) wcwidth: 0 for combining/zero-width, 2 for true
Wide/Fullwidth, 1 otherwise (Ambiguous treated as 1 — the modern-terminal
default, which keeps our box-drawing at 1 cell so borders align in the common
case while genuinely-wide content e.g. CJK in option detail still pads right).
"""
from __future__ import annotations

import os
import sys
import unicodedata
from pathlib import Path

# --- Per-skill signature: glyph + label. "Which skill is talking" at a
# glance. UTF-8; Family-F pins these byte-identical across skills.
_SKILL_SIG = {
    "presentation-maker": ("◆", "presentation-maker"),
    "paper-writer":       ("✎", "paper-writer"),
    "adversarial":        ("⚔", "adversarial"),
}
_BRAND = "CRAFT"
_WIDTH = 72  # fixed inner box width; callers pre-wrap to it.


# ---------------------------------------------------------------------------
# Display width — stdlib wcwidth (no external dep, so chrome.py vendors clean)
# ---------------------------------------------------------------------------

def _char_width(ch: str) -> int:
    """Display cells for one character.
      0 — combining marks, zero-width joiners/spaces, control chars.
      2 — East-Asian Wide (W) / Fullwidth (F).
      1 — everything else (incl. Ambiguous 'A', treated as 1 = the modern
          UTF-8-terminal default; our box-drawing + glyphs are Ambiguous and
          render 1-cell there, so borders align).
    """
    if ch == "\n":
        return 0
    o = ord(ch)
    if o == 0:
        return 0
    # C0/C1 control chars render as 0 here (we never box raw controls).
    if o < 32 or 0x7F <= o < 0xA0:
        return 0
    if unicodedata.combining(ch):
        return 0
    # Explicit zero-width code points unicodedata.combining misses.
    if o in (0x200B, 0x200C, 0x200D, 0xFEFF):
        return 0
    if unicodedata.east_asian_width(ch) in ("W", "F"):
        return 2
    return 1


def _strip_ansi(s: str) -> str:
    """Drop ANSI CSI escape sequences so width is measured on visible text."""
    out, i, n = [], 0, len(s)
    while i < n:
        if s[i] == "\033":
            j = s.find("m", i)
            if j == -1:
                break
            i = j + 1
            continue
        out.append(s[i])
        i += 1
    return "".join(out)


def _display_width(s: str) -> int:
    """Visible display width of `s`, ANSI-aware + wide-char-aware."""
    return sum(_char_width(c) for c in _strip_ansi(s))


# ---------------------------------------------------------------------------
# Color seam — the ONLY place ANSI is emitted. TTY-gated + NO_COLOR-aware.
# No-op when piped / captured by a non-TTY subprocess (i.e. inside Claude),
# so structural legibility never depends on it.
# ---------------------------------------------------------------------------

_ANSI = {
    "reset": "\033[0m", "bold": "\033[1m", "dim": "\033[2m",
    "cyan": "\033[36m", "yellow": "\033[33m", "green": "\033[32m",
    "magenta": "\033[35m",
}


def _color_enabled() -> bool:
    if os.environ.get("NO_COLOR") is not None:        # https://no-color.org
        return False
    if os.environ.get("CRAFT_FORCE_COLOR") == "1":    # test/override hook
        return True
    try:
        return sys.stdout.isatty()
    except (AttributeError, ValueError):
        return False


def _color(text: str, *styles: str) -> str:
    """Wrap `text` in ANSI styles iff color is enabled; else unchanged."""
    styles = tuple(s for s in styles if s)
    if not styles or not _color_enabled():
        return text
    prefix = "".join(_ANSI.get(s, "") for s in styles)
    return f"{prefix}{text}{_ANSI['reset']}"


# ---------------------------------------------------------------------------
# Wrapping + box primitives
# ---------------------------------------------------------------------------

def _wrap(text: str, width: int) -> list[str]:
    """Greedy display-width word-wrap, preserving explicit newlines. Keeps
    the FULL text — wrapping is for legibility, never truncation."""
    if not text:
        return []
    out: list[str] = []
    for para in text.split("\n"):
        if not para:
            out.append("")
            continue
        cur, cur_w = "", 0
        for word in para.split(" "):
            ww = _display_width(word)
            if cur and cur_w + 1 + ww > width:
                out.append(cur)
                cur, cur_w = word, ww
            else:
                if cur:
                    cur += " " + word
                    cur_w += 1 + ww
                else:
                    cur, cur_w = word, ww
        if cur:
            out.append(cur)
    return out


def _rule(kind: str) -> tuple[str, str, str, str, str, str]:
    if kind == "double":
        return "╔", "╗", "╚", "╝", "═", "║"
    return "┌", "┐", "└", "┘", "─", "│"


def _box(lines: list[str], *, kind: str = "single", width: int = _WIDTH,
         accent: tuple[str, ...] = ()) -> str:
    """Render `lines` inside a FIXED-width box. Callers must pre-wrap content
    to <= width. Padding is by DISPLAY WIDTH so glyph/wide chars + color
    escapes don't push the right border."""
    tl, tr, bl, br, h, v = _rule(kind)
    inner = width + 2
    top = _color(tl + h * inner + tr, *accent)
    bot = _color(bl + h * inner + br, *accent)
    vbar = _color(v, *accent)
    out = [top]
    for s in lines:
        pad = inner - 1 - _display_width(s)
        out.append(f"{vbar} {s}{' ' * max(pad, 0)}{vbar}")
    out.append(bot)
    return "\n".join(out)


def _sig(skill: str) -> tuple[str, str]:
    return _SKILL_SIG.get(skill, ("◇", skill))


# ---------------------------------------------------------------------------
# STAGE
# ---------------------------------------------------------------------------

def render_stage(skill: str, n: int, total: int, stage: str, model: str,
                 state: str, elapsed: str, cost: str) -> str:
    """Boxed STAGE banner (single rule). Header is the signature; detail
    carries stage / model / state / elapsed / cost."""
    glyph, label = _sig(skill)
    header = f"{glyph} {_BRAND} · {label} · STAGE {n}/{total}"
    detail = f"{stage} · {model} · {state} · {elapsed} · ${cost}"
    body = [_color(hl, "bold", "cyan") for hl in _wrap(header, _WIDTH)]
    body += [_color(dl, "dim") for dl in _wrap(detail, _WIDTH)]
    return _box(body, kind="single", width=_WIDTH, accent=("cyan",))


# ---------------------------------------------------------------------------
# DECISION — double rule = most prominent class. Options shown COMPLETELY.
# ---------------------------------------------------------------------------

def render_decision(decision: dict) -> str:
    """Boxed DECISION block from a decision.v1 dict. Every option's full
    detail is rendered; no file pointer, no raw continue command (the user
    must never see the --pick flag or draft path — Claude translates a plain
    choice via the SKILL.md contract). Handles single_select / approve_reject
    / free_text kinds."""
    w = _WIDTH
    skill = decision.get("skill", "?")
    glyph, label = _sig(skill)
    gate = decision.get("gate") or decision.get("phase") or ""
    kind = decision.get("kind", "single_select")
    prompt = decision.get("prompt", "")
    options = decision.get("options") or []
    default = decision.get("default")

    lines: list[str] = []
    lines.append(_color(f"{glyph} {_BRAND} · {label} · DECISION", "bold",
                        "yellow"))
    if gate:
        lines.append(_color(f"gate: {gate}   ·   kind: {kind}", "dim"))
    lines.append("")
    for pl in _wrap(prompt, w):
        lines.append(_color(pl, "bold"))
    if prompt:
        lines.append("")

    ids: list[str] = []
    for opt in options:
        oid = opt.get("id", "?")
        ids.append(oid)
        summary = opt.get("summary", "")
        detail = opt.get("detail", "")
        is_default = (oid == default)
        marker = "★" if is_default else "•"
        for i, hl in enumerate(_wrap(f"{marker} [{oid}] {summary}", w)):
            txt = hl if i == 0 else f"    {hl}"
            lines.append(_color(txt, "bold", "green" if is_default else ""))
        for dl in _wrap(detail, w - 6):
            lines.append(f"      {dl}")
        lines.append("")

    if default is not None:
        lines.append(_color(
            f"default if you don't choose (--auto-advance): {default}", "dim"))

    if kind == "free_text":
        ask = "To answer: reply with your text."
    elif kind == "approve_reject":
        ask = "To choose: tell me approve / reject."
    else:
        ask = f"To choose: tell me {' / '.join(ids)}."
    for cl in _wrap(ask, w):
        lines.append(_color(cl, "bold", "magenta"))

    return _box(lines, kind="double", width=w, accent=("yellow",))


# ---------------------------------------------------------------------------
# RESULT — terse, no box.
# ---------------------------------------------------------------------------

def render_result(skill: str, summary: str, *, deliverable: str | None = None,
                  cost: str | None = None) -> str:
    """One-line RESULT (glyph + facts). Not a full digest."""
    glyph, label = _sig(skill)
    bits = [f"{glyph} {_BRAND} · {label} · RESULT · {summary}"]
    if cost is not None:
        bits.append(f"${cost}")
    out = _color("  ·  ".join(bits), "bold", "green")
    if deliverable:
        out += "\n" + _color(f"    → {deliverable}", "dim")
    return out


# ---------------------------------------------------------------------------
# NOISE — never to stdout; appended to the orchestrator audit log.
# ---------------------------------------------------------------------------

def note_noise(audit_dir: str | os.PathLike, message: str) -> None:
    """Append an orchestrator-internal NOISE line to
    <audit_dir>/orchestrator.log instead of stdout. Best-effort: a logging
    write must never break the run (mirrors the run-record emitter's
    non-fatal discipline). The shipped orchestrators route their
    [orchestrator] internals here so stdout carries only STAGE/DECISION/
    RESULT signal."""
    try:
        p = Path(audit_dir) / "orchestrator.log"
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(message.rstrip("\n") + "\n")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

def _demo() -> None:
    print()
    print(render_stage("presentation-maker", 5, 14, "slide_compose", "opus",
                       "running", "2m18s", "3.42"))
    print()
    print(render_stage("paper-writer", 3, 9, "drafting", "opus", "running",
                       "11m04s", "5.18"))
    print()
    demo_decision = {
        "schema_version": "decision.v1",
        "skill": "presentation-maker",
        "phase": "throughline_pick",
        "gate": "throughline_pick",
        "draft_dir": "/projects/caulobacter_fur_lipida_loss/talks/draft_3",
        "prompt": "Choose the throughline for your talk:",
        "kind": "single_select",
        "options": [
            {"id": "TL1",
             "summary": "Δfur derepression is the demonstrable driver of lipid loss",
             "detail": ("The deletion of fur derepresses the iron regulon; "
                        "the resulting iron dysregulation is the proximate, "
                        "measurable cause of the membrane-lipid collapse — "
                        "the strongest, least-dismissable claim.")},
            {"id": "TL2",
             "summary": "Lipid remodeling is an adaptive response, not damage",
             "detail": ("More novel framing, but the causal arrow is weaker "
                        "in the current data — invites the correlation "
                        "objection.")},
        ],
        "default": "TL1",
        "confirm": True,
        "continue": {"cmd": ("beril-presentation-maker continue "
                             "{draft_dir} --pick {id}")},
    }
    print(render_decision(demo_decision))
    print()
    print(render_result(
        "presentation-maker", "deck assembled · 31 slides · 14 stages",
        deliverable="deliverable/draft.pptx", cost="19.76"))
    print()


# ---------------------------------------------------------------------------
# CLI — so a shell orchestrator can emit banners from its own vendored copy.
#   python3 chrome.py stage   --skill S --n N --total T --stage NAME \
#                             --model M --state running --elapsed 2m18s --cost 3.42
#   python3 chrome.py result  --skill S --summary "..." [--deliverable P] [--cost C]
#   python3 chrome.py decision --file <decision.v1.json>      (renders to stdout)
#   python3 chrome.py noise   --audit-dir DIR --message "[orchestrator] ..."
#   python3 chrome.py --demo
# Renderers print to stdout; `noise` writes to the audit log and prints
# nothing. argparse is stdlib — chrome.py stays dependency-free (Family-F).
# ---------------------------------------------------------------------------

def _main(argv: list[str]) -> int:
    import argparse

    if "--demo" in argv:
        _demo()
        return 0

    p = argparse.ArgumentParser(prog="chrome.py", add_help=True)
    sub = p.add_subparsers(dest="cmd")

    ps = sub.add_parser("stage", help="print a STAGE banner")
    ps.add_argument("--skill", required=True)
    ps.add_argument("--n", type=int, required=True)
    ps.add_argument("--total", type=int, required=True)
    ps.add_argument("--stage", required=True)
    ps.add_argument("--model", default="")
    ps.add_argument("--state", default="running")
    ps.add_argument("--elapsed", default="")
    ps.add_argument("--cost", default="")

    pr = sub.add_parser("result", help="print a RESULT line")
    pr.add_argument("--skill", required=True)
    pr.add_argument("--summary", required=True)
    pr.add_argument("--deliverable", default=None)
    pr.add_argument("--cost", default=None)

    pd = sub.add_parser("decision", help="render a decision.v1 JSON file")
    pd.add_argument("--file", required=True)

    pn = sub.add_parser("noise", help="append an orchestrator NOISE line to the audit log")
    pn.add_argument("--audit-dir", required=True)
    pn.add_argument("--message", required=True)

    args = p.parse_args(argv)

    if args.cmd == "stage":
        print(render_stage(args.skill, args.n, args.total, args.stage,
                           args.model, args.state, args.elapsed, args.cost))
        return 0
    if args.cmd == "result":
        print(render_result(args.skill, args.summary,
                            deliverable=args.deliverable, cost=args.cost))
        return 0
    if args.cmd == "decision":
        import json
        with open(args.file, encoding="utf-8") as f:
            print(render_decision(json.load(f)))
        return 0
    if args.cmd == "noise":
        note_noise(args.audit_dir, args.message)
        return 0

    print("chrome.py — subcommands: stage | result | decision | noise | --demo",
          file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
