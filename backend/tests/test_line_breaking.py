from __future__ import annotations

from app.subs.line_breaking import rebalance_rows


def test_short_line_untouched():
    assert rebalance_rows("Ahoj, jak se máš?", 42) is None


def test_long_line_split_at_word_boundary():
    text = "Od dneška musíš vstávat dřív, když máš ranní doplňkové hodiny, ne?"
    fixed = rebalance_rows(text, 42)
    assert fixed is not None
    rows = fixed.split("\\N")
    assert len(rows) == 2
    assert all(len(r) <= 42 for r in rows)
    assert " ".join(rows) == text


def test_split_is_balanced():
    fixed = rebalance_rows("aaaa bbbb cccc dddd eeee ffff gggg hhhh", 25)
    assert fixed is not None
    r1, r2 = fixed.split("\\N")
    assert abs(len(r1) - len(r2)) <= 5


def test_existing_break_with_long_row_rebalanced():
    text = "Je to náš HONEY BOY, náš SHY BOY a o lásku\\Nse rozdělíme"
    fixed = rebalance_rows(text, 30)
    assert fixed is not None
    assert all(len(r) <= 30 for r in fixed.split("\\N"))


def test_existing_break_that_fits_untouched():
    assert rebalance_rows("první řádek\\Ndruhý řádek", 42) is None


def test_leading_override_block_preserved():
    text = "{\\an8\\i1}Od dneška musíš vstávat dřív, když máš ranní doplňkové hodiny, ne?"
    fixed = rebalance_rows(text, 42)
    assert fixed is not None
    assert fixed.startswith("{\\an8\\i1}")
    body = fixed[len("{\\an8\\i1}"):]
    assert all(len(r) <= 42 for r in body.split("\\N"))


def test_inline_override_skipped():
    text = "Tohle je jako pozdrav {\\fscx237}-{\\r} strčit mi jazyk do pusy, fakt hodně dlouhá věta"
    assert rebalance_rows(text, 42) is None


def test_soft_break_and_hard_space_skipped():
    assert rebalance_rows("dlouhá věta se soft breakem\\na pokračováním které přeteče limit řádku", 30) is None
    assert rebalance_rows("dlouhá\\hvěta s hard\\hspace znaky která přeteče limit řádku úplně", 30) is None


def test_unbreakable_word_returns_none():
    assert rebalance_rows("Supercalifragilisticexpialidocious slovo", 20) is None


def test_needs_three_rows_returns_none():
    # Can't fit in two rows of 20 → left for the reviewer (long_row flags it).
    text = "jedna dva tři čtyři pět šest sedm osm devět deset jedenáct dvanáct třináct"
    assert rebalance_rows(text, 20) is None


def test_empty_and_markup_only():
    assert rebalance_rows("", 42) is None
    assert rebalance_rows("{\\pos(1,2)}", 42) is None
