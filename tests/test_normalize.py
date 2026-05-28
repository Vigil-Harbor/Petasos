from __future__ import annotations

import unicodedata

from petasos.normalize import INVISIBLE_CHARS, _is_strippable, normalize


class TestNFKC:
    def test_fullwidth_a(self) -> None:
        result = normalize("ａ")  # fullwidth a
        assert "a" in result.normalized
        assert "nfkc_normalized" in result.transformations_applied

    def test_mathematical_bold(self) -> None:
        result = normalize("\U0001d400")  # mathematical bold A
        assert result.normalized == "A"

    def test_nfkc_only_does_not_set_confusables(self) -> None:
        result = normalize("ａ")  # fullwidth a — NFKC normalizes, no homoglyph
        assert result.normalized == "a"
        assert result.confusables_normalized is False


class TestInvisibleCharStripping:
    def test_zero_width_space(self) -> None:
        result = normalize("hel​lo")
        assert result.normalized == "hello"
        assert result.invisible_chars_stripped == 1

    def test_multiple_invisible(self) -> None:
        result = normalize("h​e‌l﻿l‍o")
        assert result.normalized == "hello"
        assert result.invisible_chars_stripped == 4

    def test_soft_hyphen(self) -> None:
        result = normalize("he­llo")
        assert result.normalized == "hello"
        assert result.invisible_chars_stripped == 1

    def test_bom(self) -> None:
        result = normalize("﻿hello")
        assert result.normalized == "hello"
        assert result.invisible_chars_stripped == 1

    def test_zwnj_and_zwj(self) -> None:
        result = normalize("a‌b‍c")
        assert result.normalized == "abc"
        assert result.invisible_chars_stripped == 2

    def test_line_separator_not_stripped(self) -> None:
        result = normalize("hello world")
        assert " " in result.normalized

    def test_paragraph_separator_not_stripped(self) -> None:
        result = normalize("hello world")
        assert " " in result.normalized


class TestRTLDetection:
    def test_rlo_detected(self) -> None:
        result = normalize("hello‮world")
        assert result.rtl_overrides_detected is True
        assert "rtl_override_detected" in result.transformations_applied

    def test_lro_detected(self) -> None:
        result = normalize("hello‭world")
        assert result.rtl_overrides_detected is True

    def test_bidi_isolates(self) -> None:
        for cp in ["⁦", "⁧", "⁨", "⁩"]:
            result = normalize(f"hello{cp}world")
            assert result.rtl_overrides_detected is True, f"Failed for {repr(cp)}"


class TestHomoglyph:
    def test_cyrillic_a(self) -> None:
        result = normalize("аbc")  # Cyrillic a
        assert result.normalized == "abc"
        assert result.confusables_normalized is True

    def test_greek_omicron(self) -> None:
        result = normalize("οk")  # Greek omicron
        assert result.normalized == "ok"
        assert result.confusables_normalized is True

    def test_all_17_chars(self) -> None:
        cyrillic = "аеорсуіѕ"
        greek = "αεορκιν"
        latin_ipa = "ıɡ"
        result = normalize(cyrillic + greek + latin_ipa)
        assert result.normalized == "aeopcyisaeopkivig"
        assert result.confusables_normalized is True

    def test_flag_set_on_substitution(self) -> None:
        result = normalize("а")
        assert result.confusables_normalized is True

    def test_flag_not_set_ascii(self) -> None:
        result = normalize("hello world")
        assert result.confusables_normalized is False


class TestEdgeCases:
    def test_empty_string(self) -> None:
        result = normalize("")
        assert result.original == ""
        assert result.normalized == ""
        assert result.transformations_applied == ()
        assert result.invisible_chars_stripped == 0
        assert result.confusables_normalized is False
        assert result.rtl_overrides_detected is False

    def test_ascii_passthrough(self) -> None:
        result = normalize("just plain ascii")
        assert result.original == "just plain ascii"
        assert result.normalized == "just plain ascii"
        assert result.transformations_applied == ()

    def test_combined_transforms(self) -> None:
        text = "h​eаlloａ"
        result = normalize(text)
        assert "​" not in result.normalized
        assert result.invisible_chars_stripped == 1
        assert result.confusables_normalized is True
        assert "invisible_chars_stripped" in result.transformations_applied

    def test_original_preserved(self) -> None:
        original = "​hello"
        result = normalize(original)
        assert result.original == original


class TestCategoryBasedStripping:
    """PET-43 / NORM-01: category-based invisible character stripping."""

    def test_tag_char_stripped_by_category(self) -> None:
        # Regression for PET-43: U+E0001 must be stripped via Cf category
        tag = chr(0xE0001)
        assert _is_strippable(tag)
        result = normalize(f"hello{tag}world")
        assert tag not in result.normalized
        assert result.invisible_chars_stripped >= 1

    def test_tag_block_range_stripped(self) -> None:
        # Regression for PET-43: all Cf chars in the Tags block are stripped
        cf_tags = [
            chr(cp)
            for cp in range(0xE0001, 0xE0080)
            if unicodedata.category(chr(cp)) == "Cf"
        ]
        assert len(cf_tags) > 0
        payload = "a" + "".join(cf_tags) + "b"
        result = normalize(payload)
        assert result.normalized == "ab"
        assert result.invisible_chars_stripped == len(cf_tags)

    def test_braille_blank_stripped(self) -> None:
        braille = chr(0x2800)
        assert _is_strippable(braille)
        result = normalize(f"hello{braille}world")
        assert braille not in result.normalized

    def test_mongolian_separator_stripped(self) -> None:
        mvs = chr(0x180E)
        assert _is_strippable(mvs)
        result = normalize(f"hello{mvs}world")
        assert mvs not in result.normalized

    def test_existing_invisible_chars_still_stripped(self) -> None:
        for ch in INVISIBLE_CHARS:
            assert _is_strippable(ch), (
                f"INVISIBLE_CHARS member U+{ord(ch):04X} not stripped"
            )

    def test_printable_ascii_not_stripped(self) -> None:
        for cp in range(0x20, 0x7F):
            ch = chr(cp)
            assert not _is_strippable(ch), (
                f"ASCII U+{cp:04X} ({ch!r}) should not be stripped"
            )

    def test_cjk_not_stripped(self) -> None:
        for ch in "一丁丂":
            assert unicodedata.category(ch) == "Lo"
            assert not _is_strippable(ch)

    def test_whitespace_preserved(self) -> None:
        assert not _is_strippable(" ")
        assert not _is_strippable("\t")
        assert not _is_strippable("\n")

    def test_normalize_idempotent_after_fix(self) -> None:
        tag = chr(0xE0001)
        payload = f"test{tag}ignore previous"
        once = normalize(payload).normalized
        twice = normalize(once).normalized
        assert once == twice
