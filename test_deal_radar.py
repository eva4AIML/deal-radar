"""Checks for deal_radar.py. Run: python -m pytest test_deal_radar.py   (or: python test_deal_radar.py)"""
import time

import deal_radar as d


def test_parse_price_reads_full_number():
    assert d.parse_price("Dell laptop $3461 shipped") == 3461
    assert d.parse_price("TV $1,299.99") == 1299.99
    assert d.parse_price("Mac $12345") == 12345
    assert d.parse_price("Cable $9.99") == 9.99
    assert d.parse_price("Gift card $15") == 15
    assert d.parse_price("no price here") is None


def _hot_low_row_upgrades(title):
    """A Deals row logged as Low earlier; its feed now shows heat 60 (min heat 40). Returns the upgrades."""
    link = "https://example.com/deal"
    entry = {"id": "x1", "link": link, "title": title, "summary": "Thumb Score: +60",
             "published_parsed": time.gmtime()}
    known = {d.same_deal_key(link): [7, "Low", ""]}
    upgrades = []
    d.entries_to_rows("Src", d.make_rule([]), d.feedparser.FeedParserDict(entries=[entry]), [], set(), known,
                      "now", upgrades=upgrades)
    return upgrades


def test_heat_recheck_requeues_hot_deal():
    assert _hot_low_row_upgrades("Headphones $49") == [{"range": "G7", "values": [[60]]},
                                                       {"range": "J7", "values": [["New"]]}]


def test_heat_recheck_skips_deals_under_skip_under():
    assert _hot_low_row_upgrades(f"Socks ${d.SKIP_UNDER - 1}") == []


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("all tests passed")
