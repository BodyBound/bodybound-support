"""Calibration + correctness tests for validate_stencil_reference_match.

Validates two things:
  1. Legit reference/stencil pairs PASS the validator (no false rejections).
  2. Unrelated input/output pairs FAIL the validator (catches wrong-reference outputs).

Thresholds live inside validate_stencil_reference_match() in server.py so any
threshold change is reflected here automatically.
"""
import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server import validate_stencil_reference_match  # noqa: E402


STATIC = Path("/app/backend/static")


def _b64(p: Path) -> str:
    return base64.b64encode(p.read_bytes()).decode("ascii")


def _check(name: str, ref: Path, stencil: Path, expect_match: bool):
    r = validate_stencil_reference_match(_b64(ref), _b64(stencil))
    status = "PASS" if r["is_match"] == expect_match else "FAIL"
    print(
        f"[{status}] {name}: is_match={r['is_match']} "
        f"edge_ncc={r['edge_ncc']} line_prec={r['line_precision']} "
        f"reason={r['reason']}"
    )
    return r["is_match"] == expect_match


def main():
    results = []

    # --- Legit pairs (matching subject) — MUST PASS ---
    legit_pairs = [
        ("portrait  → stencil_medium",       "portrait.jpg",  "stencil_medium.png"),
        ("portrait  → stencil_heavy",        "portrait.jpg",  "stencil_heavy.png"),
        ("portrait2 → stencil_medium_alt",   "portrait2.jpg", "stencil_medium_alt.png"),
        ("portrait2 → stencil_heavy_alt",    "portrait2.jpg", "stencil_heavy_alt.png"),
        ("portrait3 → stencil_light_skull",  "portrait3.jpg", "stencil_light_skull.png"),
        ("portrait3 → stencil_medium_skull", "portrait3.jpg", "stencil_medium_skull.png"),
        ("portrait3 → stencil_heavy_skull",  "portrait3.jpg", "stencil_heavy_skull.png"),
        ("portrait4 → stencil_light_lion",   "portrait4.jpg", "stencil_light_lion.png"),
        ("portrait4 → stencil_medium_lion",  "portrait4.jpg", "stencil_medium_lion.png"),
        ("portrait4 → stencil_heavy_lion",   "portrait4.jpg", "stencil_heavy_lion.png"),
    ]
    for name, ref, stencil in legit_pairs:
        results.append(_check(name, STATIC / ref, STATIC / stencil, expect_match=True))

    # --- Wrong-reference pairs (different subject) — MUST FAIL ---
    wrong_pairs = [
        ("portrait  → stencil_heavy_skull (mismatch)",   "portrait.jpg",  "stencil_heavy_skull.png"),
        ("portrait  → stencil_heavy_lion (mismatch)",    "portrait.jpg",  "stencil_heavy_lion.png"),
        ("portrait  → stencil_medium_alt (mismatch)",    "portrait.jpg",  "stencil_medium_alt.png"),
        ("portrait2 → stencil_medium (mismatch)",        "portrait2.jpg", "stencil_medium.png"),
        ("portrait2 → stencil_heavy_lion (mismatch)",    "portrait2.jpg", "stencil_heavy_lion.png"),
        ("portrait3 → stencil_heavy (mismatch)",         "portrait3.jpg", "stencil_heavy.png"),
        ("portrait3 → stencil_heavy_lion (mismatch)",    "portrait3.jpg", "stencil_heavy_lion.png"),
        ("portrait4 → stencil_heavy (mismatch)",         "portrait4.jpg", "stencil_heavy.png"),
        ("portrait4 → stencil_heavy_skull (mismatch)",   "portrait4.jpg", "stencil_heavy_skull.png"),
    ]
    for name, ref, stencil in wrong_pairs:
        results.append(_check(name, STATIC / ref, STATIC / stencil, expect_match=False))

    total = len(results)
    passed = sum(results)
    print(f"\n{passed}/{total} expectations met.")
    if passed != total:
        sys.exit(1)


if __name__ == "__main__":
    main()
