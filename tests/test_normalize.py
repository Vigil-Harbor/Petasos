from __future__ import annotations

from petasos.normalize import normalize


class TestNFKC:
    def test_fullwidth_a(self) -> None:
        result = normalize("ａ")  # fullwidth a
        assert "a" in result.normalized
        assert "nfkc_normalized" in result.transformations_applied

    def test_mathematical_bold(self) -> None:
        result = normalize("\U0001d400")  # mathematical bold A
        assert result.normalized == "A"


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
