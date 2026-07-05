from __future__ import annotations

import xml.etree.ElementTree as ET

from app.metadata.anidb import AniDBProvider

_SAMPLE_XML = """
<anime id="123">
  <type>TV Series</type>
  <episodecount>2</episodecount>
  <startdate>2023-09-29</startdate>
  <titles>
    <title xml:lang="x-jat" type="main">Sousou no Frieren</title>
  </titles>
  <episodes>
    <episode id="1001">
      <epno type="1">1</epno>
      <airdate>2023-09-29</airdate>
      <title xml:lang="en">The Journey's End</title>
      <title xml:lang="ja">旅の終わり</title>
    </episode>
    <episode id="1002">
      <epno type="1">2</epno>
      <airdate>2023-10-06</airdate>
      <title xml:lang="en">It Didn't Have to Be Magic</title>
    </episode>
    <episode id="2001">
      <epno type="2">S1</epno>
      <title xml:lang="en">Special</title>
    </episode>
    <episode id="3001">
      <epno type="3">C1</epno>
      <title xml:lang="en">Opening</title>
    </episode>
  </episodes>
</anime>
"""


def test_parse_anime_xml_extracts_regular_episodes(tmp_path, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "config_root", tmp_path)

    provider = AniDBProvider()
    root = ET.fromstring(_SAMPLE_XML)
    result = provider._parse_anime_xml(root)

    episodes = result["episodes"]
    # Specials (type 2) and credits (type 3) are excluded.
    assert [e["number"] for e in episodes] == [1, 2]
    assert episodes[0]["title"] == "The Journey's End"
    assert episodes[0]["title_native"] == "旅の終わり"
    assert episodes[0]["air_date"] == "2023-09-29"
    assert episodes[1]["title"] == "It Didn't Have to Be Magic"
    assert episodes[1]["title_native"] is None
