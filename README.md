# Deal Radar 2026 — always-on deal scanner (for Claude and for Eva/Sumit)

Live list: Google Sheet "Deal Radar 2026" (private; ID kept in the GitHub secret SHEET_ID).
Tabs: Deals (A Deal ID … R Bought?), Watchlist (keyword, max price, must, exclude, notes, Active Y/N), Sources (feeds + rules), How it works.

## Architecture (built to save tokens)
1. COLLECT — deal_radar.py (Python, feedparser + gspread). Free; no AI. Runs on GitHub Actions in a PUBLIC repo (deal-radar.yml, every 15 min; unlimited free minutes). ~208 sources. Sources K 'Every (min)': main feeds + Amazon/Best Buy/Walmart/Target searches every run; category searches every 60 min; Reddit every 30. Normal run ≈ 1 min, hourly run ≈ 7 min (timeout 14, never two at once). Times are written in Eastern.
   - Pulls every Active feed on the Sources tab + a Slickdeals TITLE search per active Watchlist keyword (title search is far more precise than full-text).
   - De-dupes by Deal ID and across feeds (same Slickdeals thread / same link = one row).
   - Triage per source (Sources G Category, H Min heat (blank = 40), I Min price, J "Grade if title has" words): New if watchlist match, title word, heat ≥ H, or price ≥ I. Under $15 = Low unless a title word matches. Posts > 3 days old = Low (even watchlist matches); a feed's first-ever pull = Low except watchlist matches (no backlog flood).
   - Heat re-check: a Low row whose Slickdeals heat later crosses its source's Min heat (post < 3 days old) is flipped to New once — catches deals that get hot after we first saw them.
   - Heat = Slickdeals thumb score, read from the feed's full content (fixed Nov 14 — it was always blank before).
   - Logs never print watchlist keywords (public repo).
2. GRADE — Claude scheduled tasks "Deal Radar grader" (PAUSED since Nov 7; resume on request). Grades New rows, writes Verdict/Confidence/All-Time Low/Why, Status = Scored. Category rules (gold premium over spot, jewelry, beauty events, local grocery roundups, services 12-month cost, cars via CarGurus, in-store YMMV) are on 'How it works' A23:A31 — add "follow 'How it works' category rules" to the grader prompts when resuming.
2b. PRICE-DROP REFUNDS — Purchases tab (Item, Match words, Store dropdown, Bought on, Price paid, link) + Store policies tab (verified Nov 14: Best Buy 15 days, holiday purchases Oct 30–Dec 31 → claim by Jan 15 2027; Target 14 days, holiday Nov 1 → Dec 24; Costco 30; Apple 14; Lowe's 30; Home Depot 14 (sources differ); Kohl's 14 (unverified); Walmart/Amazon none → return-and-rebuy). Claim by / Days left / Drop $ are formulas. Collector: flags new deals cheaper than a purchase (💸 in Watch Match → New) and copies Deals rows marked Bought? = Y into Purchases. Grader: price-checks purchases on the first run of each day and alerts '💸 CLAIM $X … by <date>'.
2c. QUEUE — the collector rewrites a small Queue tab (rows to grade, max 150) every run; graders read only Queue, never the whole Deals tab (big token saving). Grader prompts updated Nov 14 to use Queue + category rules + price drops (still PAUSED).
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
