"""Deterministic crawl: RSS/Atom/YouTube parse + recency window + Serper, all offline."""

from datetime import UTC, datetime

import pytest

from grazlab_content_research import crawl
from grazlab_content_research.sources import FeedSource

NOW = datetime(2026, 6, 22, 12, 0, tzinfo=UTC)

RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item><title>Fresh RSS</title><link>https://e.com/1</link>
    <description>Body &lt;b&gt;one&lt;/b&gt;</description>
    <pubDate>Mon, 22 Jun 2026 10:00:00 GMT</pubDate></item>
  <item><title>Stale RSS</title><link>https://e.com/2</link>
    <pubDate>Mon, 01 Jan 2024 10:00:00 GMT</pubDate></item>
  <item><title>Undated RSS</title><link>https://e.com/3</link></item>
</channel></rss>"""

ATOM = """<feed xmlns="http://www.w3.org/2005/Atom">
  <entry><title>Atom One</title><link rel="alternate" href="https://e.com/a1"/>
    <summary>Atom body</summary><published>2026-06-22T09:00:00Z</published></entry>
</feed>"""

YT = """<feed xmlns="http://www.w3.org/2005/Atom" xmlns:media="http://search.yahoo.com/mrss/">
  <entry><title>Vid</title><link rel="alternate" href="https://youtube.com/watch?v=abc"/>
    <published>2026-06-22T08:00:00Z</published>
    <media:group><media:community><media:statistics views="12345"/></media:community></media:group>
  </entry>
</feed>"""


def test_parse_feed_reads_rss_items_into_candidates():
    items = crawl.parse_feed(RSS, source="Example", desk="ai")
    titles = {i.title for i in items}
    assert {"Fresh RSS", "Stale RSS", "Undated RSS"} <= titles
    fresh = next(i for i in items if i.title == "Fresh RSS")
    assert fresh.url == "https://e.com/1"
    assert "one" in fresh.summary  # HTML stripped
    assert fresh.desk == "ai"
    assert fresh.published == datetime(2026, 6, 22, 10, 0, tzinfo=UTC)


def test_parse_feed_reads_atom_entries():
    items = crawl.parse_feed(ATOM, source="Atom")
    assert items[0].title == "Atom One"
    assert items[0].url == "https://e.com/a1"


def test_parse_feed_extracts_youtube_view_count_into_extra():
    items = crawl.parse_feed(YT, source="2MP")
    assert items[0].extra["views"] == 12345


def test_parse_feed_returns_empty_on_garbage_xml():
    assert crawl.parse_feed("<not xml", source="x") == []


def test_harvest_drops_stale_items_keeps_fresh_and_undated():
    src = [FeedSource(name="Example", url="https://e.com/feed", kind="rss", desk="ai")]
    got = crawl.harvest(src, since_hours=24, fetch=lambda _u: RSS, now=NOW)
    titles = {c.title for c in got}
    assert "Fresh RSS" in titles
    assert "Undated RSS" in titles
    assert "Stale RSS" not in titles  # 2024 → older than 24h


def test_harvest_caps_items_per_feed():
    src = [FeedSource(name="Example", url="https://e.com/feed", kind="rss")]
    got = crawl.harvest(src, since_hours=24, max_per_feed=1, fetch=lambda _u: RSS, now=NOW)
    assert len(got) == 1


def test_harvest_skips_a_dead_feed_without_erroring():
    src = [
        FeedSource(name="Dead", url="https://dead/feed", kind="rss"),
        FeedSource(name="Live", url="https://live/feed", kind="rss"),
    ]
    got = crawl.harvest(src, fetch=lambda u: None if "dead" in u else RSS, now=NOW)
    assert got and all(c.source == "Live" for c in got)


def test_crawl_raises_loudly_when_the_whole_pool_is_empty():
    src = [FeedSource(name="Dead", url="https://dead/feed", kind="rss")]
    with pytest.raises(crawl.CrawlEmpty):
        crawl.crawl(src, fetch=lambda _u: None, now=NOW)


def test_crawl_resolves_serper_news_queries_into_candidates():
    src = [FeedSource(name="ransomware news", url="ransomware", kind="serper-news", desk="cyber")]

    def fake_post(url, json, headers):
        assert "serper" in url
        assert json["q"] == "ransomware"
        return {"news": [{"title": "Breach!", "link": "https://news.example/x", "snippet": "…"}]}

    got = crawl.crawl(src, post=fake_post, serper_api_key="k", now=NOW)
    assert got[0].title == "Breach!"
    assert got[0].url == "https://news.example/x"
    assert got[0].desk == "cyber"
