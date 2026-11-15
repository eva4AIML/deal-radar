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


PURCHASES = [{"item": "Sony XM5", "store": "Best Buy", "paid": 349.0, "words": ["sony", "xm5"],
              "claim_by": "Jan 15, 2027"}]


def _grade(title, price=None, heat=None, match=""):
    return d.grade(title, price, heat, match, PURCHASES)


def test_rule1_price_drop_on_purchase_alerts_claim():
    verdict, why, alert = _grade("Sony XM5 headphones $299", 299)
    assert verdict.startswith("✅") and why.startswith("auto price-adjust")
    assert "Claim $50.00 back at Best Buy by Jan 15, 2027" in alert[2]


def test_rule2_watchlist_match_is_must_buy():
    verdict, _, alert = _grade("LEGO set $40", 40, match="lego ✓")
    assert verdict == "✅ MUST BUY" and alert
    assert _grade("LEGO set $90", 90, match="lego (over max $50)")[0] == d.UNVERIFIED


HIST = {"lego": [{"price": 100.0, "date": "2026-11-01", "store": "Target", "id": "a"},
                 {"price": 120.0, "date": "2026-10-01", "store": "Amazon", "id": "b"}]}


def _hgrade(price, match="lego ✓", did="new"):
    return d.grade(f"LEGO set ${price}", price, 5, match, [], HIST, did)


def test_history_tiers_vs_lowest_seen():
    assert _hgrade(85)[0].startswith("\U0001f525") and _hgrade(85)[2]       # 15% under the low
    assert _hgrade(99)[0] == "\U0001f7e2 ALL-TIME LOW" and _hgrade(99)[2]   # new low
    assert _hgrade(102)[0] == "\U0001f7e2 ALL-TIME LOW"                     # within 2%
    assert _hgrade(104)[0] == "✅ MUST BUY" and _hgrade(104)[2]             # within 5%
    v, why, alert = _hgrade(115)
    assert v == "⏳ WAIT" and alert is None and "15% above the lowest seen $100 at Target" in why


def test_history_over_max_is_graded_but_never_alerts():
    v, why, alert = _hgrade(85, match="lego (over max $80)")
    assert v.startswith("\U0001f525") and alert is None and "over your max $80" in why


def test_history_ignores_the_deal_itself_and_no_max_without_history_is_unverified():
    assert _hgrade(118, did="a")[0] == "\U0001f7e2 ALL-TIME LOW"  # its own $100 row is ignored: only $120 left
    v, why, alert = d.grade("Fleece PJ $9", 9, 0, "fleece ✓" + d.NO_MAX, [], {}, "x")
    assert v == d.UNVERIFIED and alert is None and "no history yet" in why


def test_new_history_rows_logs_each_watch_deal_once():
    hist = {"lego": [{"price": 100.0, "date": "", "store": "", "id": "a"}]}
    lines = [[2, "a", "", "Src", "LEGO $90", "Target", "90", "", "https://x", "lego ✓"],
             [3, "c", "", "Src", "LEGO $95", "Walmart", "95", "", "https://y", "lego (over max $80)"],
             [4, "e", "", "Src", "[Expired] LEGO $50", "", "50", "", "https://z", "lego ✓"],
             [5, "f", "", "Src", "TV $500", "", "500", "", "https://w", ""]]
    rows = d.new_history_rows(lines, hist, "2026-11-14")
    assert [r[5] for r in rows] == ["c"] and rows[0][:4] == ["lego", "2026-11-14", 95.0, "Walmart"]
    assert d.match_keyword("nano puff ✓ (no max)") == "nano puff" and d.match_keyword("\U0001f4b8 Lower than") == ""


def test_rule3_heat_tiers():
    v, _, alert = _grade("TV $500", 500, d.HOT_HEAT)
    assert v.startswith("\U0001f525") and alert is None  # 🔥 in the sheet, but no alert below ALERT_HEAT
    v, _, alert = _grade("TV $500", 500, d.ALERT_HEAT - 1)
    assert v.startswith("\U0001f525") and alert is None
    v, _, alert = _grade("TV $500", 500, d.ALERT_HEAT)
    assert v.startswith("\U0001f525") and alert
    v, _, alert = _grade("TV $500", 500, d.GOOD_HEAT)
    assert v == "\U0001f44d GOOD" and alert is None


def test_rule4_price_mistake_needs_heat():
    v, _, alert = _grade("Price mistake: Dyson $99", 99, d.GLITCH_MIN_HEAT)
    assert v.startswith("\U0001f525") and "cancelled" in alert[2]
    assert _grade("Price mistake: Dyson $99", 99, d.GLITCH_MIN_HEAT - 1)[0] == d.UNVERIFIED


def test_rule5_expired_is_bad_and_never_alerts():
    for t in ("[Expired] TV $500", "Switch OOS", "Sold out - PS5"):
        assert _grade(t, 500, 300, "tv ✓")[0] == "\U0001f44e BAD"
        assert _grade(t, 500, 300)[2] is None
    assert _grade("Red Dead Redemption $20", 20)[0] == d.UNVERIFIED


def test_rule6_everything_else_unverified_never_all_time_low():
    assert _grade("Socks $20", 20, 10) == (d.UNVERIFIED, "auto", None)


def _line(row, title, heat, found="2026-11-14 10:00"):
    return [row, "id", found, "Src", title, "", "100", heat, "https://x", ""]


def test_auto_grade_keeps_manual_verdicts_and_never_realerts():
    now = d.datetime(2026, 11, 14, 12, 0)
    lines = [_line(2, "Hot TV", 300), _line(3, "Hot TV", 300), _line(4, "Hot TV", 300), _line(5, "Hot TV", 10),
             _line(6, "Hot TV", 300, found="2026-11-01 10:00")]
    verdicts = ["Verdict", "", "⏳ WAIT", "", d.UNVERIFIED, ""]
    whys = ["Why", "", "manual", "", "auto", ""]
    alerted = ["Alerted", "", "", "2026-11-14 11:00", "", ""]
    updates, alerts = d.auto_grade(lines, verdicts, whys, alerted, [], now)
    graded = {u["range"] for u in updates if u["range"].startswith("J")}
    assert graded == {"J2:K2", "J4:K4", "J5:K5", "J6:K6"}  # row 3 is manual: untouched; row 5 auto ❓ re-graded
    assert [a["row"] for a in alerts] == [2]  # 4 already alerted, 6 too old to alert


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("all tests passed")
