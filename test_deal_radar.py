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


def test_heat_recheck_includes_cheap_deals():  # price never filters a deal
    assert _hot_low_row_upgrades("Socks $5") == [{"range": "G7", "values": [[60]]},
                                                 {"range": "J7", "values": [["New"]]}]


def test_cheap_hot_deal_is_graded_not_low():
    assert d.triage(d.make_rule([]), "Socks $5", 5, 60, "") == "New"


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
    assert v == "⏳ WAIT" and alert and "15% above the lowest seen $100 at Target" in why


def test_every_watchlist_match_alerts_even_over_max_or_no_price():
    v, why, alert = _hgrade(85, match="lego (over max $80)")
    assert v.startswith("\U0001f525") and alert and "over your max $80" in why and "over your max" in alert[2]
    v, _, alert = d.grade("LEGO sale", None, 0, "lego ✓", [], HIST, "z")
    assert v == d.UNVERIFIED and alert and alert[0] == "watchlist: lego"


def test_history_ignores_the_deal_itself_and_no_max_without_history_is_unverified():
    assert _hgrade(118, did="a")[0] == "\U0001f7e2 ALL-TIME LOW"  # its own $100 row is ignored: only $120 left
    v, why, alert = d.grade("Fleece PJ $9", 9, 0, "fleece ✓" + d.NO_MAX, [], {}, "x")
    assert v == d.UNVERIFIED and alert and "no history yet" in why


def test_new_history_rows_logs_each_watch_deal_once():
    hist = {"lego": [{"price": 100.0, "date": "", "store": "", "id": "a"}]}
    lines = [[2, "a", "", "Src", "LEGO $90", "Target", "90", "", "https://x", "lego ✓"],
             [3, "c", "", "Src", "LEGO $95", "Walmart", "95", "", "https://y", "lego (over max $80)"],
             [4, "e", "", "Src", "[Expired] LEGO $50", "", "50", "", "https://z", "lego ✓"],
             [5, "f", "", "Src", "TV $500", "", "500", "", "https://w", ""]]
    rows = d.new_history_rows(lines, hist, "2026-11-14")
    assert [r[5] for r in rows] == ["c"] and rows[0][:4] == ["lego", "2026-11-14", 95.0, "Walmart"]
    assert d.match_keyword("nano puff ✓ (no max)") == "nano puff" and d.match_keyword("\U0001f4b8 Lower than") == ""


def test_categorize_by_title_then_feed():
    assert d.categorize("Apple AirPods Pro 3 $199") == "Apple"
    assert d.categorize("Carter's Girls Fleece Pajamas $8") == "Kids & Toys"
    assert d.categorize("Patagonia Women's Nano Puff Jacket $113") == "Clothing & Shoes"
    assert d.categorize("Hotel Grand White Down Comforter King $99.99") == "Furniture & Bedding"
    assert d.categorize("Sleep Number Mattresses: free delivery") == "Furniture & Bedding"  # plural matched
    assert d.categorize("TCL 98 inch QLED TV") == "Electronics"
    assert d.categorize("Mystery deal of the day", "Beauty") == "Beauty"  # feed category fallback
    assert d.categorize("Mystery deal of the day", "") == d.OTHER


def test_my_list_names():
    lists = {"fleece": "Sarah PJs"}
    assert d.my_list("fleece ✓", lists) == "Sarah PJs"
    assert d.my_list("nano puff (over max $150)", lists) == "Nano Puff"
    assert d.my_list("\U0001f4b8 Lower than your purchase: TV", lists) == "\U0001f4b8 My purchases"
    assert d.my_list("", lists) == ""


class _FakeWs:
    def __init__(self, rows, title="Deals"):
        self.rows, self.title, self.col_count, self.row_count = [list(r) for r in rows], title, 21, 50
        self.writes = []

    def col_values(self, c):
        col = [(r + [""] * 25)[c - 1] for r in self.rows]
        while col and not col[-1]:
            col.pop()
        return col

    def get_values(self, rng):
        import re as _re
        a, b = map(int, _re.findall(r"(\d+)", rng))
        return [list(r) for r in self.rows[a - 1:b]]

    def get_all_values(self):
        return [list(r) for r in self.rows]

    def add_cols(self, n):
        self.col_count += n

    def add_rows(self, n):
        self.row_count += n

    def update(self, values, range_name, value_input_option=None):
        import re as _re
        start = int(_re.search(r"(\d+)", range_name).group(1))
        self.writes.append(range_name)
        for k, v in enumerate(values):
            while len(self.rows) < start + k:
                self.rows.append([])
            self.rows[start - 1 + k] = list(v)


class _FakeSheet:
    def __init__(self, tabs):
        self.tabs = tabs

    def worksheet(self, name):
        return self.tabs[name]


def test_repair_shifted_rows_moves_back_dedupes_and_regrades():
    head = ["Deal ID", "Found At"] + [""] * 18
    ok = ["a1", "2026-11-14 19:51", "Src", "Old deal $5", "", "5", "1", "https://x/1", "", "Low"]
    shifted = ["", "b2", "2026-11-14 20:59", "Slickdeals Frontpage", "Patagonia Nano Puff Jacket $99", "", "99", "40",
               "https://x/2", "Scored", "\U0001f525 CANNOT MISS"]
    dup = ["", "b2", "2026-11-14 21:15", "Slickdeals Frontpage", "Patagonia Nano Puff Jacket $99", "", "99", "40",
           "https://x/2"]
    dup_old = ["", "a1", "2026-11-14 21:15", "Src", "Old deal $5", "", "5", "1", "https://x/1"]
    deals = _FakeWs([head, ok, shifted, dup, dup_old])
    sheet = _FakeSheet({"Deals": deals,
                        "Watchlist": _FakeWs([["k"], ["nano puff", "150", "", "", "", "Y", "Eva jackets"]]),
                        "Sources": _FakeWs([["Name"], ["Slickdeals Frontpage", "u", "", "Y", "", "", "Deals"]]),
                        "Price History": _FakeWs([d.HISTORY_HEADER, ["nano puff", "2026-11-01", "137", "REI", "", "", "", ""]])})
    assert d.repair_shifted_rows(sheet, deals) == 1
    row = deals.rows[2]
    assert row[:8] == ["b2", "2026-11-14 20:59", "Slickdeals Frontpage", "Patagonia Nano Puff Jacket $99", "", "99",
                       "40", "https://x/2"]
    assert row[8] == "nano puff ✓" and row[9] == "Scored" and row[10].startswith("\U0001f525")  # 99 vs low 137
    assert row[15] == d.SHIFT_NOTE and row[18] == "Clothing & Shoes" and row[19] == "Eva jackets"
    assert all(not any(r) for r in deals.rows[3:])  # duplicates cleared
    assert d.repair_shifted_rows(sheet, deals) == 0  # nothing left to fix


def test_write_rows_at_end_starts_in_column_a():
    ws = _FakeWs([["Deal ID", "Found At"], ["a", "t"], ["", "b"]])
    assert d.write_rows_at_end(ws, [["c", "t2"]]) == 4 and ws.writes == ["A4"]


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
