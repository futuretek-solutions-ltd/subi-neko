from __future__ import annotations

import pytest

from app.subs.episode_parsing import parse_episode_number


@pytest.mark.parametrize("filename,expected", [
    # Standard release naming
    ("[SubsPlease] Frieren - 12 (1080p) [ABCD1234].mkv", 12),
    ("[Erai-raws] Spy x Family - 05 [720p][Multiple Subtitle].mkv", 5),
    ("Show.Name.S01E07.1080p.WEB-DL.x264.mkv", 7),
    ("Show Name s02e13.mkv", 13),
    ("Show Name E03.mkv", 3),
    ("Show Name Ep. 24.mkv", 24),
    ("Show Name Episode 101.mkv", 101),
    ("Show Name #08.mkv", 8),
    ("Show_Name_-_09_(BD_1080p).mkv", 9),
    ("Frieren - Beyond Journey's End - 21 END.mkv", 21),
    # Trailing bare number
    ("Frieren 04.mkv", 4),
    # Noise resistance: resolution/codec tokens must not be read as episodes
    ("[Group] Show - 11 [1080p][x265][10bit].mkv", 11),
    ("Show - 02 [BDRip 1920x1080 HEVC FLAC].mkv", 2),
    ("Show - 03v2 [720p].mkv", 3),
])
def test_parses_episode_number(filename, expected):
    assert parse_episode_number(filename) == expected


@pytest.mark.parametrize("filename", [
    # No episode signal at all
    "Show Name.mkv",
    "Movie.Name.2021.1080p.BluRay.mkv",       # year, not an episode
    "Show Name - 2021.mkv",                    # year after dash
    # Fractional recap episodes — don't guess
    "Show Name - 12.5 [720p].mkv",
])
def test_returns_none_when_uncertain(filename):
    assert parse_episode_number(filename) is None


def test_prefers_explicit_episode_marker_over_trailing_number():
    # "S01E07" wins over any other number in the name.
    assert parse_episode_number("Show 2049 S01E07 1080p.mkv") == 7
