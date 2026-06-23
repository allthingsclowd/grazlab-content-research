"""A FeedSource names where to crawl; repos own the actual lists."""

from grazlab_content_research.sources import FeedSource


def test_a_feed_source_defaults_to_rss_kind():
    s = FeedSource(name="CISA", url="https://cisa.gov/feed.xml")
    assert s.kind == "rss"


def test_a_feed_source_carries_its_desk_and_kind():
    s = FeedSource(
        name="2-Minute Papers", url="https://youtube.com/feeds/x", kind="youtube", desk="ai"
    )
    assert s.desk == "ai"
    assert s.kind == "youtube"
