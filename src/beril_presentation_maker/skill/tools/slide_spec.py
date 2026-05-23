#!/usr/bin/env python3
"""slide_spec.py — schema, types, and validator for slide_spec.json.

This module is the SINGLE SOURCE OF TRUTH for the slide_spec contract
that governs four downstream consumers (SPEC §14.2):

  1. assemble_pptx.py  — reads slide_spec.json → emits .pptx
  2. validate_presentation.py  — reads slide_spec.json → P1–P10 results
  3. slide_compose.v1.md  (Phase 3 prompt)  — emits slide_spec fragments
  4. revise verb  — modifies a single slide's content in place

Schema decisions (per reference/slide-spec-schema-proposal.md, sign-off
2026-04-26):

  - Hand-rolled validator (no jsonschema runtime dep). Pure stdlib.
  - 15 named layouts matching SPEC §6 vocabulary.
  - Diagram sub-schema with 7 node shapes (rectangle, rounded, ellipse,
    parallelogram, cylinder, callout, swimlane) and 3 edge kinds
    (straight, elbow, curved). Tree-style auto-layout deferred to v0.2.
  - tools_versions as list-of-objects {tool, version} (Option A).
  - revision_log on each slide (not separate audit file).
  - validator_status on each slide.

CLI usage:

    python3 slide_spec.py validate <path/to/slide_spec.json>
    python3 slide_spec.py schema-json [--out path]
    python3 slide_spec.py example <layout-name>     # print a sample

Library usage:

    from slide_spec import validate_slide_spec, ValidationError
    errors = validate_slide_spec(spec_dict)
    if errors:
        for e in errors: print(e.format())
        raise ValidationError("invalid slide_spec", errors)

Tests live at tests/unit/test_slide_spec.py.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Schema version
# ---------------------------------------------------------------------------

SCHEMA_VERSION = "1.0"


# ---------------------------------------------------------------------------
# Closed enumerations
# ---------------------------------------------------------------------------

LAYOUTS: tuple[str, ...] = (
    "title",
    "section_divider",
    "big_idea",
    "big_number",
    "claim_evidence",
    "two_column_compare",
    "data_figure",
    "data_table",                # v0.3.2: ranked tables / matrices
    "workflow_diagram",
    "methods_summary",
    "concept_illustration",
    "cross_tenant_integration",
    "implications",
    "acknowledgments",
    "references",
    "qa_anticipated",
)

MODES: tuple[str, ...] = (
    "talk-30", "talk-15", "talk-45", "lightning-5",
    "poster-h", "poster-v",
)

TIERS: tuple[str, ...] = ("STRONG", "THIN", "EXPLORATORY")

AUDIENCES: tuple[str, ...] = ("peer",)  # v1 only

VALIDATOR_STATUS: tuple[str, ...] = (
    "pass", "soft-warning", "accepted-with-warning",
    "escalated", "user-fixed", "accepted-as-limitation",
)

DIAGRAM_KINDS: tuple[str, ...] = ("boxes_and_arrows",)

DIAGRAM_NODE_SHAPES: tuple[str, ...] = (
    "rectangle", "rounded", "ellipse", "parallelogram",
    "cylinder", "callout", "swimlane",
)

DIAGRAM_EDGE_KINDS: tuple[str, ...] = ("straight", "elbow", "curved")

CONCEPT_STYLES: tuple[str, ...] = (
    # Original 3 styles (pre-v0.3.0).
    "metaphor", "infographic", "conceptual_diagram",
    # v0.3.0 calibration added these. scientific_illustration is the
    # T2-winning default per ai_image_prompt.v1.md; the other three are
    # available via STYLE_HINT override. ai_image_prompt.v1.md is the
    # source of truth for this enumeration — adding a style there
    # without updating this tuple breaks the spec validator on any
    # concept_illustration slide using the new style. (v0.3.3 smoke
    # 2026-05-03 surfaced this drift; the validator hard-rejected
    # 'scientific_illustration' even though calibration ratified it.)
    "scientific_illustration", "watercolor", "minimalist", "abstract",
)

CONCEPT_CHANNELS: tuple[str, ...] = ("A", "B")  # SPEC §8.3 two-channel


# ---------------------------------------------------------------------------
# Validator error type
# ---------------------------------------------------------------------------

@dataclass
class ValidatorIssue:
    """A single contract violation. `path` uses dotted JSON-pointer-ish
    syntax (`slides[5].content.bullets[2]`) to identify the offending location.

    M4a Tier B (DQ4): `severity` distinguishes hard-reject ("error" —
    blocks render; the v0.3.x behaviour for all issues) from advisory
    ("soft-warning" — surfaced to the assembler's warnings channel but
    does not block). The renderer's explicit-fontScale shrink-to-fit
    (Tier A) is the safety net for the new content-length caps; a
    slightly-long node label or step_caption should not fail the
    pipeline after LLM spend. Defaults to "error" so existing callsites
    keep the v0.3.x semantics.
    """
    path: str
    message: str
    severity: str = "error"   # "error" | "soft-warning"

    def format(self) -> str:
        prefix = "" if self.severity == "error" else "[soft-warning] "
        return f"{prefix}{self.path}: {self.message}"


class ValidationError(Exception):
    """Raised when slide_spec validation fails (only when caller asks for
    raise-mode; the function-level API returns a list of issues by default)."""

    def __init__(self, message: str, issues: list[ValidatorIssue]):
        super().__init__(message)
        self.issues = issues


# ---------------------------------------------------------------------------
# Per-layout content schemas
#
# Each entry is a dict with:
#   "required": tuple[str, ...]    — required fields in `content`
#   "optional": tuple[str, ...]    — optional fields permitted in `content`
#   "checks":   callable(content, path) -> list[ValidatorIssue]
#                                   — layout-specific deep checks
#   "example":  dict               — minimal valid example for docs/tests
# ---------------------------------------------------------------------------

def _is_str(x: Any) -> bool:
    return isinstance(x, str) and x != ""


def _is_str_list(x: Any, min_len: int = 0, max_len: int | None = None) -> bool:
    if not isinstance(x, list):
        return False
    if len(x) < min_len:
        return False
    if max_len is not None and len(x) > max_len:
        return False
    return all(isinstance(s, str) and s != "" for s in x)


def _is_pos_int(x: Any) -> bool:
    return isinstance(x, int) and not isinstance(x, bool) and x >= 1


def _is_iso8601(x: Any) -> bool:
    if not isinstance(x, str):
        return False
    # Permissive — assemble_pptx doesn't actually parse these. Just check shape.
    return bool(re.match(r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}:\d{2}(Z|[+\-]\d{2}:\d{2})?)?$", x))


def _check_required_str(content: dict, key: str, path: str, issues: list[ValidatorIssue]) -> None:
    if key not in content:
        issues.append(ValidatorIssue(f"{path}.{key}", "required field missing"))
    elif not _is_str(content[key]):
        issues.append(ValidatorIssue(f"{path}.{key}", "must be non-empty string"))


def _check_optional_str(content: dict, key: str, path: str, issues: list[ValidatorIssue]) -> None:
    if key in content and not _is_str(content[key]):
        issues.append(ValidatorIssue(f"{path}.{key}", "must be non-empty string if present"))


def _check_str_list(content: dict, key: str, path: str, issues: list[ValidatorIssue],
                    *, required: bool, min_len: int, max_len: int | None) -> None:
    if key not in content:
        if required:
            issues.append(ValidatorIssue(f"{path}.{key}", "required field missing"))
        return
    val = content[key]
    if not _is_str_list(val, min_len, max_len):
        bound = f"≤{max_len}" if max_len is not None else "any"
        issues.append(ValidatorIssue(f"{path}.{key}",
            f"must be a list of {min_len}–{bound} non-empty strings"))


def _check_figure_path(content: dict, key: str, path: str, issues: list[ValidatorIssue],
                       *, allow_tbd_placeholder: bool = False) -> None:
    """Validate a figure / image / supporting_graphic path string SHAPE.

    This is path-shape validation only — it does NOT check that the file
    exists on disk (that's the assembler's runtime job). What it catches:

      1. The deprecated `figures/curated/<name>.png` convention. Live
         failure mode (2026-04-27 draft_8): the slide_compose prompt
         used to instruct the LLM to emit `figures/curated/...` paths,
         but no upstream step (curate_figures.py is inventory-only)
         materializes that subdirectory. The assembler silently warned
         and dropped the figure → four data slides shipped picture-less.
         Fix shipped same-day in slide_compose.v1.md (changelog at top).
         This validator hard-fails so the silent drop never recurs.

    Absolute paths are **not** rejected here — the assembler supports
    them via `_resolve_asset_path`'s absolute-path branch and
    `test_absolute_figure_path_works` covers that use case (e.g., for
    test fixtures with files under `tmp_path`). The slide_compose
    prompt recommends relative paths from `curated_figures.md`, but
    that's a recommendation, not a hard validator constraint.

    If `key` is absent from content, this helper is a no-op (presence is
    the caller's concern via `_check_required_str` / `_check_optional_str`).

    `allow_tbd_placeholder=True` permits the literal string `"{TBD}"` —
    used by `concept_illustration.image_path` per slide_compose.v1.md
    L829-831 (the placeholder is filled in by `ai_image_prompt.v1`).
    """
    if key not in content:
        return
    val = content[key]
    if not isinstance(val, str):
        return  # _check_required_str / _check_optional_str will handle type errors
    if allow_tbd_placeholder and val == "{TBD}":
        return
    if "/curated/" in val or val.startswith("curated/"):
        issues.append(ValidatorIssue(
            f"{path}.{key}",
            f"path contains deprecated 'curated/' segment: {val!r}. "
            f"Use the path verbatim from curated_figures.md (typically "
            f"'figures/<name>.png'). The 'figures/curated/' convention "
            f"was removed in slide_compose.v1.md changelog 2026-04-27 "
            f"because no upstream step materializes that directory."
        ))


def _check_diagram(content: dict, key: str, path: str, issues: list[ValidatorIssue],
                   *, required: bool) -> None:
    if key not in content:
        if required:
            issues.append(ValidatorIssue(f"{path}.{key}", "required diagram missing"))
        return
    diagram = content[key]
    if not isinstance(diagram, dict):
        issues.append(ValidatorIssue(f"{path}.{key}", "must be an object"))
        return
    p = f"{path}.{key}"
    if diagram.get("kind") not in DIAGRAM_KINDS:
        issues.append(ValidatorIssue(f"{p}.kind",
            f"must be one of {DIAGRAM_KINDS}, got {diagram.get('kind')!r}"))
    nodes = diagram.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        issues.append(ValidatorIssue(f"{p}.nodes", "must be a non-empty list"))
    else:
        node_ids: set[str] = set()
        for i, node in enumerate(nodes):
            np = f"{p}.nodes[{i}]"
            if not isinstance(node, dict):
                issues.append(ValidatorIssue(np, "must be an object"))
                continue
            if not _is_str(node.get("id")):
                issues.append(ValidatorIssue(f"{np}.id", "required non-empty string"))
            elif node["id"] in node_ids:
                issues.append(ValidatorIssue(f"{np}.id",
                    f"duplicate node id {node['id']!r}"))
            else:
                node_ids.add(node["id"])
            if not _is_str(node.get("label")):
                issues.append(ValidatorIssue(f"{np}.label", "required non-empty string"))
            else:
                # M4a Tier B advisory cap (DQ4): a node label is a short
                # phrase, not a sentence. The renderer's Tier-A shrink-
                # to-fit absorbs longer labels toward the 60% floor, but
                # node boxes are tight (~1.75in wide × 0.8in tall) and
                # readability degrades fast past ~40 chars.
                label = node["label"]
                if len(label) > DIAGRAM_NODE_LABEL_MAX_CHARS:
                    issues.append(ValidatorIssue(
                        f"{np}.label",
                        f"{len(label)} chars; advisory cap "
                        f"{DIAGRAM_NODE_LABEL_MAX_CHARS} (node boxes are "
                        f"~1.75in wide; shrink-to-fit absorbs but a phrase "
                        f"reads better than a sentence).",
                        severity="soft-warning",
                    ))
            if node.get("shape") not in DIAGRAM_NODE_SHAPES:
                issues.append(ValidatorIssue(f"{np}.shape",
                    f"must be one of {DIAGRAM_NODE_SHAPES}, got {node.get('shape')!r}"))
            for coord in ("x", "y", "w", "h"):
                if not isinstance(node.get(coord), (int, float)):
                    issues.append(ValidatorIssue(f"{np}.{coord}",
                        "required numeric (inches)"))
    edges = diagram.get("edges")
    if not isinstance(edges, list):
        issues.append(ValidatorIssue(f"{p}.edges", "must be a list"))
    else:
        for i, edge in enumerate(edges):
            ep = f"{p}.edges[{i}]"
            if not isinstance(edge, dict):
                issues.append(ValidatorIssue(ep, "must be an object"))
                continue
            if not _is_str(edge.get("from")):
                issues.append(ValidatorIssue(f"{ep}.from", "required non-empty string"))
            if not _is_str(edge.get("to")):
                issues.append(ValidatorIssue(f"{ep}.to", "required non-empty string"))
            if edge.get("kind") not in DIAGRAM_EDGE_KINDS:
                issues.append(ValidatorIssue(f"{ep}.kind",
                    f"must be one of {DIAGRAM_EDGE_KINDS}, got {edge.get('kind')!r}"))


# Per-layout: required fields, optional fields, deep-checker, example
# ---------------------------------------------------------------------------

def _check_title(content: dict, path: str) -> list[ValidatorIssue]:
    iss: list[ValidatorIssue] = []
    _check_required_str(content, "title", path, iss)
    _check_required_str(content, "presenter", path, iss)
    if "date" not in content:
        iss.append(ValidatorIssue(f"{path}.date", "required field missing"))
    elif not _is_str(content["date"]):
        iss.append(ValidatorIssue(f"{path}.date", "must be ISO-8601-ish string"))
    for opt in ("subtitle", "affiliation", "venue"):
        _check_optional_str(content, opt, path, iss)
    return iss


def _check_section_divider(content: dict, path: str) -> list[ValidatorIssue]:
    iss: list[ValidatorIssue] = []
    _check_required_str(content, "punchline", path, iss)
    if "substory_number" in content:
        if not isinstance(content["substory_number"], int) or isinstance(content["substory_number"], bool):
            iss.append(ValidatorIssue(f"{path}.substory_number", "must be integer"))
        elif content["substory_number"] < 1:
            iss.append(ValidatorIssue(f"{path}.substory_number", "must be ≥1"))
    return iss


def _check_big_idea(content: dict, path: str) -> list[ValidatorIssue]:
    iss: list[ValidatorIssue] = []
    _check_required_str(content, "title", path, iss)
    _check_optional_str(content, "supporting_graphic", path, iss)
    _check_figure_path(content, "supporting_graphic", path, iss)
    return iss


def _check_big_number(content: dict, path: str) -> list[ValidatorIssue]:
    iss: list[ValidatorIssue] = []
    _check_required_str(content, "headline", path, iss)
    _check_required_str(content, "subtitle", path, iss)
    _check_optional_str(content, "sub_pointer", path, iss)
    _check_optional_str(content, "source_footer", path, iss)
    # M4a Tier B advisory cap (DQ4 soft-warning): the subtitle sits in a
    # fixed 0.52in textbox below the big number; Tier A's _fit_textbox
    # shrinks long subtitles toward the 60% floor, but the slot reads
    # most cleanly when the subtitle is one short sentence.
    _check_advisory_max_chars(
        content, "subtitle", path, BIG_NUMBER_SUBTITLE_MAX_CHARS,
        "subtitle slot is 0.52in; >80 chars triggers shrink-to-fit",
        iss,
    )
    return iss


def _check_claim_evidence(content: dict, path: str) -> list[ValidatorIssue]:
    iss: list[ValidatorIssue] = []
    _check_required_str(content, "title", path, iss)
    _check_str_list(content, "bullets", path, iss, required=True, min_len=1, max_len=3)
    has_fig = "figure" in content
    has_cap = "figure_caption" in content
    if has_fig != has_cap:
        iss.append(ValidatorIssue(path,
            "figure and figure_caption must appear together (or both absent)"))
    if has_fig:
        _check_optional_str(content, "figure", path, iss)
        _check_optional_str(content, "figure_caption", path, iss)
        _check_figure_path(content, "figure", path, iss)
    if "citations" in content:
        if not _is_str_list(content["citations"]):
            iss.append(ValidatorIssue(f"{path}.citations",
                "must be a list of citation_pool keys"))
    return iss


def _check_two_column_compare(content: dict, path: str) -> list[ValidatorIssue]:
    iss: list[ValidatorIssue] = []
    _check_required_str(content, "title", path, iss)
    _check_required_str(content, "left_col_title", path, iss)
    _check_required_str(content, "right_col_title", path, iss)
    for col in ("left_col_content", "right_col_content"):
        if col not in content:
            iss.append(ValidatorIssue(f"{path}.{col}", "required field missing"))
        else:
            val = content[col]
            if isinstance(val, str):
                if not val:
                    iss.append(ValidatorIssue(f"{path}.{col}", "non-empty string or non-empty list"))
            elif isinstance(val, list):
                if not _is_str_list(val, min_len=1):
                    iss.append(ValidatorIssue(f"{path}.{col}",
                        "list must contain non-empty strings"))
            else:
                iss.append(ValidatorIssue(f"{path}.{col}",
                    "must be a string (markdown) or a list of strings (bullets)"))
    return iss


# v0.3.5: data_figure caption cap. Pins the slide_compose.v1.md /
# revise_slide.v1.md prompt's 280-char hard limit. Captions exceeding
# this hard-fail in validate_slide_spec → assemble.py rejects the spec
# and the revise-loop must re-run with shorter caption.
#
# Live failure 2026-05-04 (gene_function_ecological_agora draft_1
# slides 21+23): revise-loop produced ~410-char captions; with
# FIGURE_REGIONS["data_figure"] H 2.85 ending at y=4.15 and the
# data_source band at y=4.83 → caption text wrapped past the data_source
# anchor and into the y=5.00 logo strip. Per memory
# feedback_prompt_tool_contract_drift.md, prompt-only caps drift; pin
# in code. The render-side MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE in
# assemble_pptx._fill_data_figure is the third layer (belt-and-
# suspenders) for any case the validator misses or is bypassed.
DATA_FIGURE_CAPTION_MAX_CHARS = 280


# ---------------------------------------------------------------------------
# M4a Tier B — advisory content-length caps (DQ4 → soft-warning)
# ---------------------------------------------------------------------------
#
# The renderer's explicit-fontScale shrink-to-fit (Tier A) is the safety
# net — if the LLM emits a slightly-long subtitle / step_caption / node
# label, the rendered text shrinks rather than spilling past the box.
# These caps are the BACKSTOP for prompt-drift on the content side:
# they catch the "the prompt cap was raised but the renderer didn't
# follow" failure mode that
# `feedback_prompt_discipline_needs_post_check.md` describes — without
# failing the pipeline after LLM spend on a length the renderer can
# absorb. Soft-warning severity (DQ4): surfaced to the assembler's
# warnings channel and the Tier-C visual-QA pass, but never raised.
#
# Pinned alongside DATA_FIGURE_CAPTION_MAX_CHARS (the hard-reject cap —
# unchanged; that one's the load-bearing 280-char data_figure caption
# cap from v0.3.5, motivated by a live render failure into the brand
# strip with no shrink-to-fit fallback at the time).

BIG_NUMBER_SUBTITLE_MAX_CHARS = 80          # ~one short sentence
WORKFLOW_STEP_CAPTION_MAX_CHARS = 70        # per step (3 steps)
QA_ANSWER_SUMMARY_MAX_CHARS = 600           # one glance; depth lives in answer_detail
DIAGRAM_NODE_LABEL_MAX_CHARS = 40           # short phrase, not a sentence


def _check_advisory_max_chars(content: dict, key: str, path: str,
                              max_chars: int, where_note: str,
                              issues: list[ValidatorIssue]) -> None:
    """Append a soft-warning if `content[key]` is a string longer than
    `max_chars`. No-op if the field is missing / not a string.

    DQ4: the renderer's shrink-to-fit (Tier A) absorbs slightly-long
    strings; this is a backstop against prompt drift, surfaced as
    advisory so the operator sees it (assembler warnings + Tier-C
    visual-QA) without failing the pipeline.
    """
    val = content.get(key)
    if not isinstance(val, str):
        return
    if len(val) <= max_chars:
        return
    issues.append(ValidatorIssue(
        f"{path}.{key}",
        f"{len(val)} chars; advisory cap {max_chars} ({where_note}). "
        f"Renderer shrink-to-fit will absorb the overflow; consider a "
        f"tighter wording for legibility.",
        severity="soft-warning",
    ))


def _check_data_figure(content: dict, path: str) -> list[ValidatorIssue]:
    iss: list[ValidatorIssue] = []
    _check_required_str(content, "title", path, iss)
    _check_required_str(content, "figure", path, iss)
    _check_required_str(content, "caption", path, iss)
    _check_optional_str(content, "data_source", path, iss)
    _check_figure_path(content, "figure", path, iss)
    # Caption length cap (v0.3.5): see DATA_FIGURE_CAPTION_MAX_CHARS
    # docstring above for the live-failure motivation.
    cap = content.get("caption")
    if isinstance(cap, str) and len(cap) > DATA_FIGURE_CAPTION_MAX_CHARS:
        iss.append(ValidatorIssue(
            f"{path}.caption",
            f"data_figure caption is {len(cap)} chars; max "
            f"{DATA_FIGURE_CAPTION_MAX_CHARS} (overflow risks running into "
            f"the brand strip at y=5.00). Move citations to data_source, "
            f"drop redundant phrasing, or split insight across multiple "
            f"slides. See slide_compose.v1.md / revise_slide.v1.md."
        ))
    return iss


# v0.3.2: data_table layout — ranked top-N, comparison matrices, etc.
DATA_TABLE_MAX_ROWS = 12
DATA_TABLE_MAX_COLS = 6


def _check_data_table(content: dict, path: str) -> list[ValidatorIssue]:
    """Validate a data_table content block.

    Schema:
      title:            required str
      columns:          required list[str], 2 ≤ len ≤ DATA_TABLE_MAX_COLS,
                        non-empty header strings
      rows:             required list[list[str]], 1 ≤ len ≤ DATA_TABLE_MAX_ROWS,
                        each inner list has len(columns) cells, ALL strings
                        (caller must stringify numbers with desired precision)
      caption:          optional str (~1 sentence; rendered below table)
      footnote:         optional str (~1 line; rendered at slide-bottom)
      data_source:      optional str (REPORT.md §X.Y or notebook reference)
      highlight_rows:   optional list[int], indices of rows to render in
                        the KBase-orange highlight band (0-based, must
                        all be < len(rows))
    """
    iss: list[ValidatorIssue] = []
    _check_required_str(content, "title", path, iss)

    # columns — list of 2-6 strings. Empty-string headers ARE allowed
    # (matrix-table convention: the corner cell where row labels meet
    # column labels is conventionally empty, e.g.
    # `["", "Conserved", "Variable"]` for a quadrant classification).
    # v0.3.2.2: relaxed from "non-empty header strings" — the v0.3.2
    # worked example in slide_compose.v1.md uses this exact pattern,
    # and the LLM faithfully reproduced it (caught in core_gene_tradeoffs
    # draft_2 selection-signature-matrix slide).
    cols = content.get("columns")
    if cols is None:
        iss.append(ValidatorIssue(f"{path}.columns", "required field missing"))
        cols = []
    elif not isinstance(cols, list):
        iss.append(ValidatorIssue(
            f"{path}.columns",
            "must be a list of 2-6 header strings",
        ))
        cols = []
    elif len(cols) < 2:
        iss.append(ValidatorIssue(
            f"{path}.columns",
            f"must have at least 2 columns; got {len(cols)} "
            "(singleton-column tables aren't tables — use a bullet list)",
        ))
    elif len(cols) > DATA_TABLE_MAX_COLS:
        iss.append(ValidatorIssue(
            f"{path}.columns",
            f"too many columns: {len(cols)} (max {DATA_TABLE_MAX_COLS}; "
            "data_table is for presentation-floor readability, not data dumps)",
        ))
    else:
        for j, header in enumerate(cols):
            if not isinstance(header, str):
                iss.append(ValidatorIssue(
                    f"{path}.columns[{j}]",
                    f"must be a string; got {type(header).__name__}",
                ))

    # rows
    rows = content.get("rows")
    if rows is None:
        iss.append(ValidatorIssue(f"{path}.rows", "required field missing"))
    elif not isinstance(rows, list):
        iss.append(ValidatorIssue(f"{path}.rows", "must be a list"))
    elif len(rows) == 0:
        iss.append(ValidatorIssue(f"{path}.rows", "must have at least 1 row"))
    elif len(rows) > DATA_TABLE_MAX_ROWS:
        iss.append(ValidatorIssue(
            f"{path}.rows",
            f"too many rows: {len(rows)} (max {DATA_TABLE_MAX_ROWS}; "
            "if you need more, link to REPORT.md as the canonical source)",
        ))
    else:
        ncols = len(cols) if isinstance(cols, list) else 0
        for i, row in enumerate(rows):
            rp = f"{path}.rows[{i}]"
            if not isinstance(row, list):
                iss.append(ValidatorIssue(rp, "must be a list of cell strings"))
                continue
            if ncols and len(row) != ncols:
                iss.append(ValidatorIssue(
                    rp,
                    f"has {len(row)} cells but columns has {ncols} headers",
                ))
            for j, cell in enumerate(row):
                if not isinstance(cell, str):
                    iss.append(ValidatorIssue(
                        f"{rp}[{j}]",
                        f"must be a string; got {type(cell).__name__}. "
                        "Caller should stringify numbers with desired precision "
                        "(e.g. f'{x:.2f}') before placing on the slide.",
                    ))

    # optional fields
    _check_optional_str(content, "caption", path, iss)
    _check_optional_str(content, "footnote", path, iss)
    _check_optional_str(content, "data_source", path, iss)

    # highlight_rows
    hl = content.get("highlight_rows")
    if hl is not None:
        if not isinstance(hl, list):
            iss.append(ValidatorIssue(
                f"{path}.highlight_rows",
                "must be a list of 0-based row indices",
            ))
        else:
            row_count = len(rows) if isinstance(rows, list) else 0
            for i, idx in enumerate(hl):
                if not isinstance(idx, int) or isinstance(idx, bool):
                    iss.append(ValidatorIssue(
                        f"{path}.highlight_rows[{i}]",
                        f"must be an int; got {type(idx).__name__}",
                    ))
                elif idx < 0 or (row_count and idx >= row_count):
                    iss.append(ValidatorIssue(
                        f"{path}.highlight_rows[{i}]",
                        f"index {idx} out of range for {row_count} rows",
                    ))

    return iss


def _check_workflow_diagram(content: dict, path: str) -> list[ValidatorIssue]:
    iss: list[ValidatorIssue] = []
    _check_required_str(content, "title", path, iss)
    _check_diagram(content, "diagram", path, iss, required=True)
    _check_str_list(content, "step_caption", path, iss,
                    required=True, min_len=3, max_len=3)
    _check_optional_str(content, "tool_version_footer", path, iss)
    # M4a Tier B advisory cap (DQ4): step_captions render in a 3-column
    # band at y=4.16, 0.52in tall, ~3.0in wide; >70 chars/step starts
    # eating into the tool-version footer. Tier A shrink-to-fit
    # absorbs it; the cap is advisory so prompt drift surfaces.
    caps = content.get("step_caption")
    if isinstance(caps, list):
        for i, cap in enumerate(caps):
            if isinstance(cap, str) and len(cap) > WORKFLOW_STEP_CAPTION_MAX_CHARS:
                iss.append(ValidatorIssue(
                    f"{path}.step_caption[{i}]",
                    f"{len(cap)} chars; advisory cap "
                    f"{WORKFLOW_STEP_CAPTION_MAX_CHARS} (one of 3 captions in a "
                    f"~3.0in column at y=4.16). Renderer shrink-to-fit will "
                    f"absorb the overflow; consider a tighter wording.",
                    severity="soft-warning",
                ))
    return iss


def _check_methods_summary(content: dict, path: str) -> list[ValidatorIssue]:
    iss: list[ValidatorIssue] = []
    _check_required_str(content, "title", path, iss)
    _check_str_list(content, "bullets", path, iss,
                    required=True, min_len=5, max_len=10)
    if "tools_versions" in content:
        tv = content["tools_versions"]
        if not isinstance(tv, list):
            iss.append(ValidatorIssue(f"{path}.tools_versions",
                "must be a list of {tool, version} objects (Option A)"))
        else:
            for i, item in enumerate(tv):
                ip = f"{path}.tools_versions[{i}]"
                if not isinstance(item, dict):
                    iss.append(ValidatorIssue(ip, "must be an object"))
                    continue
                if not _is_str(item.get("tool")):
                    iss.append(ValidatorIssue(f"{ip}.tool", "required non-empty string"))
                if not _is_str(item.get("version")):
                    iss.append(ValidatorIssue(f"{ip}.version", "required non-empty string"))
    if "see_notes_footer" in content and not isinstance(content["see_notes_footer"], bool):
        iss.append(ValidatorIssue(f"{path}.see_notes_footer", "must be boolean"))
    return iss


def _check_concept_illustration(content: dict, path: str) -> list[ValidatorIssue]:
    iss: list[ValidatorIssue] = []
    _check_required_str(content, "title", path, iss)
    _check_required_str(content, "image_path", path, iss)
    _check_required_str(content, "image_prompt", path, iss)
    # `{TBD}` is the legitimate placeholder per slide_compose.v1.md L829-831;
    # ai_image_prompt.v1 fills it in downstream.
    _check_figure_path(content, "image_path", path, iss, allow_tbd_placeholder=True)
    if content.get("style") not in CONCEPT_STYLES:
        iss.append(ValidatorIssue(f"{path}.style",
            f"must be one of {CONCEPT_STYLES}, got {content.get('style')!r}"))
    _check_optional_str(content, "caption", path, iss)
    if "ai_disclosure_footer" in content and not isinstance(content["ai_disclosure_footer"], bool):
        iss.append(ValidatorIssue(f"{path}.ai_disclosure_footer", "must be boolean"))
    if "provenance" not in content:
        iss.append(ValidatorIssue(f"{path}.provenance",
            "required for AI-generated images (SPEC §8.3 disclosure)"))
    else:
        prov = content["provenance"]
        pp = f"{path}.provenance"
        if not isinstance(prov, dict):
            iss.append(ValidatorIssue(pp, "must be an object"))
        else:
            if not _is_str(prov.get("model")):
                iss.append(ValidatorIssue(f"{pp}.model", "required non-empty string"))
            if not isinstance(prov.get("cost_usd"), (int, float)):
                iss.append(ValidatorIssue(f"{pp}.cost_usd", "required number"))
            if prov.get("channel") not in CONCEPT_CHANNELS:
                iss.append(ValidatorIssue(f"{pp}.channel",
                    f"must be one of {CONCEPT_CHANNELS}, got {prov.get('channel')!r}"))
            if not _is_iso8601(prov.get("approved_at", "")):
                iss.append(ValidatorIssue(f"{pp}.approved_at",
                    "required ISO-8601 timestamp"))
            qcs = prov.get("quant_content_score")
            if qcs is not None and not isinstance(qcs, (int, float)):
                iss.append(ValidatorIssue(f"{pp}.quant_content_score",
                    "must be number if present"))
    return iss


def _check_cross_tenant_integration(content: dict, path: str) -> list[ValidatorIssue]:
    iss: list[ValidatorIssue] = []
    _check_required_str(content, "title", path, iss)
    for key in ("tenant_list", "kberdl_db_list"):
        if key in content and not _is_str_list(content[key]):
            iss.append(ValidatorIssue(f"{path}.{key}",
                "must be a list of non-empty strings if present"))
    if "sibling_project_refs" in content:
        srefs = content["sibling_project_refs"]
        if not isinstance(srefs, list):
            iss.append(ValidatorIssue(f"{path}.sibling_project_refs",
                "must be a list of {project_id, what_was_leveraged} objects"))
        else:
            for i, ref in enumerate(srefs):
                rp = f"{path}.sibling_project_refs[{i}]"
                if not isinstance(ref, dict):
                    iss.append(ValidatorIssue(rp, "must be an object"))
                    continue
                if not _is_str(ref.get("project_id")):
                    iss.append(ValidatorIssue(f"{rp}.project_id", "required non-empty string"))
                if not _is_str(ref.get("what_was_leveraged")):
                    iss.append(ValidatorIssue(f"{rp}.what_was_leveraged",
                        "required non-empty string"))
    if "data_flow_diagram" in content and content["data_flow_diagram"] is not None:
        _check_diagram(content, "data_flow_diagram", path, iss, required=False)
    if "no_signal_fallback" in content and not isinstance(
        content["no_signal_fallback"], bool
    ):
        iss.append(ValidatorIssue(f"{path}.no_signal_fallback", "must be boolean"))
    return iss


def _check_implications(content: dict, path: str) -> list[ValidatorIssue]:
    iss: list[ValidatorIssue] = []
    _check_required_str(content, "title", path, iss)
    bullets = content.get("bullets")
    if not isinstance(bullets, list):
        iss.append(ValidatorIssue(f"{path}.bullets",
            "must be a list of {claim, evidence_pointer} objects"))
    elif len(bullets) < 1 or len(bullets) > 3:
        iss.append(ValidatorIssue(f"{path}.bullets", "must have 1–3 entries"))
    else:
        for i, b in enumerate(bullets):
            bp = f"{path}.bullets[{i}]"
            if not isinstance(b, dict):
                iss.append(ValidatorIssue(bp, "must be an object"))
                continue
            if not _is_str(b.get("claim")):
                iss.append(ValidatorIssue(f"{bp}.claim", "required non-empty string"))
            if not _is_str(b.get("evidence_pointer")):
                iss.append(ValidatorIssue(f"{bp}.evidence_pointer",
                    "required non-empty string"))
    return iss


def _check_acknowledgments(content: dict, path: str) -> list[ValidatorIssue]:
    iss: list[ValidatorIssue] = []
    _check_str_list(content, "contributors", path, iss,
                    required=True, min_len=1, max_len=None)
    if "funder_logos" in content and not _is_str_list(content["funder_logos"]):
        iss.append(ValidatorIssue(f"{path}.funder_logos",
            "must be a list of file-path strings"))
    _check_optional_str(content, "tenant_attribution", path, iss)
    _check_optional_str(content, "code_repo_url", path, iss)
    return iss


def _check_references(content: dict, path: str) -> list[ValidatorIssue]:
    iss: list[ValidatorIssue] = []
    _check_str_list(content, "refs_short", path, iss,
                    required=True, min_len=1, max_len=8)
    _check_optional_str(content, "ai_disclosure", path, iss)
    if "full_pool_in_speaker_notes" in content and not isinstance(
        content["full_pool_in_speaker_notes"], bool
    ):
        iss.append(ValidatorIssue(f"{path}.full_pool_in_speaker_notes", "must be boolean"))
    return iss


def _check_qa_anticipated(content: dict, path: str) -> list[ValidatorIssue]:
    iss: list[ValidatorIssue] = []
    _check_required_str(content, "question", path, iss)
    _check_required_str(content, "answer_summary", path, iss)
    _check_required_str(content, "evidence_pointer", path, iss)
    _check_optional_str(content, "answer_detail", path, iss)
    # M4a Tier B advisory cap (DQ4): answer_summary is the glanceable
    # slide-face line; depth lives in answer_detail (routed to the
    # notes pane per M3 E-5). Long summaries trigger the renderer's
    # adaptive autofit ladder; the cap is advisory to encourage tight
    # one-glance wording without failing the pipeline.
    _check_advisory_max_chars(
        content, "answer_summary", path, QA_ANSWER_SUMMARY_MAX_CHARS,
        "answer_summary is the slide face; depth belongs in answer_detail "
        "(notes pane)",
        iss,
    )
    return iss


# Dispatcher
LAYOUT_CHECKERS = {
    "title":                    _check_title,
    "section_divider":          _check_section_divider,
    "big_idea":                 _check_big_idea,
    "big_number":               _check_big_number,
    "claim_evidence":           _check_claim_evidence,
    "two_column_compare":       _check_two_column_compare,
    "data_figure":              _check_data_figure,
    "data_table":               _check_data_table,
    "workflow_diagram":         _check_workflow_diagram,
    "methods_summary":          _check_methods_summary,
    "concept_illustration":     _check_concept_illustration,
    "cross_tenant_integration": _check_cross_tenant_integration,
    "implications":             _check_implications,
    "acknowledgments":          _check_acknowledgments,
    "references":               _check_references,
    "qa_anticipated":           _check_qa_anticipated,
}
assert set(LAYOUT_CHECKERS.keys()) == set(LAYOUTS), \
    "LAYOUT_CHECKERS must cover the entire vocabulary"


# ---------------------------------------------------------------------------
# Top-level validator
# ---------------------------------------------------------------------------

def validate_slide_spec(spec: dict) -> list[ValidatorIssue]:
    """Validate a slide_spec dict against the v1 contract.

    Returns a list of ValidatorIssue objects. An empty list means the spec
    is valid. The validator collects all issues rather than failing fast,
    so callers can show a complete error report.
    """
    iss: list[ValidatorIssue] = []

    if not isinstance(spec, dict):
        iss.append(ValidatorIssue("$", "top-level value must be an object"))
        return iss

    # Top-level required fields
    if spec.get("schema_version") != SCHEMA_VERSION:
        iss.append(ValidatorIssue("$.schema_version",
            f"must be {SCHEMA_VERSION!r}, got {spec.get('schema_version')!r}"))

    if not _is_str(spec.get("project_id")):
        iss.append(ValidatorIssue("$.project_id", "required non-empty string"))
    if spec.get("mode") not in MODES:
        iss.append(ValidatorIssue("$.mode",
            f"must be one of {MODES}, got {spec.get('mode')!r}"))
    if spec.get("audience") not in AUDIENCES:
        iss.append(ValidatorIssue("$.audience",
            f"must be one of {AUDIENCES} (v1 supports peer only), got {spec.get('audience')!r}"))
    if spec.get("tier") not in TIERS:
        iss.append(ValidatorIssue("$.tier",
            f"must be one of {TIERS}, got {spec.get('tier')!r}"))

    # throughline
    th = spec.get("throughline")
    if not isinstance(th, dict):
        iss.append(ValidatorIssue("$.throughline", "required object"))
    else:
        if not _is_str(th.get("id")):
            iss.append(ValidatorIssue("$.throughline.id", "required non-empty string"))
        if not _is_str(th.get("punchline")):
            iss.append(ValidatorIssue("$.throughline.punchline", "required non-empty string"))
        if th.get("tier_evidence") not in TIERS:
            iss.append(ValidatorIssue("$.throughline.tier_evidence",
                f"must be one of {TIERS}, got {th.get('tier_evidence')!r}"))

    # substories
    substories = spec.get("substories")
    substory_ids: set[str] = set()
    if not isinstance(substories, list):
        iss.append(ValidatorIssue("$.substories", "required list"))
    else:
        for i, sub in enumerate(substories):
            sp = f"$.substories[{i}]"
            if not isinstance(sub, dict):
                iss.append(ValidatorIssue(sp, "must be an object"))
                continue
            if not _is_str(sub.get("id")):
                iss.append(ValidatorIssue(f"{sp}.id", "required non-empty string"))
            elif sub["id"] in substory_ids:
                iss.append(ValidatorIssue(f"{sp}.id",
                    f"duplicate substory id {sub['id']!r}"))
            else:
                substory_ids.add(sub["id"])
            if not _is_str(sub.get("punchline")):
                iss.append(ValidatorIssue(f"{sp}.punchline", "required non-empty string"))
            slide_ids_field = sub.get("slide_ids")
            if not isinstance(slide_ids_field, list) or \
               not all(_is_pos_int(x) for x in slide_ids_field):
                iss.append(ValidatorIssue(f"{sp}.slide_ids",
                    "must be a list of positive integers"))

    # slides
    slides = spec.get("slides")
    if not isinstance(slides, list) or not slides:
        iss.append(ValidatorIssue("$.slides", "required non-empty list"))
        return iss  # without slides, deeper checks meaningless

    seen_ids: set[int] = set()
    for i, slide in enumerate(slides):
        sp = f"$.slides[{i}]"
        if not isinstance(slide, dict):
            iss.append(ValidatorIssue(sp, "must be an object"))
            continue

        sid = slide.get("id")
        if not _is_pos_int(sid):
            iss.append(ValidatorIssue(f"{sp}.id", "required positive integer"))
        elif sid in seen_ids:
            iss.append(ValidatorIssue(f"{sp}.id", f"duplicate slide id {sid}"))
        else:
            seen_ids.add(sid)

        layout = slide.get("layout")
        if layout not in LAYOUTS:
            iss.append(ValidatorIssue(f"{sp}.layout",
                f"must be one of {LAYOUTS}, got {layout!r}"))
            # don't recurse into content with unknown layout
            continue

        # substory_id (optional, must reference declared substory if present)
        sub_id = slide.get("substory_id")
        if sub_id is not None:
            if not _is_str(sub_id):
                iss.append(ValidatorIssue(f"{sp}.substory_id",
                    "must be string referencing a declared substory or null"))
            elif sub_id not in substory_ids:
                iss.append(ValidatorIssue(f"{sp}.substory_id",
                    f"references undeclared substory {sub_id!r}"))

        # content (layout-discriminated)
        content = slide.get("content")
        if not isinstance(content, dict):
            iss.append(ValidatorIssue(f"{sp}.content", "required object"))
        else:
            iss.extend(LAYOUT_CHECKERS[layout](content, f"{sp}.content"))

        # speaker_notes optional but if present must be string
        if "speaker_notes" in slide and not isinstance(slide["speaker_notes"], str):
            iss.append(ValidatorIssue(f"{sp}.speaker_notes", "must be string if present"))

        # validator_status optional dict; values must be from VALIDATOR_STATUS
        vs = slide.get("validator_status")
        if vs is not None:
            if not isinstance(vs, dict):
                iss.append(ValidatorIssue(f"{sp}.validator_status", "must be object if present"))
            else:
                for k, v in vs.items():
                    if v not in VALIDATOR_STATUS:
                        iss.append(ValidatorIssue(f"{sp}.validator_status.{k}",
                            f"must be one of {VALIDATOR_STATUS}, got {v!r}"))

    return iss


# ---------------------------------------------------------------------------
# JSON Schema export
# ---------------------------------------------------------------------------

def dump_json_schema() -> dict:
    """Emit a JSON Schema (Draft 2020-12) document equivalent to the
    hand-rolled validator above. Useful as documentation for the slide-
    compose prompt and as a sanity check on the contract.

    The hand-rolled validator above is the AUTHORITATIVE source; the JSON
    Schema below is generated for prompt-context hygiene only.
    """
    layout_branches = []
    for layout in LAYOUTS:
        layout_branches.append({
            "if": {"properties": {"layout": {"const": layout}}},
            "then": {"properties": {"content": {"$ref": f"#/$defs/{layout}_content"}}},
        })

    diagram_def = {
        "type": "object",
        "required": ["kind", "nodes", "edges"],
        "properties": {
            "kind": {"enum": list(DIAGRAM_KINDS)},
            "nodes": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "required": ["id", "label", "shape", "x", "y", "w", "h"],
                    "properties": {
                        "id": {"type": "string", "minLength": 1},
                        "label": {"type": "string", "minLength": 1},
                        "shape": {"enum": list(DIAGRAM_NODE_SHAPES)},
                        "x": {"type": "number"},
                        "y": {"type": "number"},
                        "w": {"type": "number"},
                        "h": {"type": "number"},
                        "fill_color": {"type": "string"},
                        "text_color": {"type": "string"},
                    },
                },
            },
            "edges": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["from", "to", "kind"],
                    "properties": {
                        "from": {"type": "string", "minLength": 1},
                        "to": {"type": "string", "minLength": 1},
                        "kind": {"enum": list(DIAGRAM_EDGE_KINDS)},
                        "label": {"type": "string"},
                    },
                },
            },
        },
    }

    # Per-layout content definitions (compact; mirrors the validator)
    content_defs = {
        "title_content": {
            "type": "object",
            "required": ["title", "presenter", "date"],
            "properties": {
                "title": {"type": "string", "minLength": 1},
                "presenter": {"type": "string", "minLength": 1},
                "date": {"type": "string"},
                "subtitle": {"type": "string"},
                "affiliation": {"type": "string"},
                "venue": {"type": "string"},
            },
        },
        "section_divider_content": {
            "type": "object",
            "required": ["punchline"],
            "properties": {
                "punchline": {"type": "string", "minLength": 1},
                "substory_number": {"type": "integer", "minimum": 1},
            },
        },
        "big_idea_content": {
            "type": "object",
            "required": ["title"],
            "properties": {
                "title": {"type": "string", "minLength": 1},
                "supporting_graphic": {"type": "string"},
            },
        },
        "big_number_content": {
            "type": "object",
            "required": ["headline", "subtitle"],
            "properties": {
                "headline": {"type": "string", "minLength": 1},
                "subtitle": {"type": "string", "minLength": 1},
                "sub_pointer": {"type": "string"},
                "source_footer": {"type": "string"},
            },
        },
        "claim_evidence_content": {
            "type": "object",
            "required": ["title", "bullets"],
            "properties": {
                "title": {"type": "string", "minLength": 1},
                "bullets": {"type": "array", "minItems": 1, "maxItems": 3,
                            "items": {"type": "string", "minLength": 1}},
                "figure": {"type": "string"},
                "figure_caption": {"type": "string"},
                "citations": {"type": "array", "items": {"type": "string"}},
            },
        },
        "two_column_compare_content": {
            "type": "object",
            "required": ["title", "left_col_title", "left_col_content",
                         "right_col_title", "right_col_content"],
            "properties": {
                "title": {"type": "string", "minLength": 1},
                "left_col_title": {"type": "string", "minLength": 1},
                "right_col_title": {"type": "string", "minLength": 1},
                "left_col_content": {
                    "oneOf": [
                        {"type": "string", "minLength": 1},
                        {"type": "array", "items": {"type": "string", "minLength": 1}},
                    ]
                },
                "right_col_content": {
                    "oneOf": [
                        {"type": "string", "minLength": 1},
                        {"type": "array", "items": {"type": "string", "minLength": 1}},
                    ]
                },
            },
        },
        "data_figure_content": {
            "type": "object",
            "required": ["title", "figure", "caption"],
            "properties": {
                "title": {"type": "string", "minLength": 1},
                "figure": {"type": "string", "minLength": 1},
                "caption": {"type": "string", "minLength": 1},
                "data_source": {"type": "string"},
            },
        },
        "data_table_content": {
            "type": "object",
            "required": ["title", "columns", "rows"],
            "properties": {
                "title": {"type": "string", "minLength": 1},
                "columns": {
                    "type": "array",
                    "minItems": 2,
                    "maxItems": DATA_TABLE_MAX_COLS,
                    "items": {"type": "string", "minLength": 1},
                },
                "rows": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": DATA_TABLE_MAX_ROWS,
                    "items": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "caption": {"type": "string"},
                "footnote": {"type": "string"},
                "data_source": {"type": "string"},
                "highlight_rows": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 0},
                },
            },
        },
        "workflow_diagram_content": {
            "type": "object",
            "required": ["title", "diagram", "step_caption"],
            "properties": {
                "title": {"type": "string", "minLength": 1},
                "diagram": {"$ref": "#/$defs/diagram"},
                "step_caption": {"type": "array", "minItems": 3, "maxItems": 3,
                                 "items": {"type": "string", "minLength": 1}},
                "tool_version_footer": {"type": "string"},
            },
        },
        "methods_summary_content": {
            "type": "object",
            "required": ["title", "bullets"],
            "properties": {
                "title": {"type": "string", "minLength": 1},
                "bullets": {"type": "array", "minItems": 5, "maxItems": 10,
                            "items": {"type": "string", "minLength": 1}},
                "tools_versions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["tool", "version"],
                        "properties": {
                            "tool": {"type": "string", "minLength": 1},
                            "version": {"type": "string", "minLength": 1},
                        },
                    },
                },
                "see_notes_footer": {"type": "boolean"},
            },
        },
        "concept_illustration_content": {
            "type": "object",
            "required": ["title", "image_path", "image_prompt", "style", "provenance"],
            "properties": {
                "title": {"type": "string", "minLength": 1},
                "image_path": {"type": "string", "minLength": 1},
                "image_prompt": {"type": "string", "minLength": 1},
                "style": {"enum": list(CONCEPT_STYLES)},
                "caption": {"type": "string"},
                "ai_disclosure_footer": {"type": "boolean"},
                "provenance": {
                    "type": "object",
                    "required": ["model", "cost_usd", "channel", "approved_at"],
                    "properties": {
                        "model": {"type": "string", "minLength": 1},
                        "cost_usd": {"type": "number"},
                        "channel": {"enum": list(CONCEPT_CHANNELS)},
                        "approved_at": {"type": "string"},
                        "quant_content_score": {"type": "number"},
                    },
                },
            },
        },
        "cross_tenant_integration_content": {
            "type": "object",
            "required": ["title"],
            "properties": {
                "title": {"type": "string", "minLength": 1},
                "tenant_list": {"type": "array", "items": {"type": "string"}},
                "kberdl_db_list": {"type": "array", "items": {"type": "string"}},
                "sibling_project_refs": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["project_id", "what_was_leveraged"],
                        "properties": {
                            "project_id": {"type": "string", "minLength": 1},
                            "what_was_leveraged": {"type": "string", "minLength": 1},
                        },
                    },
                },
                "data_flow_diagram": {
                    "anyOf": [{"type": "null"}, {"$ref": "#/$defs/diagram"}],
                },
                "no_signal_fallback": {"type": "boolean"},
            },
        },
        "implications_content": {
            "type": "object",
            "required": ["title", "bullets"],
            "properties": {
                "title": {"type": "string", "minLength": 1},
                "bullets": {
                    "type": "array", "minItems": 1, "maxItems": 3,
                    "items": {
                        "type": "object",
                        "required": ["claim", "evidence_pointer"],
                        "properties": {
                            "claim": {"type": "string", "minLength": 1},
                            "evidence_pointer": {"type": "string", "minLength": 1},
                        },
                    },
                },
            },
        },
        "acknowledgments_content": {
            "type": "object",
            "required": ["contributors"],
            "properties": {
                "contributors": {"type": "array", "minItems": 1,
                                 "items": {"type": "string", "minLength": 1}},
                "funder_logos": {"type": "array", "items": {"type": "string"}},
                "tenant_attribution": {"type": "string"},
                "code_repo_url": {"type": "string"},
            },
        },
        "references_content": {
            "type": "object",
            "required": ["refs_short"],
            "properties": {
                "refs_short": {"type": "array", "minItems": 1, "maxItems": 8,
                               "items": {"type": "string", "minLength": 1}},
                "ai_disclosure": {"type": "string"},
                "full_pool_in_speaker_notes": {"type": "boolean"},
            },
        },
        "qa_anticipated_content": {
            "type": "object",
            "required": ["question", "answer_summary", "evidence_pointer"],
            "properties": {
                "question": {"type": "string", "minLength": 1},
                "answer_summary": {"type": "string", "minLength": 1},
                "answer_detail": {"type": "string"},
                "evidence_pointer": {"type": "string", "minLength": 1},
            },
        },
    }

    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://github.com/ArkinLaboratory/beril-presentation-maker-skill/blob/main/src/beril_presentation_maker/skill/references/slide_spec.schema.json",
        "title": "BERIL Presentation Maker — slide_spec.json schema",
        "description": (
            f"v{SCHEMA_VERSION} contract for slide_spec.json. The hand-rolled "
            f"validator in tools/slide_spec.py is the authoritative source; "
            f"this JSON Schema is generated for documentation and prompt-context "
            f"hygiene."
        ),
        "type": "object",
        "required": [
            "schema_version", "project_id", "mode", "audience", "tier",
            "throughline", "substories", "slides",
        ],
        "properties": {
            "schema_version": {"const": SCHEMA_VERSION},
            "project_id": {"type": "string", "minLength": 1},
            "draft_dir": {"type": "string"},
            "mode": {"enum": list(MODES)},
            "audience": {"enum": list(AUDIENCES)},
            "tier": {"enum": list(TIERS)},
            "created_at": {"type": "string"},
            "last_modified": {"type": "string"},
            "model_used": {"type": "object"},
            "throughline": {
                "type": "object",
                "required": ["id", "punchline", "tier_evidence"],
                "properties": {
                    "id": {"type": "string", "minLength": 1},
                    "punchline": {"type": "string", "minLength": 1},
                    "tier_evidence": {"enum": list(TIERS)},
                },
            },
            "substories": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["id", "punchline", "slide_ids"],
                    "properties": {
                        "id": {"type": "string", "minLength": 1},
                        "punchline": {"type": "string", "minLength": 1},
                        "slide_ids": {"type": "array",
                                      "items": {"type": "integer", "minimum": 1}},
                        "approved_at": {"type": "string"},
                    },
                },
            },
            "citation_pool_ref": {"type": "string"},
            "slides": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "required": ["id", "layout", "content"],
                    "properties": {
                        "id": {"type": "integer", "minimum": 1},
                        "layout": {"enum": list(LAYOUTS)},
                        "substory_id": {"type": ["string", "null"]},
                        "content": {"type": "object"},
                        "speaker_notes": {"type": "string"},
                        "speaker_notes_provenance": {"type": "array"},
                        "validator_status": {
                            "type": "object",
                            "additionalProperties": {"enum": list(VALIDATOR_STATUS)},
                        },
                        "revision_log": {"type": "array"},
                    },
                    "allOf": layout_branches,
                },
            },
        },
        "$defs": {
            "diagram": diagram_def,
            **content_defs,
        },
    }
    return schema


# ---------------------------------------------------------------------------
# Examples (one minimal valid spec per layout — used in tests + schema docs)
# ---------------------------------------------------------------------------

def example_slide(layout: str, slide_id: int = 1, substory_id: str | None = "S1") -> dict:
    """Return a minimal valid slide for the given layout. Used by tests
    and by the slide-compose prompt's few-shot examples (Phase 3)."""
    if layout not in LAYOUTS:
        raise ValueError(f"unknown layout: {layout!r}")
    base = {"id": slide_id, "layout": layout, "substory_id": substory_id}
    contents: dict[str, dict] = {
        "title": {
            "title": "Sample Title",
            "presenter": "Adam Arkin",
            "date": "2026-06-12",
        },
        "section_divider": {
            "punchline": "Substory punchline goes here.",
        },
        "big_idea": {
            "title": "A single sentence claim, large and central.",
        },
        "big_number": {
            "headline": "27,000,000",
            "subtitle": "fitness scores integrated across 1,400 genomes",
        },
        "claim_evidence": {
            "title": "Punchline that summarizes the slide's argument.",
            "bullets": ["First evidence point.", "Second evidence point."],
        },
        "two_column_compare": {
            "title": "Optional comparison title.",
            "left_col_title": "Before",
            "left_col_content": ["A", "B"],
            "right_col_title": "After",
            "right_col_content": ["C", "D"],
        },
        "data_figure": {
            "title": "Chart interpretation as title.",
            "figure": "figures/fig01.png",
            "caption": "Caption explaining what the chart shows.",
        },
        "data_table": {
            "title": "Top 5 dark-matter candidates by ensemble score.",
            "columns": ["Gene", "Organism", "Score", "Evidence"],
            "rows": [
                ["AO356_11255", "P. putida", "0.92", "ML+conservation"],
                ["SO_2027",      "Shewanella", "0.88", "ML+phenotype"],
                ["SO_2123",      "Shewanella", "0.85", "ML"],
                ["DVU_0314",     "D. vulgaris", "0.81", "conservation"],
                ["DVU_0817",     "D. vulgaris", "0.78", "ML"],
            ],
            "caption": "Top candidates by ensemble score (REPORT.md §4.2).",
            "footnote": "Full ranking (n=347) in REPORT.md §4.2.",
            "highlight_rows": [0],
        },
        "workflow_diagram": {
            "title": "Workflow punchline.",
            "diagram": {
                "kind": "boxes_and_arrows",
                "nodes": [
                    {"id": "n1", "label": "Start", "shape": "rounded",
                     "x": 0.5, "y": 1.0, "w": 1.5, "h": 0.8},
                    {"id": "n2", "label": "End",   "shape": "rounded",
                     "x": 5.0, "y": 1.0, "w": 1.5, "h": 0.8},
                ],
                "edges": [{"from": "n1", "to": "n2", "kind": "straight"}],
            },
            "step_caption": ["Step 1.", "Step 2.", "Step 3."],
        },
        "methods_summary": {
            "title": "Methods grounded in code.",
            "bullets": [
                "Tool A v1.0",
                "Tool B v2.3",
                "Statistical test: Fisher exact",
                "Multiple-testing correction: Bonferroni",
                "Validation set: N=120 holdout",
            ],
        },
        "concept_illustration": {
            "title": "Conceptual illustration title.",
            "image_path": "ai_images/img01.png",
            "image_prompt": "an icon, conceptual style",
            "style": "metaphor",
            "provenance": {
                "model": "google/gemini-pro-image",
                "cost_usd": 0.18,
                "channel": "A",
                "approved_at": "2026-04-26T15:12:00Z",
            },
        },
        "cross_tenant_integration": {
            "title": "Cross-tenant integration summary.",
        },
        "implications": {
            "title": "What changes if this is true.",
            "bullets": [
                {"claim": "Implication A.", "evidence_pointer": "Substory 1"},
            ],
        },
        "acknowledgments": {
            "contributors": ["Collaborator A", "Collaborator B"],
        },
        "references": {
            "refs_short": ["Smith 2023", "Jones 2024"],
        },
        "qa_anticipated": {
            "question": "Anticipated question from the audience?",
            "answer_summary": "Brief, evidence-anchored answer.",
            "evidence_pointer": "REPORT.md §4.1",
        },
    }
    base["content"] = contents[layout]
    return base


def example_slide_spec() -> dict:
    """Return a minimal valid slide_spec covering all 15 layouts.
    Useful for tests and documentation."""
    slides = [example_slide(layout, slide_id=i + 1, substory_id=("S1" if i % 2 else None))
              for i, layout in enumerate(LAYOUTS)]
    substory_slide_ids = [s["id"] for s in slides if s.get("substory_id") == "S1"]
    return {
        "schema_version": SCHEMA_VERSION,
        "project_id": "example_project",
        "mode": "talk-30",
        "audience": "peer",
        "tier": "STRONG",
        "throughline": {
            "id": "TL1",
            "punchline": "Example throughline punchline.",
            "tier_evidence": "STRONG",
        },
        "substories": [
            {"id": "S1", "punchline": "Example substory.",
             "slide_ids": substory_slide_ids},
        ],
        "slides": slides,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli_validate(args: argparse.Namespace) -> int:
    """Validate a slide_spec.json file via the CLI.

    M4a Tier B/E (DQ4): severity-aware exit code. Soft-warnings DO NOT
    fail the validation — the renderer's shrink-to-fit absorbs slightly-
    long content, so a soft-warning is advisory, not a contract
    violation. Hard errors still rc=1.

    Live failure mid-Tier-E (2026-05-23): the pre-fix logic counted all
    issues regardless of severity; orchestrator's `slide_spec.py
    validate` call returned 1 on a spec with 19 soft-warnings and zero
    errors, halting stage_merge_and_assemble. The in-process assembler
    consumer was correctly severity-aware (Tier B commit f7581af); the
    standalone CLI was the missing piece.
    """
    spec = json.loads(Path(args.path).read_text(encoding="utf-8"))
    issues = validate_slide_spec(spec)
    if not issues:
        print("OK", file=sys.stderr)
        return 0
    errors = [i for i in issues if getattr(i, "severity", "error") == "error"]
    soft = [i for i in issues if getattr(i, "severity", "error") == "soft-warning"]
    # Print all issues so the operator sees them (the format() helper
    # prefixes soft-warnings with "[soft-warning] ").
    for issue in issues:
        print(issue.format())
    if errors:
        print(
            f"\n{len(errors)} error(s)"
            + (f" + {len(soft)} soft-warning(s)" if soft else ""),
            file=sys.stderr,
        )
        return 1
    # Soft-warnings only: advisory, the renderer absorbs them; rc=0 so
    # the orchestrator proceeds to assemble. The assembler will surface
    # the same soft-warnings through AssemblyResult.warnings.
    print(
        f"\nOK ({len(soft)} soft-warning(s) — advisory; "
        f"renderer shrink-to-fit absorbs)",
        file=sys.stderr,
    )
    return 0


def _cli_schema_json(args: argparse.Namespace) -> int:
    schema = dump_json_schema()
    text = json.dumps(schema, indent=2, sort_keys=True) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"wrote {args.out}", file=sys.stderr)
    else:
        sys.stdout.write(text)
    return 0


def _cli_example(args: argparse.Namespace) -> int:
    if args.layout == "all":
        spec = example_slide_spec()
        print(json.dumps(spec, indent=2))
    else:
        if args.layout not in LAYOUTS:
            print(f"unknown layout: {args.layout!r}; one of {LAYOUTS}", file=sys.stderr)
            return 2
        slide = example_slide(args.layout)
        print(json.dumps(slide, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="slide_spec",
        description="Validate slide_spec.json or emit schema/examples.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_val = sub.add_parser("validate", help="Validate a slide_spec.json file.")
    p_val.add_argument("path", help="Path to slide_spec.json")
    p_val.set_defaults(func=_cli_validate)

    p_sch = sub.add_parser("schema-json", help="Emit JSON Schema document.")
    p_sch.add_argument("--out", help="Write to file (default: stdout).")
    p_sch.set_defaults(func=_cli_schema_json)

    p_ex = sub.add_parser("example", help="Emit a sample slide or full spec.")
    p_ex.add_argument("layout", help=f"One of {LAYOUTS} or 'all'")
    p_ex.set_defaults(func=_cli_example)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
