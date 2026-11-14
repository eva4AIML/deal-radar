"""
Deal Radar collector - pulls deal RSS feeds into the "Deal Radar 2026" Google Sheet.

Runs free on your own computer (no AI tokens). Claude's scheduled scans then grade the
rows this script marks Status = New and push-alert you on the best ones.

Nothing personal is stored in this file, so it is safe in a public repo.
  - GitHub Actions: set repo secrets SHEET_ID and GOOGLE_SERVICE_ACCOUNT_JSON.
  - Laptop: put service_account.json and sheet_id.txt (just the sheet ID) next to this file,
    or set the SHEET_ID environment variable. Both files are in .gitignore - never upload them.

Setup (once):
  1. pip install feedparser gspread google-auth tzdata
  2. Google Cloud console -> create a project -> enable "Google Sheets API" ->
     create a Service Account -> Keys -> Add key (JSON). Save it next to this file as
     service_account.json.
  3. Open the Deal Radar 2026 sheet -> Share -> paste the service account's email
     (ends in .iam.gserviceaccount.com) -> Editor.
  4. Test:  python deal_radar.py --once
  5. Schedule every 15 minutes:
       Windows: Task Scheduler -> Create Basic Task -> Daily -> Action "Start a program"
                Program: python   Arguments: C:\\path\\deal_radar.py --once
                Then edit the task -> Triggers -> Repeat task every 15 minutes, for 1 day.
       Mac/Linux: crontab -e  ->  */15 * * * * /usr/bin/python3 /path/deal_radar.py --once
     Or just leave it running:  python deal_radar.py --loop
"""
import argparse
import calendar
import hashlib
import json
import os
import html
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

import socket
from zoneinfo import ZoneInfo

import feedparser

ET = ZoneInfo("America/New_York")  # GitHub runners are on UTC; the sheet shows Eastern time (Windows needs: pip install tzdata)
socket.setdefaulttimeout(20)  # a feed that never answers must fail, not hang the whole run


def now_et():
    return datetime.now(ET)

HERE = os.path.dirname(os.path.abspath(__file__))
CREDS_FILE = os.path.join(HERE, "service_account.json")
SHEET_ID_FILE = os.path.join(HERE, "sheet_id.txt")
USER_AGENT = "DealRadar/1.0 (personal deal tracker)"
# Grading rules are per source, on the Sources tab: G Category, H Min heat, I Min price,
# J "Grade if title has" (comma list), K Every (min) = how often to pull it (blank = every run). A row is queued for Claude (Status New) when it matches
# the Watchlist, or heat >= H, or price >= I, or its title contains a J word. Otherwise "Low".
DEFAULT_MIN_HEAT = 40    # used when H is blank
MAX_AGE_DAYS = 3         # older posts are logged as Low (often already expired)
SKIP_UNDER = 15          # tiny-ticket deals are logged but not graded (saves tokens),
                         # unless the title has one of the source's J words (e.g. "free")

# Comma form needs at least one ",ddd" group; otherwise "$3461" would stop after "346".
PRICE_RE = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)")
THUMBS_RE = re.compile(r"Thumb Score:\s*\+?(-?\d+)", re.I)
STORE_RE = re.compile(r"^\s*([A-Z][\w.&' +-]{1,40}?)\s+(?:has|is offering|offers)\b")
TAG_RE = re.compile(r"<[^>]+>")


def clean(text):
    return re.sub(r"\s+", " ", html.unescape(TAG_RE.sub(" ", text or ""))).strip()


def parse_price(title):
    m = PRICE_RE.search(title or "")
    return float(m.group(1).replace(",", "")) if m else None


def parse_store(summary_text, link):
    m = STORE_RE.search(summary_text)
    if m:
        return m.group(1).replace(".com", "").strip()
    host = urllib.parse.urlparse(link).netloc.lower().replace("www.", "")
    return host.split(".")[0].capitalize() if host and "slickdeals" not in host and "reddit" not in host else ""


def deal_id(source, entry):
    raw = entry.get("id") or entry.get("link") or entry.get("title", "")
    return source[:3].lower() + "-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


SD_THREAD_RE = re.compile(r"slickdeals\.net/(?:f/|thread-)(\d+)")


def same_deal_key(link_or_id):
    """One key per deal across feeds: Slickdeals thread number, else the link without tracking."""
    m = SD_THREAD_RE.search(link_or_id or "")
    if m:
        return "sd" + m.group(1)
    return (link_or_id or "").split("?")[0].split("#")[0].rstrip("/").lower()


def watch_match(title, price, watchlist):
    t = title.lower()
    for w in watchlist:
        words = [x for x in re.split(r"\s+", w["keyword"].lower()) if x]
        if not words or not all(x in t for x in words):
            continue
        if w["must"] and w["must"].lower() not in t:
            continue
        if any(x.strip() and x.strip().lower() in t for x in w["exclude"].split(",")):
            continue
        if w["max"] and price and price > w["max"]:
            return f"{w['keyword']} (over max ${w['max']:g})"
        return f"{w['keyword']} \u2713"
    return ""


def num(x):
    try:
        return float(str(x).replace("$", "").replace(",", "").strip())
    except ValueError:
        return None


def make_rule(row):
    """Read a Sources row's G-J columns into a grading rule."""
    row = (row + [""] * 11)[:11]
    heat = num(row[7]) if str(row[7]).strip() else DEFAULT_MIN_HEAT
    words = [w.strip().lower() for w in str(row[9]).split(",") if w.strip()]
    return {"category": str(row[6]).strip(), "min_heat": heat, "min_price": num(row[8]), "words": words,
            "every": num(row[10]) or 0}


def due(rule, last_pulled, now_dt):
    """Skip slow feeds until their 'Every (min)' has passed (keeps Slickdeals load polite)."""
    if not rule["every"]:
        return True
    try:
        last = datetime.strptime(str(last_pulled)[:16], "%Y-%m-%d %H:%M")
    except ValueError:
        return True
    return now_dt.replace(tzinfo=None) - last >= timedelta(minutes=rule["every"] - 2)


DATE_FORMATS = ("%b %d, %Y", "%Y-%m-%d", "%m/%d/%Y", "%B %d, %Y")
CLOSED = {"claimed", "expired", "returned"}


def parse_date(text):
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(str(text).strip(), fmt).date()
        except ValueError:
            pass
    return None


def load_purchases(sheet, today):
    """Purchases still inside their price-adjustment (or return-and-rebuy) window."""
    try:
        rows = sheet.worksheet("Purchases").get_all_values()[1:]
    except Exception:
        return []
    out = []
    for r in rows:
        r = (r + [""] * 15)[:15]
        item, words, store, bought, paid, claim_by, status = r[0], r[1], r[2], r[3], r[4], r[7], r[12]
        price = num(paid)
        if not item.strip() or price is None or status.strip().lower() in CLOSED:
            continue
        deadline = parse_date(claim_by)
        bought_d = parse_date(bought)
        if deadline is None:  # no price-adjustment policy: still useful for return-and-rebuy for ~30 days
            if bought_d is None or (today - bought_d).days > 30:
                continue
        elif deadline < today:
            continue
        keys = [w for w in re.split(r"[\s,]+", (words or item).lower()) if len(w) > 1]
        out.append({"item": item.strip(), "store": store.strip(), "paid": price, "words": keys})
    return out


def purchase_match(title, price, purchases):
    if price is None:
        return ""
    t = title.lower()
    for p in purchases:
        if p["words"] and all(w in t for w in p["words"]) and price < p["paid"]:
            return f"\U0001f4b8 Lower than your purchase: {p['item']} (paid ${p['paid']:g} at {p['store'] or '?'})"
    return ""


def sync_bought(sheet, deals_ws, now_dt):
    """Copy Deals rows marked Bought? = Y into Purchases (once), so price drops get watched.
    Reads only column R, then just the marked rows - cheap even when Deals is huge."""
    try:
        pws = sheet.worksheet("Purchases")
    except Exception:
        return 0
    bought_col = deals_ws.col_values(18)
    marked = [i + 1 for i, v in enumerate(bought_col) if i > 0 and str(v).strip().upper() in ("Y", "YES")]
    if not marked:
        return 0
    prow = pws.get_all_values()
    done = {(r + [""] * 15)[14] for r in prow[1:]}
    try:
        stores = [r[0] for r in sheet.worksheet("Store policies").get_all_values()[1:] if r and r[0]]
    except Exception:
        stores = []
    nxt = max(len(prow), 1) + 1
    data = []
    for block in deals_ws.batch_get([f"A{i}:R{i}" for i in marked]):
        r = ((block[0] if block else []) + [""] * 18)[:18]
        if not r[0] or r[0] in done:
            continue
        store = next((s for s in stores if s.lower() != "other" and s.lower() in (r[4] + " " + r[3]).lower()), "Other")
        title = ("'" + r[3]) if r[3][:1] in "=+-@" else r[3]
        data.append({"range": f"A{nxt}:F{nxt}", "values": [[title, "", store, now_dt.strftime("%Y-%m-%d"), r[5], r[7]]]})
        data.append({"range": f"M{nxt}:O{nxt}", "values": [["Watching", "Added from Deals - check store, date and price", r[0]]]})
        done.add(r[0])
        nxt += 1
    if data:  # only A-F and M-O: G-L are formulas
        pws.batch_update(data, value_input_option="USER_ENTERED")
    return len(data) // 2


QUEUE_MAX = 150


def write_queue(sheet, deals_ws, statuses, first_new_row, all_rows, upgraded_rows):
    """Keep a small 'Queue' tab listing only the rows Claude must grade, so the grader never
    has to read the (huge) Deals tab. Columns: Deals row, then Deals A-I."""
    try:
        q = sheet.worksheet("Queue")
    except Exception:
        q = sheet.add_worksheet(title="Queue", rows=QUEUE_MAX + 5, cols=10)
    old_new = [i for i, st in enumerate(statuses, start=1) if i > 1 and st == "New"]
    old_new = sorted(set(old_new) | set(upgraded_rows))
    lines = []
    if old_new:
        want = old_new[-QUEUE_MAX:]
        for row_no, block in zip(want, deals_ws.batch_get([f"A{i}:I{i}" for i in want])):
            r = ((block[0] if block else []) + [""] * 9)[:9]
            lines.append([row_no] + r)
    for k, r in enumerate(all_rows):
        if r[9] == "New":
            lines.append([first_new_row + k] + r[:9])
    lines = lines[-QUEUE_MAX:]
    header = [["Deals row", "Deal ID", "Found At", "Source", "Title", "Store", "Price", "Heat", "Link",
               f"Watch Match  |  {len(lines)} rows to grade"]]
    q.batch_clear(["A1:J"])
    q.update(values=header + lines, range_name="A1", value_input_option="RAW")
    return len(lines)


def triage(rule, title, price, heat, match):
    """Decide whether Claude should spend tokens grading this row."""
    if match and "over max" not in match:
        return "New"
    t = title.lower()
    if any(w in t for w in rule["words"]):
        return "New"
    if price is not None and price < SKIP_UNDER:
        return "Low"
    if heat is not None and rule["min_heat"] is not None and heat >= rule["min_heat"]:
        return "New"
    if rule["min_price"] is not None and (price or 0) >= rule["min_price"]:
        return "New"
    return "Low"


def entries_to_rows(source, rule, feed, watchlist, seen, known, now, first_pull=False, upgrades=None, purchases=()):
    """known: same-deal key -> [sheet row, status, heat] for rows already in Deals.
    A Low row whose heat later crosses this source's Min heat (while still fresh) is
    flipped to New, so deals that get hot after we first saw them are not missed."""
    rows = []
    cutoff = time.time() - MAX_AGE_DAYS * 86400
    for e in feed.entries:
        did = deal_id(source, e)
        key = same_deal_key(e.get("id", "")) if "slickdeals" in e.get("id", "") else same_deal_key(e.get("link", ""))
        full = " ".join(c.get("value", "") for c in e.get("content", [])) + " " + (e.get("summary", "") or "")
        tm = THUMBS_RE.search(full)  # Slickdeals puts the thumb score in the full content
        heat = int(tm.group(1)) if tm else None
        pub = e.get("published_parsed") or e.get("updated_parsed")
        stale = pub is not None and calendar.timegm(pub) < cutoff
        if did in seen or (key and key in known):
            k = known.get(key)
            price = parse_price(clean(e.get("title", "")))
            cheap = price is not None and price < SKIP_UNDER  # tiny-ticket deals stay Low even when hot
            if (upgrades is not None and k and k[0] and k[1] == "Low" and heat is not None and not stale and not cheap
                    and rule["min_heat"] is not None and heat >= rule["min_heat"] > (num(k[2]) or 0)):
                upgrades.append({"range": f"G{k[0]}", "values": [[heat]]})
                upgrades.append({"range": f"J{k[0]}", "values": [["New"]]})
                k[1], k[2] = "New", heat
            continue
        title = clean(e.get("title", ""))
        summary = clean(e.get("summary", "") or e.get("description", ""))
        link = e.get("link", "")
        price = parse_price(title)
        match = purchase_match(title, price, purchases) or watch_match(title, price, watchlist)
        status = triage(rule, title, price, heat, match)
        if status == "New" and (stale or (first_pull and not (match and "over max" not in match))):
            status = "Low"  # old post (likely expired), or backlog from a brand-new feed: log, don't grade
        rows.append([did, now, source, title[:200], parse_store(summary, link), price if price is not None else "",
                     heat if heat is not None else "", link, match, status, "", "", "", "", "", "", "", ""])
        seen.add(did)
        if key:
            known[key] = [None, status, heat]  # row number unknown until appended; no upgrade this run
    return rows


NTFY_MAX = 10  # alerts per run, so a burst never floods the phone
DROP = "\U0001f4b8"


def alert_rows(rows):
    """New rows worth a phone alert: a watchlist match within max price, or cheaper than a purchase."""
    return [r for r in rows if r[9] == "New" and ("✓" in r[8] or DROP in r[8])]


def notify(rows):
    """Push alert_rows to ntfy.sh/<NTFY_TOPIC>. Does nothing when the topic is not set."""
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    sent = 0
    for r in alert_rows(rows)[:NTFY_MAX] if topic else []:
        drop = DROP in r[8]
        headers = {"Title": "Deal Radar: price drop" if drop else "Deal Radar: watchlist match",
                   "Tags": "moneybag" if drop else "bell"}
        if r[7].isascii():  # HTTP headers must be plain ASCII
            headers["Click"] = r[7]
        price = f" - ${r[5]:g}" if isinstance(r[5], float) else ""
        body = f"{r[3]}{price}\n{r[8]}".encode("utf-8")
        try:
            urllib.request.urlopen(urllib.request.Request(f"https://ntfy.sh/{topic}", data=body, headers=headers),
                                   timeout=10).close()
            sent += 1
        except Exception as ex:  # an alert failing must never fail the run
            print(f"Alert failed: {ex}")
    return sent


def fetch(url):
    if "reddit.com" in url and "limit=" not in url:
        url += ("&" if "?" in url else "?") + "limit=100"  # each Reddit feed gets one turn per ~2 h, so take a long page
    return feedparser.parse(url, agent=USER_AGENT)


def log_name(row_idx, name):
    """Logs are public on a public repo: never print watchlist keywords."""
    return name if row_idx else "Slickdeals watchlist search"


def get_sheet_id():
    sid = os.environ.get("SHEET_ID", "").strip()
    if not sid and os.path.exists(SHEET_ID_FILE):
        sid = open(SHEET_ID_FILE).read().strip()
    if not sid:
        sys.exit("No sheet ID: set the SHEET_ID secret/environment variable or create sheet_id.txt")
    return sid


def open_sheet():
    import gspread
    sheet_id = get_sheet_id()
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if not raw and not os.path.exists(CREDS_FILE):
        sys.exit("No Google key: set the GOOGLE_SERVICE_ACCOUNT_JSON secret or put service_account.json next to this script")
    gc = gspread.service_account_from_dict(json.loads(raw)) if raw else gspread.service_account(filename=CREDS_FILE)
    return gc.open_by_key(sheet_id)


def run_once(sheet):
    now_dt = now_et()
    now = now_dt.strftime("%Y-%m-%d %H:%M")
    deals = sheet.worksheet("Deals")
    ids = deals.col_values(1)
    seen = set(ids[1:])
    heats, links, statuses = deals.col_values(7), deals.col_values(8), deals.col_values(10)
    known = {}  # same-deal key -> [sheet row, status, heat]
    for i, link in enumerate(links[1:], start=2):
        if link:
            known[same_deal_key(link)] = [i, statuses[i - 1] if i - 1 < len(statuses) else "",
                                          heats[i - 1] if i - 1 < len(heats) else ""]
    upgrades = []
    copied = sync_bought(sheet, deals, now_dt)
    purchases = load_purchases(sheet, now_dt.date())

    wl_rows = sheet.worksheet("Watchlist").get_all_values()[1:]
    watchlist = []
    for r in wl_rows:
        r = (r + [""] * 6)[:6]
        if r[0].strip() and r[5].strip().upper() == "Y":
            try:
                mx = float(str(r[1]).replace("$", "").replace(",", "")) if r[1] else None
            except ValueError:
                mx = None
            watchlist.append({"keyword": r[0].strip(), "max": mx, "must": r[2].strip(), "exclude": r[3]})

    src_ws = sheet.worksheet("Sources")
    src_rows = src_ws.get_all_values()
    if len(src_rows[0]) < 5 or src_rows[0][4] != "Last pulled":
        src_ws.update_acell("E1", "Last pulled")
        src_ws.update_acell("F1", "New items last pull")
    feeds = [(i, r[0], r[1], make_rule(r)) for i, r in enumerate(src_rows[1:], start=2)
             if len(r) > 3 and r[1].startswith("http") and r[3].strip().upper() == "Y"]
    for w in watchlist:  # one Slickdeals title search per active watchlist keyword
        q = urllib.parse.quote_plus(w["keyword"])
        feeds.append((None, f"Slickdeals search: {w['keyword']}",
                      f"https://slickdeals.net/newsearch.php?q={q}&searcharea=deals&searchin=title&rss=1",
                      make_rule([])))

    def last_pulled(i):
        return (src_rows[i - 1] + [""] * 5)[4]

    # Logged-out Reddit allows ~1 request a minute per IP, so pull ONE Reddit feed per run:
    # the due one waiting longest (blank = never pulled sorts first).
    reddit_due = [(last_pulled(i), i) for i, _, u, rule in feeds
                  if i and "reddit.com" in u and due(rule, last_pulled(i), now_dt)]
    reddit_pick = min(reddit_due)[1] if reddit_due else None

    all_rows, status_updates, skipped = [], [], 0
    for row_idx, name, url, rule in feeds:
        if row_idx and not due(rule, last_pulled(row_idx), now_dt):
            skipped += 1
            continue
        if "reddit.com" in url and row_idx != reddit_pick:
            skipped += 1
            continue
        first_pull = bool(row_idx) and not last_pulled(row_idx).strip()
        try:
            feed = fetch(url)
            if feed.get("status", 200) >= 400:  # e.g. Reddit's 429 comes back as an empty, "valid" feed
                raise RuntimeError(f"HTTP {feed.status}")
            if feed.bozo and not feed.entries:
                raise RuntimeError(str(feed.bozo_exception)[:80])
            rows = entries_to_rows(name, rule, feed, watchlist, seen, known, now, first_pull, upgrades, purchases)
            all_rows.extend(rows)
            msg = (now, len(rows))
            print(f"OK   {log_name(row_idx, name)}: {len(feed.entries)} items, {len(rows)} new")
        except Exception as ex:  # keep going if one feed is down
            # A failed first pull keeps E blank, so the first good pull still logs its backlog as Low.
            msg = ("", f"{now} ERROR {ex}") if first_pull else (f"{now} ERROR {ex}", 0)
            print(f"FAIL {log_name(row_idx, name)}: {ex}")
        if row_idx:
            status_updates.append({"range": f"E{row_idx}:F{row_idx}", "values": [list(msg)]})
        time.sleep(3 if "reddit.com" in url else 1)  # be polite (Reddit rate-limits hard)

    first_new_row = len(ids) + 1
    if all_rows:
        resp = deals.append_rows(all_rows, value_input_option="RAW")  # RAW: titles like "+$15 bonus" stay text
        # Sheets appends after the last used row in ANY column, so take the real start row from the reply.
        m = re.search(r"!A(\d+)", resp.get("updates", {}).get("updatedRange", ""))
        if m:
            first_new_row = int(m.group(1))
    if status_updates:
        src_ws.batch_update(status_updates)
    alerts = notify(all_rows)  # after the append, so alerts only go out for rows that were saved
    # Read row numbers BEFORE batch_update: gspread rewrites each range in place ("J12" -> "'Deals'!J12").
    upgraded_rows = [int(u["range"][1:]) for u in upgrades if u["range"].startswith("J")]
    if upgrades:
        deals.batch_update(upgrades)
    queued = write_queue(sheet, deals, statuses, first_new_row, all_rows, upgraded_rows)
    graded = sum(1 for r in all_rows if r[9] == "New")
    print(f"Pulled {len(feeds) - skipped} feeds ({skipped} not due yet). "
          f"Watching {len(purchases)} purchases for price drops ({copied} newly copied from Deals).")
    print(f"Added {len(all_rows)} rows ({graded} queued for Claude to grade); "
          f"{len(upgrades) // 2} earlier rows got hot and were re-queued. Queue: {queued} rows to grade. "
          f"Phone alerts sent: {alerts}.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="pull all feeds one time and exit")
    ap.add_argument("--loop", action="store_true", help="keep running, pulling every 15 minutes")
    args = ap.parse_args()

    sheet = open_sheet()
    if args.loop:
        while True:
            try:
                run_once(sheet)
            except Exception as ex:
                print("Run failed:", ex)
            time.sleep(15 * 60)
    else:
        run_once(sheet)


if __name__ == "__main__":
    sys.exit(main())
