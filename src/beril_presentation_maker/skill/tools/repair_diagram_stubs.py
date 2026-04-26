#!/usr/bin/env python3
"""repair_diagram_stubs.py — deterministic coercion of malformed
workflow_diagram (and cross_tenant_integration data_flow_diagram)
content into schema-conformant stubs.

Live smoke on 2026-04-26 surfaced slide_compose.v1 producing diagrams
with invented shape vocabulary (`data_input`, `process`, `output`),
missing `kind` on the diagram object, missing node geometry, and
missing `kind` on edges. The model stayed within reasonable semantic
content but improvised the schema fields it didn't have inline
guidance for.

Two layers of defense (this script is layer 1; prompt tightening is
layer 2):

1. **Coerce invented shape values** to closest schema match (default:
   `rectangle`).
2. **Coerce invented edge kinds** to closest schema match (default:
   `straight`).
3. **Add missing `kind: boxes_and_arrows`** on the diagram object.
4. **Compute default geometry** for nodes missing x/y/w/h: linear
   horizontal flow across the workflow_diagram content region
   (~0.5, 1.4, 9.0, 4.2 inches), with explicit gap = 0.4".
5. **Log every coercion** for transparency. The repair output is
   *not* silent — `--report` writes a markdown file naming each
   coercion with the original and replacement value, so the user
   sees what was changed.

Usage:
    python3 repair_diagram_stubs.py \
        --in slide_spec.json \
        --out slide_spec.repaired.json \
        --report slide_spec.repair_report.md

Exit codes:
  0 — repair complete (may have made coercions; check report)
  1 — input file missing / unreadable / malformed JSON

Idempotent: running on an already-valid spec is a no-op (the report
is written but is empty of coercions).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

VALID_NODE_SHAPES = (
    "rectangle", "rounded", "ellipse", "parallelogram",
    "cylinder", "callout", "swimlane",
)

VALID_EDGE_KINDS = ("straight", "elbow", "curved")

# Mapping for common invented shape names → our 7-shape vocabulary.
# When the LLM uses generic-flowchart language, coerce to the closest
# schema-valid match. Keys are lowercased; values are exact.
SHAPE_ALIASES = {
    # Process / generic action steps → rectangle
    "process": "rectangle",
    "step": "rectangle",
    "task": "rectangle",
    "action": "rectangle",
    # Inputs/outputs → parallelogram (skews toward "data") OR rectangle
    "data_input": "parallelogram",
    "data-input": "parallelogram",
    "input": "parallelogram",
    "data_output": "parallelogram",
    "data-output": "parallelogram",
    "output": "parallelogram",
    # Decision diamonds → ellipse (no diamond in v1; ellipse is closest
    # to "branch")
    "decision": "ellipse",
    "diamond": "ellipse",
    "branch": "ellipse",
    # Database/store → cylinder
    "database": "cylinder",
    "store": "cylinder",
    "datastore": "cylinder",
    # Annotation/comment → callout
    "annotation": "callout",
    "comment": "callout",
    "note": "callout",
    # Terminator (start/end) → ellipse
    "start": "ellipse",
    "end": "ellipse",
    "terminator": "ellipse",
}

# Edge-kind aliases. Default to `straight` for anything unrecognized.
EDGE_KIND_ALIASES = {
    "line": "straight",
    "arrow": "straight",
    "direct": "straight",
    "right_angle": "elbow",
    "right-angle": "elbow",
    "L-shape": "elbow",
    "bezier": "curved",
    "spline": "curved",
}

# Default workflow_diagram content region (matches diagram_design.v1):
# left=0.5, top=1.4, width=9.0, height=4.2 (inches).
CONTENT_LEFT = 0.5
CONTENT_TOP = 1.4
CONTENT_WIDTH = 9.0
CONTENT_HEIGHT = 4.2


def coerce_shape(raw: Any) -> tuple[str, str | None]:
    """Return (coerced_shape, original_if_changed_else_None)."""
    if raw in VALID_NODE_SHAPES:
        return raw, None
    key = (raw or "").strip().lower() if isinstance(raw, str) else ""
    coerced = SHAPE_ALIASES.get(key, "rectangle")
    return coerced, str(raw)


def coerce_edge_kind(raw: Any) -> tuple[str, str | None]:
    """Return (coerced_kind, original_if_changed_else_None)."""
    if raw in VALID_EDGE_KINDS:
        return raw, None
    key = (raw or "").strip().lower() if isinstance(raw, str) else ""
    coerced = EDGE_KIND_ALIASES.get(key, "straight")
    return coerced, str(raw) if raw is not None else "<missing>"


def compute_linear_geometry(n_nodes: int, node_idx: int) -> dict:
    """Linear horizontal flow geometry. Used when slide_compose omitted
    x/y/w/h. Mirrors the default in diagram_design.v1's
    'Geometry-authoring discipline' section.

    For N nodes: gap = 0.4", node_w = (CONTENT_WIDTH - (N+1)*gap) / N,
    node_h = 0.9, y = CONTENT_TOP + 0.4.
    """
    gap = 0.4
    if n_nodes <= 0:
        n_nodes = 1
    node_w = (CONTENT_WIDTH - (n_nodes + 1) * gap) / n_nodes
    if node_w < 0.6:
        node_w = 0.6  # floor — assemble_pptx prefers >= 0.5
    node_h = 0.9
    x = CONTENT_LEFT + (node_idx + 1) * gap + node_idx * node_w
    y = CONTENT_TOP + 0.4
    return {"x": round(x, 3), "y": round(y, 3),
            "w": round(node_w, 3), "h": round(node_h, 3)}


def repair_diagram(diagram: dict, slide_path: str,
                   coercions: list[str]) -> dict:
    """In-place-ish repair: returns a new diagram dict with the
    schema-conformant fields filled in. `coercions` is appended to
    with one human-readable line per change."""
    if not isinstance(diagram, dict):
        coercions.append(
            f"{slide_path}: diagram is not an object; replaced with empty stub"
        )
        return {"kind": "boxes_and_arrows", "nodes": [], "edges": []}

    out = dict(diagram)

    # Top-level kind
    if out.get("kind") != "boxes_and_arrows":
        coercions.append(
            f"{slide_path}.kind: {out.get('kind')!r} → 'boxes_and_arrows'"
        )
        out["kind"] = "boxes_and_arrows"

    # Nodes
    nodes_in = out.get("nodes")
    nodes_out: list[dict] = []
    if isinstance(nodes_in, list):
        n_total = len(nodes_in)
        needs_geometry = any(
            not isinstance(node, dict) or
            any(k not in node or not isinstance(node.get(k), (int, float))
                for k in ("x", "y", "w", "h"))
            for node in nodes_in
        )
        for i, node in enumerate(nodes_in):
            if not isinstance(node, dict):
                coercions.append(
                    f"{slide_path}.nodes[{i}]: not an object; dropped"
                )
                continue
            new_node = dict(node)

            # Shape
            new_shape, orig_shape = coerce_shape(new_node.get("shape"))
            if orig_shape is not None:
                coercions.append(
                    f"{slide_path}.nodes[{i}].shape: "
                    f"{orig_shape!r} → {new_shape!r}"
                )
            new_node["shape"] = new_shape

            # Geometry: if any of x/y/w/h missing or non-numeric, compute defaults
            if needs_geometry or any(
                k not in new_node or
                not isinstance(new_node.get(k), (int, float))
                for k in ("x", "y", "w", "h")
            ):
                geom = compute_linear_geometry(n_total, i)
                missing = [k for k in ("x", "y", "w", "h")
                           if k not in node or not isinstance(node.get(k), (int, float))]
                if missing:
                    coercions.append(
                        f"{slide_path}.nodes[{i}]: computed default geometry "
                        f"(missing/non-numeric: {','.join(missing)}) → "
                        f"{geom}"
                    )
                new_node.update(geom)

            nodes_out.append(new_node)
    else:
        coercions.append(
            f"{slide_path}.nodes: not a list; replaced with empty list"
        )
    out["nodes"] = nodes_out

    # Edges
    edges_in = out.get("edges")
    edges_out: list[dict] = []
    if isinstance(edges_in, list):
        for i, edge in enumerate(edges_in):
            if not isinstance(edge, dict):
                coercions.append(
                    f"{slide_path}.edges[{i}]: not an object; dropped"
                )
                continue
            new_edge = dict(edge)
            new_kind, orig_kind = coerce_edge_kind(new_edge.get("kind"))
            if orig_kind is not None:
                coercions.append(
                    f"{slide_path}.edges[{i}].kind: "
                    f"{orig_kind!r} → {new_kind!r}"
                )
            new_edge["kind"] = new_kind
            edges_out.append(new_edge)
    else:
        coercions.append(
            f"{slide_path}.edges: not a list; replaced with empty list"
        )
    out["edges"] = edges_out

    return out


def repair_spec(spec: dict) -> tuple[dict, list[str]]:
    """Walk the spec, repair every diagram. Returns (new_spec,
    coercions_log)."""
    coercions: list[str] = []
    out_spec = dict(spec)
    slides = out_spec.get("slides")
    if not isinstance(slides, list):
        return out_spec, coercions

    new_slides = []
    for i, slide in enumerate(slides):
        if not isinstance(slide, dict):
            new_slides.append(slide)
            continue
        new_slide = dict(slide)
        layout = new_slide.get("layout")
        content = new_slide.get("content")
        if not isinstance(content, dict):
            new_slides.append(new_slide)
            continue
        new_content = dict(content)

        # workflow_diagram has `diagram` (required)
        if layout == "workflow_diagram" and "diagram" in new_content:
            new_content["diagram"] = repair_diagram(
                new_content["diagram"],
                f"$.slides[{i}].content.diagram",
                coercions,
            )

        # cross_tenant_integration has `data_flow_diagram` (optional)
        if layout == "cross_tenant_integration" \
                and isinstance(new_content.get("data_flow_diagram"), dict):
            new_content["data_flow_diagram"] = repair_diagram(
                new_content["data_flow_diagram"],
                f"$.slides[{i}].content.data_flow_diagram",
                coercions,
            )

        new_slide["content"] = new_content
        new_slides.append(new_slide)

    out_spec["slides"] = new_slides
    return out_spec, coercions


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="in_path", required=True,
                    help="Input slide_spec.json path")
    ap.add_argument("--out", dest="out_path", required=True,
                    help="Output (repaired) slide_spec.json path")
    ap.add_argument("--report", dest="report_path", default=None,
                    help="Optional path for the repair-report markdown")
    args = ap.parse_args()

    in_path = Path(args.in_path)
    if not in_path.is_file():
        print(f"Error: input not found: {in_path}", file=sys.stderr)
        return 1

    try:
        spec = json.loads(in_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"Error: cannot parse {in_path}: {e}", file=sys.stderr)
        return 1

    new_spec, coercions = repair_spec(spec)

    out_path = Path(args.out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(new_spec, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    if args.report_path is not None:
        report_path = Path(args.report_path)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        if coercions:
            body = (
                f"# Diagram repair report — {in_path.name}\n\n"
                f"**{len(coercions)} coercion(s) applied** to make "
                f"diagrams schema-conformant. Each line below names "
                f"the path, original value, and replacement.\n\n"
                + "\n".join(f"- {c}" for c in coercions)
                + "\n"
            )
        else:
            body = (
                f"# Diagram repair report — {in_path.name}\n\n"
                f"No coercions applied; all diagrams are "
                f"schema-conformant.\n"
            )
        report_path.write_text(body, encoding="utf-8")

    print(f"  -> repaired {len(coercions)} field(s); "
          f"wrote {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
