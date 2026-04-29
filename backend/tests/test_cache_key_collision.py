"""Regression test for the cache-key collision bug.

Bug: cache_key was computed from only the first 1000 base64 chars of the
image. JPEG/PNG headers + EXIF + quantization tables on phone photos are
similar enough that two unrelated photos could collide on the prefix,
returning user A's stencil when user B requested generation for an
unrelated reference photo. Launch-blocking.

Fix: cache_key now uses SHA-256 of the FULL base64 payload + style.

This test seeds two images that share a long common prefix but differ in
their tail bytes, and asserts they produce DIFFERENT cache keys.
"""
import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server import get_cache_key, hash_image


def _b64_with_prefix(prefix_bytes: bytes, tail_bytes: bytes) -> str:
    """Build a base64 string whose binary form is prefix + tail."""
    return base64.b64encode(prefix_bytes + tail_bytes).decode()


def test_two_images_with_shared_prefix_get_distinct_cache_keys():
    # 1500 bytes of shared "header" + a different tail per image.
    # When base64-encoded, the first ~2000 chars are identical.
    shared = (b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00' * 80)[:1500]

    img_a_b64 = _b64_with_prefix(shared, b'A' * 5000)
    img_b_b64 = _b64_with_prefix(shared, b'B' * 5000)

    # Sanity: their first 1000 chars are identical (the OLD bug surface)
    assert img_a_b64[:1000] == img_b_b64[:1000], 'test setup failed: first 1000 chars must match'
    # But their full content differs, so the new hash MUST treat them as distinct
    assert hash_image(img_a_b64) != hash_image(img_b_b64)
    # And cache keys MUST differ across the same style
    assert get_cache_key(img_a_b64, 'medium') != get_cache_key(img_b_b64, 'medium')


def test_same_image_same_style_produces_identical_cache_key():
    img = base64.b64encode(b'reference_photo_bytes_xyz_unique' * 100).decode()
    assert get_cache_key(img, 'light') == get_cache_key(img, 'light')


def test_same_image_different_style_produces_distinct_cache_keys():
    img = base64.b64encode(b'reference_photo_bytes_xyz_unique' * 100).decode()
    keys = {get_cache_key(img, s) for s in ('light', 'medium', 'heavy')}
    assert len(keys) == 3, f'expected 3 distinct cache keys, got {len(keys)}'


def test_data_url_prefix_is_stripped_for_hashing():
    """A client may send the same image with or without the
    `data:image/png;base64,` prefix. Both must hash identically so the
    cache treats them as the same image."""
    raw = base64.b64encode(b'identical_bytes_should_hash_the_same' * 100).decode()
    with_prefix = f'data:image/png;base64,{raw}'
    assert hash_image(raw) == hash_image(with_prefix)
    assert get_cache_key(raw, 'medium') == get_cache_key(with_prefix, 'medium')
