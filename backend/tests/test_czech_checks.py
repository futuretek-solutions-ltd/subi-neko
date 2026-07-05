from __future__ import annotations

from app.subs.czech_checks import (
    check_gender_agreement,
    check_readability,
    check_tv_against_pairs,
    check_tv_mixed_in_line,
    check_untranslated_english,
    check_vocative,
)


# ---------------------------------------------------------------------------
# Gender agreement
# ---------------------------------------------------------------------------

def test_gender_agreement_flags_masculine_form_for_female_speaker():
    findings = check_gender_agreement("Šel jsem domů.", "female")
    assert findings
    assert findings[0][0] == "gender_agreement"


def test_gender_agreement_flags_feminine_form_for_male_speaker():
    findings = check_gender_agreement("Viděla jsem to.", "male")
    assert findings
    assert findings[0][0] == "gender_agreement"


def test_gender_agreement_accepts_correct_feminine_form():
    assert check_gender_agreement("Šla jsem domů.", "female") == []


def test_gender_agreement_accepts_correct_masculine_form():
    assert check_gender_agreement("Byl bych rád.", "male") == []


def test_gender_agreement_handles_inverted_order():
    findings = check_gender_agreement("Já jsem šel domů.", "female")
    assert findings


def test_gender_agreement_ignores_unknown_gender():
    assert check_gender_agreement("Šel jsem domů.", None) == []
    assert check_gender_agreement("Šel jsem domů.", "non_binary") == []


def test_gender_agreement_noun_before_aux_not_flagged_when_correct_form_present():
    # "stůl" ends in -l but the real participle "koupila" agrees — precision
    # heuristic: any correctly-gendered candidate suppresses the flag.
    assert check_gender_agreement("Ten stůl jsem koupila včera.", "female") == []


def test_gender_agreement_ignores_ass_markup():
    findings = check_gender_agreement(r"{\i1}Šel jsem{\i0} domů.", "female")
    assert findings


# ---------------------------------------------------------------------------
# T–V mixing within one line
# ---------------------------------------------------------------------------

def test_tv_mixed_in_line_flags_mixture():
    findings = check_tv_mixed_in_line("Můžeš mi říct, co vás sem přivádí, ty jeden?")
    assert findings
    assert findings[0][0] == "tv_address_mixed"


def test_tv_consistent_informal_not_flagged():
    assert check_tv_mixed_in_line("Můžeš mi říct, co tě sem přivádí?") == []


def test_tv_consistent_formal_not_flagged():
    assert check_tv_mixed_in_line("Můžete mi říct, co vás sem přivádí?") == []


def test_tv_against_pairs_flags_formal_from_uniformly_informal_speaker():
    findings = check_tv_against_pairs("Co vás sem přivádí?", {"tykani"})
    assert findings
    assert findings[0][0] == "tv_address_mismatch"


def test_tv_against_pairs_flags_informal_from_uniformly_formal_speaker():
    findings = check_tv_against_pairs("Co tě sem přivádí?", {"vykani"})
    assert findings


def test_tv_against_pairs_silent_for_mixed_relationships():
    assert check_tv_against_pairs("Co vás sem přivádí?", {"tykani", "vykani"}) == []
    assert check_tv_against_pairs("Co vás sem přivádí?", {"mixed"}) == []


def test_tv_against_pairs_silent_when_matching():
    assert check_tv_against_pairs("Co tě sem přivádí?", {"tykani"}) == []


# ---------------------------------------------------------------------------
# Vocative
# ---------------------------------------------------------------------------

def test_vocative_flags_nominative_in_direct_address():
    findings = check_vocative("Ahoj, Tomáš!", {"Tomáš": "Tomáši"})
    assert findings
    assert findings[0][0] == "vocative_missing"


def test_vocative_flags_line_initial_address():
    findings = check_vocative("Tomáš, pojď sem.", {"Tomáš": "Tomáši"})
    assert findings


def test_vocative_ignores_name_in_normal_position():
    assert check_vocative("Tomáš šel domů.", {"Tomáš": "Tomáši"}) == []


def test_vocative_accepts_correct_vocative_form():
    assert check_vocative("Ahoj, Tomáši!", {"Tomáš": "Tomáši"}) == []


def test_vocative_skips_names_without_distinct_form():
    assert check_vocative("Ahoj, Aria!", {"Aria": "Aria"}) == []


# ---------------------------------------------------------------------------
# Readability
# ---------------------------------------------------------------------------

def test_readability_flags_high_cps():
    text = "Tohle je opravdu velmi dlouhý titulek, který nelze přečíst."
    findings = check_readability(text, duration_ms=1000, cps_limit=20.0, max_row_chars=42)
    assert any(f[0] == "high_cps" for f in findings)


def test_readability_accepts_normal_line():
    findings = check_readability("Ahoj.", duration_ms=1500, cps_limit=20.0, max_row_chars=42)
    assert findings == []


def test_readability_flags_long_row():
    text = "x" * 60
    findings = check_readability(text, duration_ms=60000, cps_limit=20.0, max_row_chars=42)
    assert any(f[0] == "long_row" for f in findings)


def test_readability_row_split_on_ass_newline():
    text = ("x" * 30) + r"\N" + ("y" * 30)
    findings = check_readability(text, duration_ms=60000, cps_limit=20.0, max_row_chars=42)
    assert not any(f[0] == "long_row" for f in findings)


def test_readability_flags_three_rows():
    text = r"a\Nb\Nc"
    findings = check_readability(text, duration_ms=60000, cps_limit=20.0, max_row_chars=42)
    assert any(f[0] == "too_many_rows" for f in findings)


def test_readability_zero_duration_skips_cps():
    findings = check_readability("Dlouhý text " * 20, duration_ms=0, cps_limit=20.0, max_row_chars=1000)
    assert not any(f[0] == "high_cps" for f in findings)


# ---------------------------------------------------------------------------
# Untranslated English
# ---------------------------------------------------------------------------

def test_untranslated_english_flags_english_output():
    findings = check_untranslated_english(
        "But there is something about this place.",
        "But there is something about this place.",
    )
    assert findings
    assert findings[0][0] == "untranslated_english"


def test_untranslated_english_accepts_czech_output():
    assert check_untranslated_english(
        "But there is something about this place.",
        "Ale na tomhle místě něco je.",
    ) == []


def test_untranslated_english_ignores_honorific_compounds():
    # "Ako-neechan"/"Riko-neechan" are preserved by design — a translated
    # line dominated by them must not flag as untranslated.
    assert check_untranslated_english(
        "Give me a break Ako-neechan, Riko-neechan...",
        "Dejte mi pokoj, Ako-neechan, Riko-neechan...",
    ) == []


def test_untranslated_english_ignores_shared_proper_names():
    # Names capitalized in both source and target are names, not English.
    assert check_untranslated_english(
        "Ako and Riko-senpai? Kiryuu-sensei?",
        "Ako a Riko-sempai? Kiryuu-sensei?",
    ) == []


def test_untranslated_english_ignores_glossary_terms():
    assert check_untranslated_english(
        "The Honey Boy and the Shy Boy share everything.",
        "Honey Boy a Shy Boy se dělí o všechno.",
        exclude_terms={"honey", "boy", "shy"},
    ) == []


def test_untranslated_english_still_flags_verbatim_lyric():
    findings = check_untranslated_english(
        "Please don't cease that twinkling",
        "Please don't cease that twinkling",
    )
    assert findings
    assert findings[0][0] == "untranslated_english"
