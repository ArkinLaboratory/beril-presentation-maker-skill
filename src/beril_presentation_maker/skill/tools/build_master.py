#!/usr/bin/env python3
"""build_master.py — derive kbase-presentation-master.pptx from user-supplied .potx.

This is a build-time script (NOT runtime). It is run when:
- The KBase brand changes and Adam supplies a refreshed .potx.
- The slide-shape vocabulary in SPEC §6 / DECISIONS D-008 is updated.

Inputs (relative to repo root):
    reference/master-template-source/KBase 2026 and beyond.potx
        (gitignored; user-supplied; never redistributed)

Outputs:
    src/beril_presentation_maker/skill/references/templates/kbase-presentation-master.pptx
    src/beril_presentation_maker/skill/references/kbase-brand-tokens.json

Pipeline:
    1. Validate source .potx exists.
    2. Convert content-type .potx → .pptx (python-pptx can't open .potx directly).
    3. Open in python-pptx; verify expected source structure.
    4. Rename 15 chosen layouts in slide master 0 to our named vocabulary.
    5. Remove the 17 unused layouts from slide master 0 (XML + parts + rels).
    6. Remove slide master 1 entirely (Google Slides round-trip duplicate).
    7. Save derived master.
    8. Emit kbase-brand-tokens.json from canonical Style Guide values
       (NOT extracted from .potx — Style Guide is the source of truth per
       reference/kbase-style-extract.md).
    9. Print a build report (layout names confirmed, sizes, etc.).

Idempotent: running twice from the same .potx produces byte-identical output
(modulo XML attribute ordering; tested via unzipped-content-equality).

References:
    - SPEC §6, §14.1 — slide-shape vocabulary, master template
    - DECISIONS D-007, D-008 — derived master, closed vocabulary
    - reference/master-template-source-notes.md — full derivation contract
    - reference/kbase-style-extract.md — brand tokens canonical source
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Iterable

# python-pptx
from pptx import Presentation
from pptx.oxml.ns import qn
from lxml import etree

# ---------------------------------------------------------------------------
# Layout mapping: source-layout-name → our named-vocabulary name.
#
# Mapping was chosen by inspecting the .potx (see
# reference/master-template-source-notes.md §2). Each source layout's
# placeholder shape was matched to the closest fit for our 15 named
# vocabulary entries. Indices in the table below are advisory; the mapping
# matches by source name (more stable than ordinal index).
# ---------------------------------------------------------------------------

LAYOUT_RENAMES: dict[str, str] = {
    # Source name (from KBase 2026 .potx)         → our SPEC §6 name
    "TITLE_1_2":                                  "title",
    "CUSTOM_4":                                   "section_divider",
    "CUSTOM_1":                                   "big_idea",
    "CUSTOM_3_3":                                 "big_number",
    "TITLE_AND_BODY_1_1_1_1_1_1_1_1_1":           "claim_evidence",
    "CUSTOM_1_1":                                 "two_column_compare",
    "TITLE_AND_BODY_1":                           "data_figure",
    "TITLE_AND_BODY_1_1_1_1":                     "workflow_diagram",
    "TITLE_AND_BODY_1_1_1_1_1_1_1":               "methods_summary",
    "TITLE_AND_BODY_1_2":                         "concept_illustration",
    "TITLE_AND_BODY_1_1_1_1_1_1_1_1_2":           "cross_tenant_integration",
    "TITLE_AND_BODY_1_1_1":                       "implications",
    "CUSTOM_5":                                   "acknowledgments",
    "TITLE_AND_BODY_1_1_2":                       "references",
    "TITLE_AND_BODY_1_1_1_1_1_2_1":               "qa_anticipated",
}

# The 15 expected names after renaming. Used for validation.
NAMED_VOCABULARY: tuple[str, ...] = tuple(LAYOUT_RENAMES.values())
assert len(NAMED_VOCABULARY) == 15, "vocabulary must be exactly 15 layouts"
assert len(set(NAMED_VOCABULARY)) == 15, "vocabulary names must be unique"


# ---------------------------------------------------------------------------
# Layout fixes — applied AFTER renaming.
#
# Adam reviewed the v0.1 derived master visually (2026-04-26) and identified
# placeholder positions in the source .potx that don't match the visual
# contract of our named layouts. Each fix is encoded here as a dict the
# build script can apply via XML manipulation.
#
# Adding a new fix:
#   1. Adam visually edits the layout in PowerPoint and re-saves the sample
#      deck.
#   2. Diff old vs. new layout XML to identify the substantive changes.
#   3. Append a fix entry below with rationale.
#   4. Run build_master.py; verify the fix matches Adam's intent visually.
#
# EMU = English Metric Unit, 914400 EMU = 1 inch.
# ---------------------------------------------------------------------------

INCH = 914400  # EMU per inch

LAYOUT_FIXES: dict[str, dict] = {
    # big_number: the source .potx places the TITLE in a tiny strip at
    # the top (0.1in × 0.6in tall, 9.3in wide). For a "big number" slide
    # where the number IS the slide, the title should be huge, bold, and
    # centered in the slide body. Adam's fix on 2026-04-26:
    "big_number": {
        "rationale": (
            "Headline statistic must be visually dominant. Source layout had "
            "the title as a top header strip; numbers like '27,000,000' or "
            "'90% accuracy' need to be the visual focus, not a header."
        ),
        "title_xfrm": {
            # Position + size (EMUs). ~(0.7, 1.0, 8.6 × 3.6 in) — large
            # centered area filling most of the 16:9 slide.
            "off_x": 660902,
            "off_y": 923453,
            "ext_cx": 7840301,
            "ext_cy": 3286408,
        },
        "title_body_pr": {
            "anchor": "ctr",          # vertical center
            "auto_fit_kind": "noAutofit",  # don't auto-shrink
        },
        "title_lvl1_ppr": {
            "algn": "ctr",            # horizontal center
        },
        "title_lvl1_def_rpr": {
            "sz": 6600,               # 66pt (PowerPoint half-points × 100)
            "b": 1,                   # bold
        },
    },
    # Other layouts may accumulate fixes here as visual review surfaces issues.
    # Keep each fix small and explicit — never a "while we're at it" sweep.
}


# ---------------------------------------------------------------------------
# Brand tokens — canonical from KBase Style Guide June 2022.
# See reference/kbase-style-extract.md §2, §3, §4, §5.
# ---------------------------------------------------------------------------

BRAND_TOKENS: dict = {
    "version": "1.0",
    "source": "KBase Style Guidelines — PRINT & PRESENTATION, June 2022",
    "palette": {
        "primary": {
            "microbe_orange":  {"hex": "#F78E1E", "rgb": [247, 142, 30],
                                "tints": {"80": "#F9A455", "60": "#FBBA8C", "40": "#FDD0BB", "20": "#FFE5CB"}},
            "grass_green":     {"hex": "#5E9732", "rgb": [94, 151, 50],
                                "tints": {"80": "#7EAC5B", "60": "#9EC184", "40": "#BED5AD", "20": "#DFEAD6"}},
            "freshwater_blue": {"hex": "#007DC3", "rgb": [0, 125, 195],
                                "tints": {"80": "#3397CF", "60": "#66B1DB", "40": "#99CBE7", "20": "#CCE5F3"}},
            "golden_yellow":   {"hex": "#FFD200", "rgb": [255, 210, 0],
                                "tints": {"80": "#FFDB33", "60": "#FFE466", "40": "#FFED99", "20": "#FFF6CC"}},
            "spring_green":    {"hex": "#C1CD23", "rgb": [193, 205, 35],
                                "tints": {"80": "#CDD659", "60": "#DAE183", "40": "#E6EBAC", "20": "#F3F5D6"}},
            "ocean_blue":      {"hex": "#72CCD2", "rgb": [114, 204, 210],
                                "tints": {"80": "#8ED6DB", "60": "#AAE0E4", "40": "#C6EAED", "20": "#E3F5F6"}}
        },
        "secondary": {
            "cyanobacteria_teal": {"hex": "#009688", "rgb": [0, 150, 136]},
            "lupine_purple":      {"hex": "#66489D", "rgb": [102, 72, 157]},
            "frost_blue":         {"hex": "#C7DBEE", "rgb": [199, 219, 238]},
            "rainier_cherry_red": {"hex": "#D2232A", "rgb": [210, 35, 42]},
            "graphite_gray":      {"hex": "#9D9389", "rgb": [157, 146, 135]}
        },
        "neutral": {
            "white": {"hex": "#FFFFFF"},
            "black": {"hex": "#000000"}
        },
        "contrast_warnings": [
            {"pair": ["spring_green", "golden_yellow"],
             "reason": "KBase Style Guide §5: forbidden as contrasting colors."}
        ]
    },
    "typography": {
        "primary": {"family": "Oxygen", "weights": ["Regular", "Bold", "Italic", "Bold Italic"]},
        "fallback": {"family": "Calibri", "weights": ["Regular", "Light", "Italic", "Bold"]},
        "code": {"family": "Courier", "weights": ["Regular", "Bold"]},
        "sizes_pt": {
            "deck_title": 60,
            "section_divider": 48,
            "big_idea": 60,
            "big_number": 96,
            "content_title": 36,
            "body": 24,
            "caption": 14,
            "ai_disclosure": 8
        }
    },
    "logo": {
        "min_height_pt": 36,
        "clear_space_x_factor": 0.5
    },
    "contrast_minima_wcag": {
        "body_text_aa_ratio": 4.5,
        "body_text_aaa_ratio": 7.0,
        "large_text_aa_ratio": 3.0,
        "large_text_aaa_ratio": 4.5
    },
    "vocabulary": list(NAMED_VOCABULARY)
}


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def repo_root() -> Path:
    """Walk up from this file until we find pyproject.toml at the repo root."""
    here = Path(__file__).resolve()
    for parent in [here, *here.parents]:
        if (parent / "pyproject.toml").is_file() and (parent / "SPEC.md").is_file():
            return parent
    raise RuntimeError(
        f"Could not locate repo root (looked for pyproject.toml + SPEC.md) starting from {here}"
    )


def potx_to_pptx_bytes(potx_path: Path) -> bytes:
    """Read a .potx and return the bytes of an equivalent .pptx (content type rewritten).

    python-pptx cannot open .potx directly. The only difference at the file
    level is the override declared in [Content_Types].xml: ...presentation.template
    vs ...presentation.presentation. Rewriting the content type produces a valid .pptx.
    """
    if not potx_path.is_file():
        raise FileNotFoundError(
            f"Source .potx not found at {potx_path}. "
            f"This file is gitignored and user-supplied; "
            f"see reference/master-template-source-notes.md §1 for sourcing details."
        )

    out = io.BytesIO()
    with zipfile.ZipFile(potx_path, "r") as zin, \
         zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "[Content_Types].xml":
                data = data.replace(
                    b"application/vnd.openxmlformats-officedocument.presentationml.template.main+xml",
                    b"application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml",
                )
            zout.writestr(item, data)
    return out.getvalue()


# ---------------------------------------------------------------------------
# python-pptx XML helpers
# ---------------------------------------------------------------------------

P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _set_layout_name(layout_part_xml: bytes, new_name: str) -> bytes:
    """Set <p:cSld name="..."> on a slide layout XML and return the updated bytes."""
    tree = etree.fromstring(layout_part_xml)
    csld = tree.find(qn("p:cSld"))
    if csld is None:
        raise ValueError("slideLayout XML missing <p:cSld> element")
    csld.set("name", new_name)
    return etree.tostring(tree, xml_declaration=True, encoding="UTF-8", standalone=True)


def _layout_name_from_xml(layout_part_xml: bytes) -> str:
    tree = etree.fromstring(layout_part_xml)
    csld = tree.find(qn("p:cSld"))
    return csld.get("name", "") if csld is not None else ""


def _drop_layout_refs_from_master_element(master_element, layout_rels_to_drop: set[str]) -> int:
    """Remove <p:sldLayoutId> entries from a slide master's <p:sldLayoutIdLst>
    whose r:id is in layout_rels_to_drop. Operates on the lxml element in-place.
    Returns count of refs removed.
    """
    lst = master_element.find(qn("p:sldLayoutIdLst"))
    if lst is None:
        return 0
    n = 0
    for layout_id in list(lst):
        rid = layout_id.get(qn("r:id"))
        if rid in layout_rels_to_drop:
            lst.remove(layout_id)
            n += 1
    return n


def _drop_master_ref_from_presentation_element(pres_element, master_rid: str) -> int:
    """Remove a <p:sldMasterId> with the given r:id from <p:sldMasterIdLst>.
    Operates on lxml element in-place. Returns count of refs removed.
    """
    lst = pres_element.find(qn("p:sldMasterIdLst"))
    if lst is None:
        return 0
    n = 0
    for master_id in list(lst):
        rid = master_id.get(qn("r:id"))
        if rid == master_rid:
            lst.remove(master_id)
            n += 1
    return n


def _apply_big_number_fix(layout_element, fix: dict) -> None:
    """Apply Adam's 2026-04-26 fix to the big_number layout.

    Operates on the lxml element of a slideLayout XML, in place.
    Fix targets the title placeholder (idx 0).

    See LAYOUT_FIXES['big_number'] for rationale.
    """
    a_ns = "http://schemas.openxmlformats.org/drawingml/2006/main"
    p_ns = "http://schemas.openxmlformats.org/presentationml/2006/main"

    # Find the TITLE placeholder shape (idx 0 by convention; falls back to
    # first <p:sp> with <p:ph type="title">).
    title_sp = None
    for sp in layout_element.iter(f"{{{p_ns}}}sp"):
        ph = sp.find(f".//{{{p_ns}}}nvSpPr/{{{p_ns}}}nvPr/{{{p_ns}}}ph")
        if ph is None:
            continue
        if ph.get("type") == "title" or ph.get("idx", "0") == "0":
            title_sp = sp
            break
    if title_sp is None:
        raise ValueError("big_number layout: TITLE placeholder not found")

    # 1. Title position + size: <a:xfrm><a:off/><a:ext/></a:xfrm>
    xfrm = title_sp.find(f".//{{{a_ns}}}xfrm")
    if xfrm is None:
        raise ValueError("big_number TITLE has no <a:xfrm>")
    off = xfrm.find(f"{{{a_ns}}}off")
    ext = xfrm.find(f"{{{a_ns}}}ext")
    if off is None or ext is None:
        raise ValueError("big_number TITLE <a:xfrm> missing <a:off> or <a:ext>")
    title_xfrm = fix["title_xfrm"]
    off.set("x", str(title_xfrm["off_x"]))
    off.set("y", str(title_xfrm["off_y"]))
    ext.set("cx", str(title_xfrm["ext_cx"]))
    ext.set("cy", str(title_xfrm["ext_cy"]))

    # 2. Title body anchor + autofit: <p:txBody><a:bodyPr anchor="ctr">
    #    Replace child <a:normAutofit/> with <a:noAutofit/>.
    body_pr = title_sp.find(f".//{{{p_ns}}}txBody/{{{a_ns}}}bodyPr")
    if body_pr is None:
        raise ValueError("big_number TITLE <p:txBody> missing <a:bodyPr>")
    body_pr.set("anchor", fix["title_body_pr"]["anchor"])

    # remove existing autofit child(ren)
    for tag in ("normAutofit", "noAutofit", "spAutoFit"):
        for child in list(body_pr):
            if child.tag == f"{{{a_ns}}}{tag}":
                body_pr.remove(child)
    # add <a:noAutofit/>
    body_pr.append(etree.SubElement(body_pr, f"{{{a_ns}}}{fix['title_body_pr']['auto_fit_kind']}"))
    # the SubElement helper appends already; remove duplicate (defensive)
    children = body_pr.findall(f"{{{a_ns}}}{fix['title_body_pr']['auto_fit_kind']}")
    for extra in children[1:]:
        body_pr.remove(extra)

    # 3. lvl1pPr alignment: <a:lstStyle><a:lvl1pPr algn="ctr">
    lst_style = title_sp.find(f".//{{{p_ns}}}txBody/{{{a_ns}}}lstStyle")
    if lst_style is None:
        raise ValueError("big_number TITLE <p:txBody> missing <a:lstStyle>")
    lvl1 = lst_style.find(f"{{{a_ns}}}lvl1pPr")
    if lvl1 is None:
        raise ValueError("big_number TITLE <a:lstStyle> missing <a:lvl1pPr>")
    lvl1.set("algn", fix["title_lvl1_ppr"]["algn"])

    # 4. defRPr font size + bold: <a:lvl1pPr>...<a:defRPr sz=N b=1/>
    def_rpr = lvl1.find(f"{{{a_ns}}}defRPr")
    if def_rpr is None:
        # create one
        def_rpr = etree.SubElement(lvl1, f"{{{a_ns}}}defRPr")
    def_rpr.set("sz", str(fix["title_lvl1_def_rpr"]["sz"]))
    def_rpr.set("b", str(fix["title_lvl1_def_rpr"]["b"]))


def _apply_layout_fixes(prs, verbose: bool = True) -> list[str]:
    """Apply all LAYOUT_FIXES to the post-rename presentation. Returns list of
    layout names that received fixes.
    """
    applied: list[str] = []
    layouts = {l.name: l for l in prs.slide_masters[0].slide_layouts}
    for layout_name, fix in LAYOUT_FIXES.items():
        if layout_name not in layouts:
            raise ValueError(
                f"LAYOUT_FIXES references '{layout_name}' but this layout "
                f"is not present in the renamed master. Check LAYOUT_RENAMES."
            )
        layout = layouts[layout_name]
        # Each layout has its own dispatcher. Currently only big_number; add
        # more dispatchers when LAYOUT_FIXES grows.
        if layout_name == "big_number":
            _apply_big_number_fix(layout.element, fix)
        else:
            raise NotImplementedError(
                f"LAYOUT_FIXES['{layout_name}'] has no applier registered. "
                f"Add a _apply_<layout_name>_fix function."
            )
        applied.append(layout_name)
        if verbose:
            print(f"[build_master] applied layout fix: {layout_name}")
    return applied


def _drop_all_slide_refs_from_presentation_element(pres_element) -> int:
    """Remove ALL <p:sldId> entries from <p:sldIdLst>. The derived master ships with
    no slides (the assembler creates fresh decks each invocation).
    Returns count of refs removed.
    """
    lst = pres_element.find(qn("p:sldIdLst"))
    if lst is None:
        return 0
    n = 0
    for sld_id in list(lst):
        lst.remove(sld_id)
        n += 1
    return n


# ---------------------------------------------------------------------------
# Build pipeline
# ---------------------------------------------------------------------------

def build_master(source_potx: Path, dest_pptx: Path, brand_tokens_dest: Path,
                 verbose: bool = True) -> dict:
    """Run the full build pipeline. Returns a build-report dict."""
    report: dict = {
        "source": str(source_potx),
        "dest_master": str(dest_pptx),
        "dest_brand_tokens": str(brand_tokens_dest),
        "renamed_layouts": [],
        "deleted_layouts": [],
        "deleted_masters": [],
    }

    # Step 1: validate + convert content-type
    pptx_bytes = potx_to_pptx_bytes(source_potx)

    # Step 2: open with python-pptx for inspection
    prs = Presentation(io.BytesIO(pptx_bytes))
    if len(prs.slide_masters) == 0:
        raise ValueError("source has no slide masters")

    if verbose:
        print(f"[build_master] source has {len(prs.slide_masters)} slide masters, "
              f"master[0] has {len(prs.slide_masters[0].slide_layouts)} layouts")

    master0 = prs.slide_masters[0]

    # Step 3: identify layouts in master 0 to keep (by source name) vs delete
    keep_source_names = set(LAYOUT_RENAMES.keys())
    keep_indices: dict[str, int] = {}
    drop_indices: list[int] = []

    for li, layout in enumerate(master0.slide_layouts):
        if layout.name in keep_source_names:
            if layout.name in keep_indices:
                # Duplicate source name (shouldn't happen — but guard)
                drop_indices.append(li)
            else:
                keep_indices[layout.name] = li
        else:
            drop_indices.append(li)

    missing = keep_source_names - set(keep_indices.keys())
    if missing:
        raise ValueError(
            f"source master is missing expected layouts: {sorted(missing)}\n"
            f"available layout names: {sorted(l.name for l in master0.slide_layouts)}\n"
            f"this is a brand-version skew; update LAYOUT_RENAMES in build_master.py "
            f"or restore the missing layouts in the .potx."
        )

    if verbose:
        print(f"[build_master] keep {len(keep_indices)} layouts, "
              f"drop {len(drop_indices)} layouts from master[0]")

    # Step 4: rename kept layouts via XML
    rename_summary = []
    for source_name, new_name in LAYOUT_RENAMES.items():
        idx = keep_indices[source_name]
        layout = master0.slide_layouts[idx]
        # python-pptx exposes layout.element (lxml node). Set <p:cSld name="...">
        csld = layout.element.find(qn("p:cSld"))
        if csld is None:
            raise ValueError(f"layout '{source_name}' has no <p:cSld>")
        csld.set("name", new_name)
        rename_summary.append((source_name, new_name))

    report["renamed_layouts"] = [{"from": s, "to": d} for (s, d) in rename_summary]

    # Step 5: drop unused layouts from master 0
    # python-pptx doesn't expose layout deletion, so manipulate the package directly
    pkg = prs.part.package
    master0_part = master0.part

    # collect (source_name, rel_id, partname) for layouts to drop
    drops: list[tuple[str, str, str]] = []
    for li in drop_indices:
        layout = master0.slide_layouts[li]
        # find the relationship from master0 to this layout
        rel = next(
            (r for r in master0_part.rels.values()
             if r.target_part is layout.part), None)
        if rel is None:
            continue
        drops.append((layout.name, rel.rId, layout.part.partname))

    # remove them from master0's relationships
    # (python-pptx 1.x prunes orphaned parts at save time — verified empirically;
    # we don't need to touch package._parts directly. Dropping the rel is sufficient.)
    drop_rids = {rid for (_, rid, _) in drops}
    for (_, rid, _) in drops:
        if rid in master0_part.rels:
            master0_part.rels.pop(rid)

    # remove <p:sldLayoutId> references from master XML (in-place on element)
    _drop_layout_refs_from_master_element(master0_part._element, drop_rids)

    report["deleted_layouts"] = [{"name": n, "rId": r} for (n, r, _) in drops]

    # Step 5b: apply hand-tuned layout fixes (Adam's visual review).
    applied_fixes = _apply_layout_fixes(prs, verbose=verbose)
    report["applied_fixes"] = applied_fixes

    # Step 6: drop slide_masters[1:] (Google Slides round-trip duplicates)
    pres_part = prs.part
    if len(prs.slide_masters) > 1:
        masters_to_drop = list(prs.slide_masters)[1:]
        master_drop_rids: list[str] = []
        for extra in masters_to_drop:
            extra_part = extra.part
            # find rel from presentation → this master
            rel = next(
                (r for r in pres_part.rels.values()
                 if r.target_part is extra_part), None)
            if rel is None:
                continue
            master_drop_rids.append(rel.rId)
            # remove its layouts (cascade) — drop rels only, parts are pruned at save
            for layout in list(extra.slide_layouts):
                lay_rel = next(
                    (r for r in extra_part.rels.values()
                     if r.target_part is layout.part), None)
                if lay_rel is not None and lay_rel.rId in extra_part.rels:
                    extra_part.rels.pop(lay_rel.rId)
            # remove the master rel from the presentation
            if rel.rId in pres_part.rels:
                pres_part.rels.pop(rel.rId)
            report["deleted_masters"].append(
                {"partname": str(extra_part.partname), "rId": rel.rId}
            )

        # remove <p:sldMasterId> references from presentation.xml (in-place)
        for rid in master_drop_rids:
            _drop_master_ref_from_presentation_element(pres_part._element, rid)

    # Step 6b: drop ALL slides from the .potx — the derived master ships empty.
    # Source slides (32 in the Gazi example deck) are template fodder; the
    # assembler creates fresh decks per invocation.
    slide_rids_to_drop: list[str] = []
    if hasattr(prs, "slides"):
        for slide in list(prs.slides):
            slide_part = slide.part
            slide_rel = next(
                (r for r in pres_part.rels.values()
                 if r.target_part is slide_part), None)
            if slide_rel is None:
                continue
            slide_rids_to_drop.append(slide_rel.rId)
            if slide_rel.rId in pres_part.rels:
                pres_part.rels.pop(slide_rel.rId)
    n_slides_dropped = _drop_all_slide_refs_from_presentation_element(pres_part._element)
    report["deleted_slides_count"] = n_slides_dropped

    # Step 7: save derived master
    dest_pptx.parent.mkdir(parents=True, exist_ok=True)
    prs.save(dest_pptx)

    # Step 8: emit brand-tokens JSON
    brand_tokens_dest.parent.mkdir(parents=True, exist_ok=True)
    brand_tokens_dest.write_text(
        json.dumps(BRAND_TOKENS, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    # Step 9: hash the output for idempotency check
    dest_bytes = dest_pptx.read_bytes()
    report["dest_master_sha256"] = hashlib.sha256(dest_bytes).hexdigest()
    report["dest_master_size_bytes"] = len(dest_bytes)

    if verbose:
        print(f"[build_master] wrote {dest_pptx} "
              f"({len(dest_bytes):,} bytes; sha256={report['dest_master_sha256'][:12]}...)")
        print(f"[build_master] wrote {brand_tokens_dest}")

    return report


# ---------------------------------------------------------------------------
# Verification helpers (also used by test_build_master.py)
# ---------------------------------------------------------------------------

def verify_built_master(master_pptx: Path) -> dict:
    """Open the built master, verify all 15 named layouts present + no extras, and return
    a structured report.
    """
    prs = Presentation(master_pptx)
    n_masters = len(prs.slide_masters)
    if n_masters != 1:
        raise AssertionError(f"expected exactly 1 slide master, got {n_masters}")

    layouts = list(prs.slide_masters[0].slide_layouts)
    found_names = sorted(l.name for l in layouts)
    expected_names = sorted(NAMED_VOCABULARY)

    if found_names != expected_names:
        extra = sorted(set(found_names) - set(expected_names))
        missing = sorted(set(expected_names) - set(found_names))
        raise AssertionError(
            f"layout name mismatch:\n"
            f"  extra:   {extra}\n"
            f"  missing: {missing}"
        )

    # Each layout must have at least one TITLE placeholder (or be one of the
    # exempt layouts in SPEC §6.1 — references / acknowledgments / qa_anticipated
    # all still happen to have titles in our mapping, so no exemption needed).
    title_check = []
    for layout in layouts:
        has_title = any(
            ph.placeholder_format.idx == 0
            for ph in layout.placeholders
        )
        title_check.append({"layout": layout.name, "has_title_placeholder": has_title})

    return {
        "n_masters": n_masters,
        "n_layouts": len(layouts),
        "layout_names_sorted": found_names,
        "title_check": title_check,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="build_master",
        description="Build kbase-presentation-master.pptx from user-supplied .potx.",
    )
    parser.add_argument(
        "--source", "-s",
        type=Path,
        default=None,
        help="Path to source .potx (default: <repo>/reference/master-template-source/KBase 2026 and beyond.potx)",
    )
    parser.add_argument(
        "--dest", "-d",
        type=Path,
        default=None,
        help="Path to derived .pptx output (default: <repo>/src/.../skill/references/templates/kbase-presentation-master.pptx)",
    )
    parser.add_argument(
        "--brand-tokens",
        type=Path,
        default=None,
        help="Path to kbase-brand-tokens.json output (default: <repo>/src/.../skill/references/kbase-brand-tokens.json)",
    )
    parser.add_argument(
        "--quiet", "-q", action="store_true", help="Suppress build progress output.",
    )
    parser.add_argument(
        "--verify-only", action="store_true",
        help="Don't rebuild; verify the existing derived master matches expected vocabulary.",
    )
    args = parser.parse_args(argv)

    root = repo_root()
    source = args.source or (root / "reference" / "master-template-source" /
                             "KBase 2026 and beyond.potx")
    dest = args.dest or (root / "src" / "beril_presentation_maker" / "skill" /
                         "references" / "templates" / "kbase-presentation-master.pptx")
    brand = args.brand_tokens or (root / "src" / "beril_presentation_maker" / "skill" /
                                  "references" / "kbase-brand-tokens.json")

    if args.verify_only:
        report = verify_built_master(dest)
        print(json.dumps(report, indent=2))
        return 0

    try:
        report = build_master(source, dest, brand, verbose=not args.quiet)
    except FileNotFoundError as e:
        print(f"build_master: {e}", file=sys.stderr)
        return 3
    except ValueError as e:
        print(f"build_master: {e}", file=sys.stderr)
        return 2

    # Verify after building.
    verify = verify_built_master(dest)
    report["verification"] = verify
    if not args.quiet:
        print(f"[build_master] verification: {verify['n_layouts']} layouts, "
              f"{verify['n_masters']} masters; all 15 named layouts present.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
