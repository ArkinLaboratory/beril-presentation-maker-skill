---
name: beril-presentation-maker
description: Drafts evidence-grounded scientific presentations (talks + posters) from a BERDL analysis project, in KBase brand. Reuses project figures; generates illustrative diagrams procedurally or via opt-in CBORG-Gemini image-gen. Produces speaker notes, Q&A prep, citation pool, and an audit trail of every claim. Hands off to harsh review and revises iteratively.
---

# BERIL Presentation Maker — v0.1.0-spec stub

This SKILL.md is a placeholder for the v0.1.0-spec release.

The full skill content (slash-command registry, prompt invocation
contract, slide-shape vocabulary, stage descriptions) lands with
implementation. Refer to:

- [SPEC.md](../../../../SPEC.md) — what and why (~700 lines)
- [LAYOUT.md](../../../../LAYOUT.md) — shape, CLI, output tree
- [DECISIONS.md](../../../../DECISIONS.md) — numbered rationale

## Commands (planned)

```
/beril-presentation-maker [<project_id>] [--mode talk-30|talk-15|talk-45|lightning-5|poster-h|poster-v]
                          [--throughline auto|interactive]
                          [--depth quick|standard|deep]
                          [--ai-diagrams off|opt-in]
                          [--no-adversarial]

/beril-presentation-maker-continue <draft_dir>
/beril-presentation-maker-assemble <draft_dir> [--format pptx|pdf]
```

Defaults: `--mode talk-30`, `--throughline interactive`,
`--depth standard`, `--ai-diagrams off`, adversarial review ON if
`beril-adversarial` is on PATH (else inline fallback reviewer).

## Status

v0.1.0-spec — read SPEC.md before commenting on design. Implementation
PRs land per LAYOUT.md.
