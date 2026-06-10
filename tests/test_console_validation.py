"""Tests for petasos.console._validation — session_id boundary sanitization (PET-85).

The console scan endpoints (standalone /api/scan and Hermes plugin /scan)
share sanitize_session_id(): degenerate ids — oversize, empty, the invisible
character classes — are rejected with field-level 422s, and printable
homoglyph/compatibility variants collapse to one canonical FrequencyTracker
key and one ALRT-02 alert-dedup pair. The scan response echoes the canonical
id (D13), so canonicalization is observable at the API layer.

Every test that takes the params-based ``client`` fixture runs once per route
flavor, so each rejection-class test IS the route-parity test (same payload →
same status → same detail[0].field on both routes).
"""

import unicodedata
from collections.abc import Iterator

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from petasos.config import PetasosConfig  # noqa: E402
from petasos.console._validation import SessionIdError, sanitize_session_id  # noqa: E402
from petasos.pipeline import Pipeline  # noqa: E402
from petasos.scanners.minimal import MinimalScanner  # noqa: E402

_SCAN_TEXT = "hello world this is a test"


def _make_pipeline() -> Pipeline:
    return Pipeline(
        scanners=[MinimalScanner()],
        config=PetasosConfig(fail_mode="degraded"),
    )


@pytest.fixture(params=["standalone", "plugin"])
def client(request: pytest.FixtureRequest) -> Iterator[tuple[TestClient, str]]:
    """Yield (test_client, scan_path) for each console route flavor.

    Carries its own copy of the plugin-handler reset (pattern from
    tests/test_plugin_api_sse.py — fixtures are not importable across
    modules).
    """
    import petasos.console.hermes.plugin_api as plugin_mod

    plugin_mod._handlers = None
    if request.param == "standalone":
        from petasos.console.server import build_app

        yield TestClient(build_app(_make_pipeline())), "/api/scan"
    else:
        from petasos.console.hermes.plugin_api import init_handlers, router

        init_handlers(_make_pipeline())
        app = FastAPI()
        app.include_router(router)
        yield TestClient(app), "/scan"
    plugin_mod._handlers = None


# ── Null / type / emptiness / size ──────────────────────────────────────────


def test_null_session_id_passes(client: tuple[TestClient, str]) -> None:
    assert sanitize_session_id(None) is None
    tc, path = client
    resp = tc.post(path, json={"text": _SCAN_TEXT})
    assert resp.status_code == 200
    assert resp.json()["session_id"] is None


@pytest.mark.parametrize("bad", [123, []])
def test_non_string_rejected(client: tuple[TestClient, str], bad: object) -> None:
    with pytest.raises(SessionIdError, match="Must be a string or null"):
        sanitize_session_id(bad)
    tc, path = client
    resp = tc.post(path, json={"text": _SCAN_TEXT, "session_id": bad})
    assert resp.status_code == 422
    assert resp.json()["detail"][0]["field"] == "session_id"


def test_empty_string_rejected(client: tuple[TestClient, str]) -> None:
    with pytest.raises(SessionIdError, match="Must be non-empty"):
        sanitize_session_id("")
    tc, path = client
    resp = tc.post(path, json={"text": _SCAN_TEXT, "session_id": ""})
    assert resp.status_code == 422
    assert resp.json()["detail"][0]["field"] == "session_id"


def test_whitespace_only_rejected(client: tuple[TestClient, str]) -> None:
    with pytest.raises(SessionIdError, match="Must be non-empty"):
        sanitize_session_id("   ")
    tc, path = client
    resp = tc.post(path, json={"text": _SCAN_TEXT, "session_id": "   "})
    assert resp.status_code == 422
    assert resp.json()["detail"][0]["field"] == "session_id"


def test_oversize_rejected(client: tuple[TestClient, str]) -> None:
    with pytest.raises(SessionIdError, match="Exceeds 128 character limit"):
        sanitize_session_id("a" * 129)
    assert sanitize_session_id("a" * 128) == "a" * 128
    tc, path = client
    resp = tc.post(path, json={"text": _SCAN_TEXT, "session_id": "a" * 129})
    assert resp.status_code == 422
    assert resp.json()["detail"][0]["field"] == "session_id"
    resp = tc.post(path, json={"text": _SCAN_TEXT, "session_id": "a" * 128})
    assert resp.status_code == 200


# ── Control / invisible character classes ───────────────────────────────────


@pytest.mark.parametrize("bad", ["abc\ndef", "abc\x00def"])
def test_control_chars_rejected(client: tuple[TestClient, str], bad: str) -> None:
    with pytest.raises(SessionIdError, match="non-printable or invisible"):
        sanitize_session_id(bad)
    tc, path = client
    resp = tc.post(path, json={"text": _SCAN_TEXT, "session_id": bad})
    assert resp.status_code == 422
    assert resp.json()["detail"][0]["field"] == "session_id"


def test_trailing_newline_trimmed(client: tuple[TestClient, str]) -> None:
    # Regression for PET-85: outer whitespace (incl. C0 whitespace controls) is
    # trimmed as copy-paste forgiveness (D2); only interior controls reject.
    assert sanitize_session_id("session\n") == "session"
    tc, path = client
    resp = tc.post(path, json={"text": _SCAN_TEXT, "session_id": "session\n"})
    assert resp.status_code == 200
    assert resp.json()["session_id"] == "session"


@pytest.mark.parametrize("bad", ["sess​ion", "‮session"])
def test_zero_width_rejected(client: tuple[TestClient, str], bad: str) -> None:
    with pytest.raises(SessionIdError, match="non-printable or invisible"):
        sanitize_session_id(bad)
    tc, path = client
    resp = tc.post(path, json={"text": _SCAN_TEXT, "session_id": bad})
    assert resp.status_code == 422
    assert resp.json()["detail"][0]["field"] == "session_id"


_INVISIBLE_SAMPLES = [
    "⠀",  # BRAILLE PATTERN BLANK (So, via _is_strippable)
    "ㅤ",  # HANGUL FILLER
    "ﾠ",  # HALFWIDTH HANGUL FILLER
    "ᅟ",  # HANGUL CHOSEONG FILLER
    "ᅠ",  # HANGUL JUNGSEONG FILLER
    "͏",  # COMBINING GRAPHEME JOINER
    "᠏",  # MONGOLIAN FREE VARIATION SELECTOR FOUR (round-2 addition)
    "឴",  # KHMER VOWEL INHERENT AQ (round-2 addition)
    "឵",  # KHMER VOWEL INHERENT AA (round-2 addition)
    "️",  # VARIATION SELECTOR-16
    "\U00016fe4",  # KHITAN SMALL SCRIPT FILLER (round-3 addition, non-DI)
    "\U0001bc9d",  # DUPLOYAN THICK LETTER SELECTOR (round-3 addition, non-DI)
]


@pytest.mark.parametrize(
    "ch", _INVISIBLE_SAMPLES, ids=[f"U+{ord(c):04X}" for c in _INVISIBLE_SAMPLES]
)
def test_invisible_printable_rejected(client: tuple[TestClient, str], ch: str) -> None:
    bad = f"sess{ch}ion"
    with pytest.raises(SessionIdError, match="non-printable or invisible"):
        sanitize_session_id(bad)
    tc, path = client
    resp = tc.post(path, json={"text": _SCAN_TEXT, "session_id": bad})
    assert resp.status_code == 422
    assert resp.json()["detail"][0]["field"] == "session_id"


# Default_Ignorable_Code_Point ranges transcribed directly from Unicode 14.0.0
# DerivedCoreProperties.txt — deliberately NOT derived from the production
# _INVISIBLE_PRINTABLE set, so this sweep fails if that set ever omits an
# assigned-non-Cf class member (the round-1 FVS4/Khmer failure mode).
_DEFAULT_IGNORABLE_RANGES: list[tuple[int, int]] = [
    (0x00AD, 0x00AD),  # SOFT HYPHEN (Cf)
    (0x034F, 0x034F),  # COMBINING GRAPHEME JOINER (Mn)
    (0x061C, 0x061C),  # ARABIC LETTER MARK (Cf)
    (0x115F, 0x1160),  # HANGUL FILLERS (Lo)
    (0x17B4, 0x17B5),  # KHMER VOWELS INHERENT (Mn)
    (0x180B, 0x180D),  # MONGOLIAN FVS1-3 (Mn)
    (0x180E, 0x180E),  # MONGOLIAN VOWEL SEPARATOR (Cf)
    (0x180F, 0x180F),  # MONGOLIAN FVS4 (Mn)
    (0x200B, 0x200F),  # ZWSP..RLM (Cf)
    (0x202A, 0x202E),  # LRE..RLO (Cf)
    (0x2060, 0x2064),  # WORD JOINER..INVISIBLE PLUS (Cf)
    (0x2065, 0x2065),  # reserved (Cn)
    (0x206A, 0x206F),  # deprecated format controls (Cf)
    (0x3164, 0x3164),  # HANGUL FILLER (Lo)
    (0xFE00, 0xFE0F),  # VARIATION SELECTORS 1-16 (Mn)
    (0xFEFF, 0xFEFF),  # ZWNBSP/BOM (Cf)
    (0xFFA0, 0xFFA0),  # HALFWIDTH HANGUL FILLER (Lo)
    (0xFFF0, 0xFFF8),  # reserved (Cn)
    (0x1BCA0, 0x1BCA3),  # SHORTHAND FORMAT controls (Cf)
    (0x1D173, 0x1D17A),  # MUSICAL SYMBOL beams/slurs (Cf)
    (0xE0000, 0xE0000),  # reserved (Cn)
    (0xE0001, 0xE0001),  # LANGUAGE TAG (Cf)
    (0xE0002, 0xE001F),  # reserved (Cn)
    (0xE0020, 0xE007F),  # TAG characters (Cf)
    (0xE0080, 0xE00FF),  # reserved (Cn)
    (0xE0100, 0xE01EF),  # VARIATION SELECTORS 17-256 (Mn)
    (0xE01F0, 0xE0FFF),  # reserved (Cn)
]


def test_default_ignorable_rejected() -> None:
    """Sweep the assigned-non-Cf Default_Ignorable residue (group 1 guard)."""
    swept = 0
    for start, end in _DEFAULT_IGNORABLE_RANGES:
        for cp in range(start, end + 1):
            ch = chr(cp)
            if unicodedata.category(ch) in ("Cf", "Cn"):
                continue  # isprintable() rejects these; group 1 is the assigned-non-Cf residue
            swept += 1
            with pytest.raises(SessionIdError):
                sanitize_session_id(f"a{ch}b")
    # Unicode 14.0.0: CGJ(1) + Hangul fillers(2) + Khmer(2) + FVS1-4(4)
    # + HANGUL FILLER(1) + VS1-16(16) + HALFWIDTH FILLER(1) + VS17-256(240) = 267
    assert swept >= 267


@pytest.mark.parametrize(
    "bad",
    [
        "¨",  # Mn: NFKC(U+00A8) → <space>+U+0308, strip → bare leading U+0308
        "́abc",  # Mn: literal leading COMBINING ACUTE ACCENT
        "िabc",  # Mc: leading DEVANAGARI VOWEL SIGN I
        "⃝x",  # Me: leading COMBINING ENCLOSING CIRCLE
    ],
)
def test_leading_combining_mark_rejected(bad: str) -> None:
    with pytest.raises(SessionIdError, match="Begins with a combining mark"):
        sanitize_session_id(bad)


def test_spacing_accent_accepted_visibly() -> None:
    # D9 accepted residue: NFKC(U+00A8) = <space>+combining-diaeresis; the mark
    # anchors to the NFKC-introduced visible space, so "a¨b" is a visibly
    # distinct key — and stays distinct from "a´b" (no homoglyph collapse).
    out_diaeresis = sanitize_session_id("a¨b")
    out_acute = sanitize_session_id("a´b")
    assert out_diaeresis == "a ̈b"
    assert out_acute == "a ́b"
    assert out_diaeresis != out_acute


# ── Canonicalization (printable confusables collapse) ───────────────────────


def test_homoglyph_canonicalized() -> None:
    # Equal canonical ids ⟺ same FrequencyTracker key and ALRT-02 dedup pair.
    assert sanitize_session_id("bаd-actor") == sanitize_session_id("bad-actor") == "bad-actor"


def test_fullwidth_canonicalized() -> None:
    assert sanitize_session_id("ｈｅｒｍｅｓ－４２") == "hermes-42"


def test_response_echoes_canonical_session_id(client: tuple[TestClient, str]) -> None:
    # D13: canonicalization is silent (D3) but observable in the response.
    tc, path = client
    resp = tc.post(path, json={"text": _SCAN_TEXT, "session_id": "bаd-actor"})
    assert resp.status_code == 200
    assert resp.json()["session_id"] == "bad-actor"


def test_nfkc_expansion_capped() -> None:
    # 128 ﬃ ligatures pass the pre-NFKC cap, expand to 384 chars post-NFKC (D5).
    with pytest.raises(SessionIdError, match="Exceeds 128 character limit"):
        sanitize_session_id("ﬃ" * 128)


def test_plain_ascii_unchanged() -> None:
    sid = "hermes-session-42"
    out = sanitize_session_id(sid)
    assert out == sid
    assert out is not None
    assert len(out) == len(sid)


def test_visible_unicode_id_accepted() -> None:
    # Devanagari "namaste" — combining matras attach to visible bases, so the
    # leading-mark check must not fire (guards against over-rejection, D3).
    sid = "नमस्ते-42"
    assert sanitize_session_id(sid) == sid
