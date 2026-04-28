#!/usr/bin/env python3
"""diagram_render.py — render slide_spec diagram dicts to python-pptx shapes.

Per SPEC §8.2 + D-014: Tier 2 figure handling. Workflow / architecture /
ER / decision-tree diagrams are rendered as python-pptx NATIVE shapes
(AutoShapes + Connectors + TextBoxes), not as raster images. This keeps
the diagram editable in PowerPoint / Keynote / Slides downstream.

Inputs (one diagram, defined in slide_spec.py):

  diagram = {
    "kind": "boxes_and_arrows",
    "nodes": [
      {"id": "n1", "label": "Start", "shape": "rounded",
       "x": 0.5, "y": 1.0, "w": 1.5, "h": 0.8,
       "fill_color": "freshwater_blue", "text_color": "white"},
      ...
    ],
    "edges": [
      {"from": "n1", "to": "n2", "kind": "straight", "label": "..."},
      ...
    ],
  }

Coordinates are inches with (0, 0) at upper-left of `region` (passed by
caller — the body region of the slide). Brand colors are KBase palette
names; resolved against `kbase-brand-tokens.json`.

Library:

    from diagram_render import render_diagram
    render_diagram(slide, diagram, region=(0.5, 1.4, 9.0, 3.5),
                   brand_tokens=tokens)

Tests live at tests/unit/test_diagram_render.py.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE, MSO_CONNECTOR
from pptx.util import Emu, Inches, Pt


# ---------------------------------------------------------------------------
# Shape + connector mappings (mirrors slide_spec.DIAGRAM_NODE_SHAPES + DIAGRAM_EDGE_KINDS)
# ---------------------------------------------------------------------------

NODE_SHAPE_MAP: dict[str, int] = {
    "rectangle":      MSO_SHAPE.RECTANGLE,
    "rounded":        MSO_SHAPE.ROUNDED_RECTANGLE,
    "ellipse":        MSO_SHAPE.OVAL,
    "parallelogram":  MSO_SHAPE.PARALLELOGRAM,
    "cylinder":       MSO_SHAPE.CAN,                 # database-y
    "callout":        MSO_SHAPE.RECTANGULAR_CALLOUT,
    "swimlane":       MSO_SHAPE.RECTANGLE,           # rendered no-fill
}

EDGE_KIND_MAP: dict[str, int] = {
    "straight": MSO_CONNECTOR.STRAIGHT,
    "elbow":    MSO_CONNECTOR.ELBOW,
    "curved":   MSO_CONNECTOR.CURVE,
}


# ---------------------------------------------------------------------------
# Defaults / fallbacks
# ---------------------------------------------------------------------------

# Default fill / text colors when a node doesn't specify (KBase palette).
DEFAULT_NODE_FILL = "freshwater_blue"
DEFAULT_NODE_TEXT = "white"
DEFAULT_SWIMLANE_BORDER = "graphite_gray"

# Hardcoded fallback hexes if brand_tokens not provided. Matches
# kbase-brand-tokens.json (KBase Style Guide June 2022).
_FALLBACK_HEX = {
    "microbe_orange":     "#F78E1E",
    "grass_green":        "#5E9732",
    "freshwater_blue":    "#007DC3",
    "golden_yellow":      "#FFD200",
    "spring_green":       "#C1CD23",
    "ocean_blue":         "#72CCD2",
    "cyanobacteria_teal": "#009688",
    "lupine_purple":      "#66489D",
    "frost_blue":         "#C7DBEE",
    "rainier_cherry_red": "#D2232A",
    "graphite_gray":      "#9D9389",
    "white":              "#FFFFFF",
    "black":              "#000000",
}


@dataclass
class _RenderedShape:
    """Internal — the python-pptx shape we created for a node, plus its
    intended center coordinates. Used to compute connector endpoints."""
    node_id: str
    shape: Any                     # python-pptx shape object
    cx: float                      # center x (inches)
    cy: float                      # center y (inches)


# ---------------------------------------------------------------------------
# Brand-color resolution
# ---------------------------------------------------------------------------

def resolve_color(name_or_hex: str | None,
                  brand_tokens: dict | None,
                  default_token: str = DEFAULT_NODE_FILL) -> RGBColor:
    """Resolve a color reference (palette token or '#RRGGBB') to RGBColor.

    Resolution order:
      1. If name_or_hex starts with '#', parse as hex.
      2. If brand_tokens provided, look up by name in palette.primary
         then palette.secondary then palette.neutral.
      3. Fallback to _FALLBACK_HEX.
      4. If still unresolved, fall back to the default_token through the
         same chain.
    """
    candidates = [name_or_hex, default_token]
    for c in candidates:
        if c is None:
            continue
        if isinstance(c, str) and c.startswith("#") and len(c) == 7:
            return RGBColor.from_string(c[1:].upper())
        # Brand token lookup
        if brand_tokens is not None:
            palette = brand_tokens.get("palette", {}) if isinstance(brand_tokens, dict) else {}
            for group in ("primary", "secondary", "neutral"):
                grp = palette.get(group, {})
                if c in grp:
                    hexv = grp[c].get("hex", "")
                    if hexv.startswith("#") and len(hexv) == 7:
                        return RGBColor.from_string(hexv[1:].upper())
        # Hardcoded fallback
        if c in _FALLBACK_HEX:
            return RGBColor.from_string(_FALLBACK_HEX[c][1:].upper())
    # Final fallback: white
    return RGBColor(0xFF, 0xFF, 0xFF)


# ---------------------------------------------------------------------------
# Coordinate transform (diagram → slide)
# ---------------------------------------------------------------------------

def _transform_coords(
    x_in: float, y_in: float,
    region: tuple[float, float, float, float],
) -> tuple[float, float]:
    """Pass through diagram coordinates as ABSOLUTE slide coords.

    2026-04-27 fix #78: previous version added region.top + region.left
    to (x, y), assuming coords were diagram-local (origin at region
    top-left). But:
      - slide_compose.v1.md tells the LLM 'Default region: x in [0.5,
        9.5], y in [1.4, 5.6]' — absolute slide coords.
      - repair_diagram_stubs.compute_linear_geometry produces absolute
        slide coords (CONTENT_LEFT=0.5, CONTENT_TOP=1.4 already
        baked in).
      - The renderer's region.top=1.30 was being ADDED to absolute y
        values like 5.0, producing slide y=6.30 (off-slide; slide
        height is 5.625in). Live failure draft_7 slide 11: 8 nodes
        with y up to 5.0 rendered partly off-slide.

    Treat region as the BOUNDS the diagram should fit within, not an
    origin offset. Coordinates pass through. The region tuple stays
    in the signature for future use (e.g., scaling-to-fit when a
    diagram is generated for a smaller region than the master's
    workflow_diagram body).
    """
    return x_in, y_in


# ---------------------------------------------------------------------------
# Node rendering
# ---------------------------------------------------------------------------

def _render_node(
    slide,
    node: dict,
    region: tuple[float, float, float, float],
    brand_tokens: dict | None,
) -> _RenderedShape:
    """Add one node shape to the slide. Returns metadata for connector drawing."""
    shape_kind = node.get("shape", "rectangle")
    if shape_kind not in NODE_SHAPE_MAP:
        raise ValueError(
            f"unknown node shape: {shape_kind!r}; valid: {sorted(NODE_SHAPE_MAP.keys())}"
        )
    mso_shape = NODE_SHAPE_MAP[shape_kind]

    x, y = _transform_coords(float(node["x"]), float(node["y"]), region)
    w = float(node["w"])
    h = float(node["h"])

    sp = slide.shapes.add_shape(
        mso_shape,
        Inches(x), Inches(y), Inches(w), Inches(h),
    )

    # Fill + outline
    fill_color_name = node.get("fill_color", DEFAULT_NODE_FILL)
    text_color_name = node.get("text_color", DEFAULT_NODE_TEXT)

    if shape_kind == "swimlane":
        # Swimlanes are containers — outline only, no fill.
        sp.fill.background()
        sp.line.color.rgb = resolve_color(
            DEFAULT_SWIMLANE_BORDER, brand_tokens, DEFAULT_SWIMLANE_BORDER,
        )
    else:
        sp.fill.solid()
        sp.fill.fore_color.rgb = resolve_color(
            fill_color_name, brand_tokens, DEFAULT_NODE_FILL,
        )
        sp.line.fill.background()  # no outline on filled nodes by default

    # Label
    label = node.get("label", "")
    if label:
        tf = sp.text_frame
        tf.text = label
        # Color the text based on text_color_name
        for paragraph in tf.paragraphs:
            for run in paragraph.runs:
                run.font.color.rgb = resolve_color(
                    text_color_name, brand_tokens, DEFAULT_NODE_TEXT,
                )
                run.font.size = Pt(14)

    return _RenderedShape(
        node_id=node["id"],
        shape=sp,
        cx=x + w / 2,
        cy=y + h / 2,
    )


# ---------------------------------------------------------------------------
# Edge rendering
# ---------------------------------------------------------------------------

def _render_edge(
    slide,
    edge: dict,
    rendered_by_id: dict[str, _RenderedShape],
    brand_tokens: dict | None,
) -> None:
    """Add one connector line between source and target node shapes."""
    edge_kind = edge.get("kind", "straight")
    if edge_kind not in EDGE_KIND_MAP:
        raise ValueError(
            f"unknown edge kind: {edge_kind!r}; valid: {sorted(EDGE_KIND_MAP.keys())}"
        )
    mso_connector = EDGE_KIND_MAP[edge_kind]

    src_id = edge.get("from")
    dst_id = edge.get("to")
    if src_id not in rendered_by_id or dst_id not in rendered_by_id:
        # Skip edges referencing missing nodes — diagram_design prompt
        # should never produce these, but the validator catches it as
        # well via slide_spec validation.
        return

    src = rendered_by_id[src_id]
    dst = rendered_by_id[dst_id]

    # Use shape edge midpoints for cleaner endpoints than centers.
    # Crude heuristic: aim from src center toward dst center, but
    # snap to the nearest shape edge.
    line = slide.shapes.add_connector(
        mso_connector,
        Inches(src.cx), Inches(src.cy),
        Inches(dst.cx), Inches(dst.cy),
    )
    # Color the line graphite-gray (KBase palette neutral)
    line.line.color.rgb = resolve_color(
        "graphite_gray", brand_tokens, "graphite_gray",
    )

    # Edge labels: render as a small text box positioned ABOVE the line
    # (not at center y). Original 2026-04-26 implementation centered the
    # label at (mid_x, mid_y) where mid_y == node center y, so labels
    # rendered ON the nodes themselves (live failure draft_2). 2026-04-27
    # fix #54: offset label upward by 0.30in (above line) and shrink
    # textbox width to 0.7in so it fits in the inter-node gap rather
    # than spanning into adjacent nodes.
    label = edge.get("label", "")
    if label:
        mid_x = (src.cx + dst.cx) / 2
        mid_y = (src.cy + dst.cy) / 2
        # Heuristic: if endpoints are roughly horizontal (|dy|<0.3),
        # offset label above by 0.30in. If vertical (|dx|<0.3), offset
        # right. Otherwise (diagonal), offset above-and-right by half each.
        dy = abs(dst.cy - src.cy)
        dx = abs(dst.cx - src.cx)
        if dy < 0.3:
            label_x = mid_x - 0.35
            label_y = mid_y - 0.40   # above the line
        elif dx < 0.3:
            label_x = mid_x + 0.10   # right of the line
            label_y = mid_y - 0.15
        else:
            label_x = mid_x - 0.20
            label_y = mid_y - 0.30
        tb = slide.shapes.add_textbox(
            Inches(label_x), Inches(label_y),
            Inches(0.70), Inches(0.25),
        )
        tb.text_frame.text = label
        for paragraph in tb.text_frame.paragraphs:
            for run in paragraph.runs:
                run.font.size = Pt(9)
                run.font.color.rgb = resolve_color(
                    "graphite_gray", brand_tokens, "graphite_gray",
                )


# ---------------------------------------------------------------------------
# Top-level render
# ---------------------------------------------------------------------------

def render_diagram(
    slide,
    diagram: dict,
    region: tuple[float, float, float, float],
    brand_tokens: dict | None = None,
) -> None:
    """Render a slide_spec diagram into a python-pptx slide.

    Args:
      slide: python-pptx Slide object.
      diagram: slide_spec diagram dict (kind, nodes, edges).
      region: (left, top, width, height) in inches — the slide region
              the diagram fits into. Diagram-local (x, y) coords map to
              region.left + x, region.top + y.
      brand_tokens: parsed kbase-brand-tokens.json (or None for hardcoded
                    fallback hexes).

    Raises:
      ValueError on unknown shape / edge kind. (Schema validator should
      have caught these before render.)
    """
    if diagram.get("kind") != "boxes_and_arrows":
        raise ValueError(
            f"unsupported diagram kind: {diagram.get('kind')!r} "
            f"(only 'boxes_and_arrows' supported in v0.1; "
            f"see SPEC §6 / DECISIONS D-028 for v0.2 plans)"
        )

    # 2026-04-27 fix #54: render order matters for visual quality.
    # python-pptx z-order = paint order (later shapes on top). When
    # nodes were rendered first then edges second, the connector lines
    # painted OVER the node box fills — endpoints appeared to bisect
    # the boxes (live failure draft_2 visual review).
    #
    # Fix: pre-compute node centers from node geometry (without adding
    # shapes to the slide), render edges using those centers, THEN
    # render node shapes on top. Node fills now occlude edge endpoints
    # cleanly — the line appears to "enter" the node edge.
    nodes = diagram.get("nodes", []) or []
    edges = diagram.get("edges", []) or []

    # Pre-compute centers (no slide mutation yet)
    centers_by_id: dict[str, tuple[float, float]] = {}
    for node in nodes:
        node_id = node.get("id", "")
        x, y = _transform_coords(float(node["x"]), float(node["y"]), region)
        w = float(node["w"])
        h = float(node["h"])
        centers_by_id[node_id] = (x + w / 2, y + h / 2)

    # Pass 1: render edges using computed centers
    edge_proxy: dict[str, _RenderedShape] = {
        nid: _RenderedShape(node_id=nid, shape=None, cx=cx, cy=cy)
        for nid, (cx, cy) in centers_by_id.items()
    }
    for edge in edges:
        _render_edge(slide, edge, edge_proxy, brand_tokens)

    # Pass 2: render node shapes on top of edges
    rendered_by_id: dict[str, _RenderedShape] = {}
    for node in nodes:
        rs = _render_node(slide, node, region, brand_tokens)
        rendered_by_id[rs.node_id] = rs


# ---------------------------------------------------------------------------
# Brand-tokens loader
# ---------------------------------------------------------------------------

def load_brand_tokens(path: Path | str | None = None) -> dict | None:
    """Convenience: load kbase-brand-tokens.json from the shipped
    references dir (default) or a user-supplied path."""
    if path is None:
        here = Path(__file__).resolve().parent
        path = here.parent / "references" / "kbase-brand-tokens.json"
    p = Path(path)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


# ---------------------------------------------------------------------------
# CLI (smoke testing)
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="diagram_render",
        description="Render a slide_spec diagram dict into a one-slide pptx "
                    "for visual smoke testing.",
    )
    parser.add_argument("diagram_json",
                        help="Path to a JSON file containing a single diagram dict.")
    parser.add_argument("--out", required=True, help="Output .pptx path.")
    parser.add_argument("--brand-tokens",
                        help="Path to kbase-brand-tokens.json "
                             "(default: shipped one).")
    parser.add_argument("--region", default="0.5,1.4,9.0,3.5",
                        help="Comma-separated 4-tuple in inches "
                             "(left,top,width,height). Default: 0.5,1.4,9.0,3.5")
    args = parser.parse_args(argv)

    diagram = json.loads(Path(args.diagram_json).read_text(encoding="utf-8"))
    region = tuple(float(x) for x in args.region.split(","))
    if len(region) != 4:
        print("--region must be 4 comma-separated floats", file=sys.stderr)
        return 2
    tokens = load_brand_tokens(args.brand_tokens)

    # Build a minimal pptx
    from pptx import Presentation
    prs = Presentation()
    blank_layout = prs.slide_layouts[6]  # blank layout
    slide = prs.slides.add_slide(blank_layout)
    render_diagram(slide, diagram, region, tokens)
    prs.save(args.out)
    print(f"wrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
