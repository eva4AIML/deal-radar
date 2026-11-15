# Deal Radar 2026 — always-on deal scanner (for Claude and for Eva/Sumit)

Live list: Google Sheet "Deal Radar 2026" (private; ID kept in the GitHub secret SHEET_ID).
Tabs: Deals (A Deal ID … R Bought?), Price History (keyword, date, price, store, title, deal ID, link, note), Watchlist (keyword, max price, must, exclude, notes, Active Y/N), Sources (feeds + rules), How it works.

## Architecture (built to save tokens)
1. COLLECT — deal_radar.py (Python, feedparser + gspread). Free; no AI. Runs on GitHub Actions in a PUBLIC repo (deal-radar.yml, every 15 min; unlimited free minutes). ~208 sources. Sources K 'Every (min)': main feeds + Amazon/Best Buy/Walmart/Target searches every run; category searches every 60 min; Reddit every 30. Normal run ≈ 1 min, hourly run ≈ 7 min (timeout 14, never two at once). Times are written in Eastern.
   - Pulls every Active feed on the Sources tab + a Slickdeals TITLE search per active Watchlist keyword (title search is far more precise than full-text).
   - De-dupes by Deal ID and across feeds (same Slickdeals thread / same link = one row).
   - Triage per source (Sources G Category, H Min heat (blank = 40), I Min price, J "Grade if title has" words): New if watchlist match, title word, heat ≥ H, or price ≥ I. Price never filters: every deal found is written to Deals and cheap deals are graded like any other. Posts > 3 days old = Low (even watchlist matches); a feed's first-ever pull = Low except watchlist matches (no backlog flood).
   - Heat re-check: a Low row whose Slickdeals heat later crosses its source's Min heat (post < 3 days old) is flipped to New once — catches deals that get hot after we first saw them.
   - Heat = Slickdeals thumb score, read from the feed's full content (fixed Nov 14 — it was always blank before).
   - Logs never print watchlist keywords (public repo).
2. GRADE (free, no AI) — the collector auto-grades every queued row whose Verdict is blank (never overwrites a manual verdict) and writes "auto…" in Why, Status = Scored. Rules, in order (thresholds are constants at the top of deal_radar.py):
   - Title says expired / OOS / out of stock / sold out / [dead] → 👎 BAD (checked first, so dead deals never alert).
   - 💸 cheaper than a Purchases row still in its claim window → ✅ MUST BUY, Why "auto price-adjust: Claim $X back at <store> by <claim-by>" + alert.
   - Watchlist match with a known price → graded against the Price History tab (lowest price seen for the same watch keyword, i.e. same or similar product): ≥10% under → 🔥, within 2% (or new low) → 🟢, within 5% → ✅, more than 5% above → ⏳ WAIT. EVERY watchlist match alerts (any price, any verdict; the alert shows the verdict). Max price only shows in Why. No history yet: ✅ if at/under max, ❓ if over max or no max; no price in title → ❓ + alert. Every watchlist match's price is appended to Price History after grading (Note = auto); hand-typed rows (e.g. known sale prices) count too.
   - Title says price mistake/glitch/error and heat ≥ 25 → 🔥 CANNOT MISS + alert ("may get cancelled").
   - Heat ≥ 100 → 🔥 CANNOT MISS (alert only at heat ≥ 300, ALERT_HEAT); heat ≥ 50 → 👍 GOOD (no alert).
   - Else ❓ UNVERIFIED. 🟢 only comes from Price History (watchlist items). An auto ❓ that later gets hot is re-queued and re-graded.
   Alerts: max 10 per run, only for rows found within 3 days, and Deals P Alerted is stamped so a deal is never alerted twice.
2x. OPTIONAL CLAUDE GRADER (not needed now) — Claude scheduled tasks "Deal Radar grader" (PAUSED since Nov 7; resume on request). Grades New rows, writes Verdict/Confidence/All-Time Low/Why, Status = Scored. Category rules (gold premium over spot, jewelry, beauty events, local grocery roundups, services 12-month cost, cars via CarGurus, in-store YMMV) are on 'How it works' A23:A31 — add "follow 'How it works' category rules" to the grader prompts when resuming.
2b. PRICE-DROP REFUNDS — Purchases tab (Item, Match words, Store dropdown, Bought on, Price paid, link) + Store policies tab (verified Nov 14: Best Buy 15 days, holiday purchases Oct 30–Dec 31 → claim by Jan 15 2027; Target 14 days, holiday Nov 1 → Dec 24; Costco 30; Apple 14; Lowe's 30; Home Depot 14 (sources differ); Kohl's 14 (unverified); Walmart/Amazon none → return-and-rebuy). Claim by / Days left / Drop $ are formulas. Collector: flags new deals cheaper than a purchase (💸 in Watch Match → New) and copies Deals rows marked Bought? = Y into Purchases. Grader: price-checks purchases on the first run of each day and alerts '💸 CLAIM $X … by <date>'.
2c. QUEUE — the collector rewrites a small Queue tab (rows to grade, max 150) every run; graders read only Queue, never the whole Deals tab (big token saving). Grader prompts updated Nov 14 to use Queue + category rules + price drops (still PAUSED).
2d. PHONE ALERTS (collector, no AI) — if the repo secret NTFY_TOPIC is set, each run pushes up to 10 alerts to the ntfy app (ntfy.sh/<topic>) for rows the auto-grader marks with an alert (only: every watchlist match (with its verdict), 💸 price drop, price mistake/glitch, or heat ≥ 300). Subscribe to the same topic in the ntfy app. The topic name works like a password: keep it secret.
3. ALERT — push notification for 🔥/🟢 (High/Med confidence) or a ✓ watchlist match that isn't WAIT/BAD.

## Categories covered (Sources tab, added Nov 14)
General/Tech/Apple/Computers/Clothing/Household/Cashback (original 13) + Gold/Silver/Jewelry, Beauty, Sports/Outdoor, Furniture/Mattress, Grocery/Warehouse (Costco, Sam's, BJ's), Auto, Books/Streaming/Software, Local grocery/pharmacy (Southern Savers, I Heart Publix, I Heart Kroger, Aldi, CVS, Walgreens), Services (phone, internet, insurance), Cars (lease, rental; CarGurus via grader), Local clearance (clearance, YMMV, in-store). ~50 New rows/day expected from the new feeds outside peak.
Added later Nov 14 (~26 New/day): TechBargains, 9to5Mac, Android Police; hot-deal searches for Amazon, Best Buy, Walmart, Target, Home Depot, Lowe's; Kohl's, Macy's, Nordstrom, Old Navy, Gap, Belk; r/frugalfemalefashion; LEGO (+ r/legodeal), toys, kids, baby, diapers; Chewy, Petco, pet food; vacuums, air purifiers, smart home, garden, grills; printers, office chairs, cameras; AirPods, iPad, Apple refurb, iPhone, Galaxy; TVs, laptops, Switch, PS5; DoorDash, Uber Eats, restaurants, Starbucks, gift cards, tickets, wine.
Added Nov 14 (third batch, ~36 New/day): major appliances (fridge, washer, dryer, dishwasher, gas/electric range, freezer), kitchen (KitchenAid, Ninja, Vitamix, espresso, air fryer, Instant Pot), audio (headphones, Sony, Bose, JBL, soundbar, Sonos), wearables (Apple Watch, Garmin, Fitbit, Oura), power tools (DeWalt, Milwaukee, Ryobi), holiday decor (trees, lights, inflatables), networking (router, modem, mesh: eero/Orbi/Deco), backup power (EcoFlow, Anker SOLIX, power stations, generators), EV chargers + CarPlay, eyewear (contacts, sunglasses, eyeglasses, Warby Parker, Zenni), health products (vitamins, iHerb, protein), luggage + backpacks, bedding (sheets, comforters, towels), board games/puzzles/Michaels/Hobby Lobby, Coursera/MasterClass, money (checking/bank bonuses, Rakuten, Remitly, money transfer), marketplaces (eBay, eBay coupon, eBay Refurbished, Newegg, B&H, Micro Center, Woot, Back Market, open box, Amazon Resale, Dell, Lenovo, Groupon).
Not reachable by feed (grader/web only): store-app and loyalty offers (Target Circle, Kohl's Cash, Walmart+), card-linked offers (Amex/Chase/BofA), BrickSeek local inventory, print doorbuster ad scans, Facebook Marketplace/Craigslist, Groupon local.
Off: Ben's Bargains (403 to bots), flight feeds (Travel project). Tested and rejected: Woot, Brad's Deals, camelcamelcamel RSS, employee subreddits.

## Verdict rules
🔥 CANNOT MISS ≥10% under the all-time low, or at/below it with a stack · 🟢 ALL-TIME LOW within 2% · ✅ MUST BUY within 5% (or, only if no low is known, ≤ last Black Friday) · 👍 GOOD no low known but ≥25% off a credible regular price · ⏳ WAIT >5% above the known low · 👎 BAD fake discount / lower-spec store model / sketchy seller · ❓ UNVERIFIED.

## Collector setup (one time)
- Google Cloud → enable Sheets API → service account → JSON key. Share the sheet with the service account email as Editor. Keep the sheet private.
- GitHub: new PUBLIC repo with deal_radar.py and .gitignore in the root and .github/workflows/deal-radar.yml. Secrets: GOOGLE_SERVICE_ACCOUNT_JSON (whole JSON) and SHEET_ID. Run once from the Actions tab.
- Or laptop: `pip install feedparser gspread google-auth tzdata`, put service_account.json + sheet_id.txt next to the script, `python deal_radar.py --once`, schedule every 15 min.
- Reddit sometimes rate-limits cloud IPs; if those rows show ERROR in Sources!E, set them Active = N.

## Related
- Nov 7 full ad scan (408 deals): ../deal-tracker/ (master CSV parts + Holiday_2026_Deal_Tracker.xlsx builder).
