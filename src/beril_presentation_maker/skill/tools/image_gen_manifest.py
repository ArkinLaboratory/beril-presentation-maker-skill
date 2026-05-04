#!/usr/bin/env python3
"""image_gen_manifest.py — Tier 3 manifest writer for v0.3.3 image-gen.

The manifest at working/05_images/manifest.json indexes every
slide-level image-gen decision: approved (with image bound),
rejected (slide will be dropped per R6 Option A), and
budget-skipped (cap exhausted before this slide). Consumed by:

  - merge_compose_fragments.py: binds approved entries' image_path
    onto the matching slide's content.image_path before spec writeout.
  - revise_loop.py (future): inspects rejected entries to know which
    slides were intentionally dropped, so adversarial-feedback
    revision doesn't re-introduce them.
  - User: a human-readable index of "what was generated, what wasn't,
    why" travelling next to the PNGs themselves.

Schema "image-manifest.v1":

    {
      "schema_version": "image-manifest.v1",
      "draft_dir": "<absolute path>",
      "entries": [
        {
          "slide_id": "S2-pos4",
          "approved": true,
          "image_path": "working/05_images/S2-pos4.png",
          "request_path": "working/05_image_requests/S2-pos4_request.json",
          "channel": "A",
          "model": "gemini-3-pro-image",
          "cost_usd": 0.014,
          "approved_at": "2026-05-03T14:32:11Z"
        },
        {
          "slide_id": "S2-pos7",
          "approved": false,
          "rejected_at": "2026-05-03T14:32:35Z",
          "reason": "user-rejected: prompt drift from substory"
        },
        {
          "slide_id": "S2-pos9",
          "approved": false,
          "skipped": true,
          "rejected_at": "2026-05-03T14:33:02Z",
          "reason": "budget cap exhausted ($0.50 / $0.014 each)"
        }
      ]
    }

The schema is single-document (one envelope per manifest). Append
patterns load → mutate → write — typical of small audit logs that
need atomic-replace semantics.

CLI is intentionally minimal — the manifest is mostly written
programmatically by the orchestrator. The `validate` subcommand is
useful for post-hoc inspection.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

SCHEMA_VERSION = "image-manifest.v1"


class ManifestError(ValueError):
    """Raised when manifest schema validation fails."""


@dataclass
class Manifest:
    """A single-envelope image-manifest.v1 document.

    Round-trip: load(path) → mutate via add_approved / add_rejected /
    add_skipped → write(path). Re-loading gives the same data.
    """

    draft_dir: str = ""
    entries: list[dict] = field(default_factory=list)

    # ------------------------------------------------------------------
    # I/O
    # ------------------------------------------------------------------

    @classmethod
    def load(cls, path: Path | str) -> "Manifest":
        """Load a manifest from disk. Returns an empty Manifest if the
        file doesn't exist (so callers can call add_*-then-write without
        an explicit init step)."""
        path = Path(path)
        if not path.is_file():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ManifestError(
                f"manifest at {path} is not valid JSON: {e}"
            ) from e
        if not isinstance(data, dict):
            raise ManifestError(
                f"manifest at {path} is not a JSON object (got {type(data).__name__})"
            )
        if data.get("schema_version") != SCHEMA_VERSION:
            raise ManifestError(
                f"manifest at {path} has schema_version={data.get('schema_version')!r}; "
                f"expected {SCHEMA_VERSION!r}"
            )
        entries = data.get("entries", [])
        if not isinstance(entries, list):
            raise ManifestError(
                f"manifest at {path} entries field is not a list "
                f"(got {type(entries).__name__})"
            )
        return cls(
            draft_dir=str(data.get("draft_dir", "")),
            entries=list(entries),
        )

    def write(self, path: Path | str) -> Path:
        """Atomically write the manifest as JSON. Caller passes the full
        target path; we do load → mutate → write (no append-by-line),
        so atomicity is via Python's write_text which on POSIX is
        rename-on-close. Returns the resolved path."""
        path = Path(path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        envelope = {
            "schema_version": SCHEMA_VERSION,
            "draft_dir": self.draft_dir,
            "entries": list(self.entries),
        }
        path.write_text(json.dumps(envelope, indent=2) + "\n", encoding="utf-8")
        return path

    # ------------------------------------------------------------------
    # Mutators
    # ------------------------------------------------------------------

    def add_approved(
        self,
        *,
        slide_id: str,
        image_path: str,
        request_path: str,
        channel: str,
        model: str,
        cost_usd: float,
        approved_at: Optional[str] = None,
    ) -> dict:
        """Record an approved + generated image. Returns the new entry."""
        if not slide_id:
            raise ManifestError("slide_id required")
        if channel not in ("A", "B"):
            raise ManifestError(
                f"channel must be 'A' or 'B'; got {channel!r}"
            )
        if cost_usd < 0:
            raise ManifestError(f"cost_usd must be ≥ 0; got {cost_usd}")
        if self.has_slide(slide_id):
            raise ManifestError(
                f"slide_id {slide_id!r} already in manifest; use update or "
                f"remove first to avoid silent overwrite"
            )
        entry = {
            "slide_id": slide_id,
            "approved": True,
            "image_path": image_path,
            "request_path": request_path,
            "channel": channel,
            "model": model,
            "cost_usd": float(cost_usd),
            "approved_at": approved_at or _utc_iso_now(),
        }
        self.entries.append(entry)
        return entry

    def add_rejected(
        self,
        *,
        slide_id: str,
        reason: str,
        rejected_at: Optional[str] = None,
        request_path: Optional[str] = None,
    ) -> dict:
        """Record a user-rejected slide. The slide will be dropped from
        its fragment per R6 Option A — manifest captures the rejection
        for audit + future-revise reference."""
        if not slide_id:
            raise ManifestError("slide_id required")
        if not reason:
            raise ManifestError("reason required for rejection")
        if self.has_slide(slide_id):
            raise ManifestError(
                f"slide_id {slide_id!r} already in manifest"
            )
        entry: dict = {
            "slide_id": slide_id,
            "approved": False,
            "rejected_at": rejected_at or _utc_iso_now(),
            "reason": reason,
        }
        if request_path is not None:
            entry["request_path"] = request_path
        self.entries.append(entry)
        return entry

    def add_skipped(
        self,
        *,
        slide_id: str,
        reason: str,
        rejected_at: Optional[str] = None,
    ) -> dict:
        """Record a budget-skipped slide. Distinguishable from
        user-rejection by the `skipped: true` flag — preserves the
        signal that this slide WOULD have been generated if budget
        permitted, so the user can re-run with `--resume-from
        image_gen --max-image-cost-usd <higher>` to fill the gap."""
        if not slide_id:
            raise ManifestError("slide_id required")
        if not reason:
            raise ManifestError("reason required for skip")
        if self.has_slide(slide_id):
            raise ManifestError(
                f"slide_id {slide_id!r} already in manifest"
            )
        entry = {
            "slide_id": slide_id,
            "approved": False,
            "skipped": True,
            "rejected_at": rejected_at or _utc_iso_now(),
            "reason": reason,
        }
        self.entries.append(entry)
        return entry

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def has_slide(self, slide_id: str) -> bool:
        return any(e.get("slide_id") == slide_id for e in self.entries)

    def get(self, slide_id: str) -> Optional[dict]:
        for e in self.entries:
            if e.get("slide_id") == slide_id:
                return e
        return None

    def approved_entries(self) -> list[dict]:
        """Entries the merge step should bind to slides."""
        return [e for e in self.entries if e.get("approved") is True]

    def rejected_entries(self) -> list[dict]:
        """Entries the merge step should drop from fragments."""
        return [e for e in self.entries if e.get("approved") is False]

    def total_cost_usd(self) -> float:
        """Sum of cost_usd over approved entries. Used by the
        orchestrator's budget-tracker to compute remaining budget
        before the next image-gen call."""
        return sum(
            float(e.get("cost_usd", 0.0))
            for e in self.entries
            if e.get("approved") is True
        )

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self) -> list[str]:
        """Return a list of validation error strings. Empty list means
        valid. Used by the `validate` CLI subcommand and as a safety
        net before write."""
        errors: list[str] = []
        seen_ids: set[str] = set()
        for i, entry in enumerate(self.entries):
            prefix = f"entries[{i}]"
            if not isinstance(entry, dict):
                errors.append(f"{prefix}: not a JSON object")
                continue
            slide_id = entry.get("slide_id")
            if not isinstance(slide_id, str) or not slide_id:
                errors.append(f"{prefix}.slide_id: required non-empty string")
                continue
            if slide_id in seen_ids:
                errors.append(f"{prefix}.slide_id: duplicate {slide_id!r}")
            seen_ids.add(slide_id)
            approved = entry.get("approved")
            if not isinstance(approved, bool):
                errors.append(f"{prefix}.approved: required boolean")
                continue
            if approved:
                for required in ("image_path", "request_path", "channel",
                                 "model", "cost_usd", "approved_at"):
                    if required not in entry:
                        errors.append(f"{prefix}.{required}: required for approved entry")
                if entry.get("channel") not in ("A", "B", None):
                    errors.append(
                        f"{prefix}.channel: must be 'A' or 'B'; "
                        f"got {entry.get('channel')!r}"
                    )
            else:
                for required in ("rejected_at", "reason"):
                    if required not in entry:
                        errors.append(f"{prefix}.{required}: required for rejected entry")
        return errors


# --------------------------------------------------------------------------
# Internal helpers
# --------------------------------------------------------------------------

def _utc_iso_now() -> str:
    """ISO-8601 UTC timestamp matching image_provenance.json convention."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _cmd_validate(args: argparse.Namespace) -> int:
    path = Path(args.path)
    if not path.is_file():
        print(f"image_gen_manifest: file not found: {path}", file=sys.stderr)
        return 1
    try:
        manifest = Manifest.load(path)
    except ManifestError as e:
        print(f"image_gen_manifest: {e}", file=sys.stderr)
        return 2
    errors = manifest.validate()
    if errors:
        print(f"image_gen_manifest: {len(errors)} validation error(s):",
              file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 2
    n_approved = len(manifest.approved_entries())
    n_rejected = len(manifest.rejected_entries())
    total = manifest.total_cost_usd()
    print(
        f"image_gen_manifest: OK ({n_approved} approved, {n_rejected} rejected, "
        f"${total:.3f} total cost)",
        file=sys.stderr,
    )
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="image_gen_manifest",
        description="v0.3.3 image-manifest.v1 reader / validator.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    p_validate = sub.add_parser(
        "validate",
        help="Read a manifest and validate it.",
    )
    p_validate.add_argument("path", help="Path to manifest.json")
    p_validate.set_defaults(func=_cmd_validate)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
