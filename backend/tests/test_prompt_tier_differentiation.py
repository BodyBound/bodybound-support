"""Regression tests for build_blueprint_prompt tier differentiation.

Light is intentionally a STANDALONE prompt (no Blueprint Heavy+ framing,
no four-tier hierarchy, no DOTTED tier) — empirically required so the
model produces a visibly cleaner output than Medium/Heavy.

Medium and Heavy share the Blueprint Heavy+ base prompt with their own
detail blocks.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server import build_blueprint_prompt


def test_light_is_standalone_prompt():
    light = build_blueprint_prompt("black", "minimal")

    # Light uses the Feb-16-2026 photo-to-line-art tracing brief
    assert "TRACING" in light
    assert "SHADING AMOUNT: MINIMAL" in light
    assert "BLACK FILLS: NONE" in light

    # Light must NOT inherit any Blueprint Heavy+ framing — this is
    # the entire point of branching it out.
    assert "BLUEPRINT HEAVY+" not in light
    assert "DOTTED" not in light
    assert "TIER" not in light
    assert "PRIMARY" not in light
    assert "SECONDARY" not in light
    assert "TERTIARY" not in light
    assert "thermofax" not in light


def test_medium_uses_blueprint_heavy_plus_base():
    medium = build_blueprint_prompt("black", "moderate")
    assert "BLUEPRINT HEAVY+" in medium
    assert "MEDIUM" in medium
    assert "DOTTED guides at this level" in medium  # explicit "no dotted at medium"


def test_heavy_uses_blueprint_heavy_plus_base_with_dotted():
    heavy = build_blueprint_prompt("black", "detailed")
    assert "BLUEPRINT HEAVY+" in heavy
    assert "HEAVY" in heavy
    assert "DOTTED" in heavy
    assert "PRIMARY + SECONDARY + FULL TERTIARY + DOTTED" in heavy


def test_line_color_is_interpolated_into_light():
    light_black = build_blueprint_prompt("black", "minimal")
    light_purple = build_blueprint_prompt("purple/violet", "minimal")
    assert "black colored lines on pure white background" in light_black
    assert "purple/violet colored lines on pure white background" in light_purple


def test_tier_lengths_signal_clear_separation():
    """Light should be substantially shorter than Medium/Heavy — proxy
    for 'less framing, less hierarchy, less detail'."""
    light = build_blueprint_prompt("black", "minimal")
    medium = build_blueprint_prompt("black", "moderate")
    heavy = build_blueprint_prompt("black", "detailed")

    assert len(light) < len(medium)
    assert len(medium) < len(heavy)
    # Light is dramatically shorter — at least 3x shorter than Medium
    assert len(medium) > 3 * len(light)
