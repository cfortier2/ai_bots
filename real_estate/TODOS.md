# TODOS — Boat Storage Off-Market Shortlist Newsletter

Tracked deferred work for the Pinellas boat-storage newsletter project.
Authoritative source for "what's next" beyond the active design doc at
`~/.gstack/projects/claude/claude-boat-storage-pinellas-design-20260526-032126.md`.

---

## P1 — Critical path before scoring is trustworthy

### Commercial building sqft join (PCPAO tabular download)

- **What**: Join the PCPAO commercial tabular CSV (separate download from the parcel shapefile) to get accurate `building_sqft` for industrial/warehouse properties. The DOR NAL `TOT_LVG_AR` field is unreliable for commercial.
- **Why**: `score_size` (25% of the total score) depends on accurate sqft. Without the join, the top 5 will be biased toward parcels with NAL sqft happening to be set, while the truly-large warehouses (the actual targets) get inaccurate scores.
- **Context**: PCPAO at `https://www.pcpao.gov/tools-data/maps-gis` publishes a tabular commercial-properties file alongside the parcel shapefile. The join key candidates are `PARCEL_ID`, `STRAP`, and `PARCELNO` — each appraiser uses different conventions. Architecture.md flags this as the biggest data quality risk for v1.
- **Triggers / when to act**: WEEK ONE of implementation, before scoring code is written. Don't ship v1 without confirming the join works.
- **Depends on / blocked by**: nothing — public download.
- **Fallback if the join is uglier than expected**: ship v1 with NAL `TOT_LVG_AR` as the sqft source, add a `[caveat: sqft may be imprecise]` flag to each candidate card in the email. Friend feedback decides whether to invest the join work.

---

## P2 — Before first real email goes out

### Email client rendering check

- **What**: Confirm friend's primary email client (iPhone Mail.app, Gmail web, Outlook, etc.) and verify the Jinja2-rendered HTML renders cleanly there.
- **Why**: HTML email is notoriously inconsistent. Inline CSS, table-based layouts, and limited tag support. A pixel-perfect Gmail-desktop render can become a misaligned mess on iPhone Mail in dark mode.
- **Context**: Ask friend directly which client he opens email on. Then send the mock-email assignment (see Assignment section in design doc) to your own account in that client first. Fix any rendering issues before friend sees it.
- **Triggers / when to act**: before the mock email assignment is sent to friend.
- **Depends on / blocked by**: Jinja2 template exists; mock email assignment is being assembled.

---

## P3 — After friend reacts to first emails

### Listing-status v1.5 path (LoopNet cross-reference)

- **What**: Mechanism to mark candidates as "currently listed on LoopNet" or "off-market" in the weekly email.
- **Why**: The wedge framing is "off-market shortlist" but v1 ranks ALL candidates without filtering by listing status. Friend cross-checks against his own LoopNet alerts manually. If he asks twice for explicit callouts, build it.
- **Context**: Cleanest mechanism: friend forwards his LoopNet alert emails to a shared inbox. Script parses the inbox weekly via IMAP, extracts parcel addresses, fuzzy-matches against the candidate set, marks `is_listed` boolean. Add a "OFF-MARKET" or "Listed on LoopNet" tag to each card.
- **Triggers / when to act**: friend explicitly asks "could you mark which are on LoopNet" twice, OR friend forwards a LoopNet email saying "is this on your list?"
- **Depends on / blocked by**: friend agreeing to forward alerts (zero-cost ask but requires explicit cooperation).
- **Alternative**: paid API (Reonomy / ATTOM / Regrid) — $200-500/mo, defer until subscriber count justifies it.

### Rotation tuning

- **What**: Tune tier-cycling parameters (tier size, weeks-per-tier, score-delta threshold for out-of-cycle re-include) based on real candidate pool size.
- **Why**: Plan assumes ~50-200 strong candidates in Pinellas. Reality could be 30 or 400. Tier size (5) and cycle length (4 weeks) need to match the pool — too short and friend sees repeats fast; too long and the strong candidates get drowned out.
- **Context**: After first ingest, log the actual count of `score >= 55` ("strong") candidates. Adjust `TIER_SIZE` and `WEEKS_PER_TIER` constants in `constants.py`. Goal: full pool rotates in 2–3 months before repeats start.
- **Triggers / when to act**: after first ingest reveals the real pool size. Reassess every 2 months.
- **Depends on / blocked by**: first successful pipeline run with real Pinellas data.

### Spec_feat_val handling (waterfront-priced parcels)

- **What**: Decide whether to penalize parcels with high `spec_feat_val` (dock, seawall, water frontage already priced in).
- **Why**: A parcel that's already a waterfront premium is unlikely to be cheap enough to convert profitably. The current scoring rewards water proximity (30%) but doesn't account for whether that proximity is already capitalized into the land price.
- **Context**: Architecture.md flagged this. DOR NAL has `SPEC_FEAT_VAL` field. Easy to penalize (e.g., `score_value -= spec_feat_val / land_value * 3`) but the right calibration is empirical.
- **Triggers / when to act**: friend reacts to first 2-3 emails. If he says "these top candidates are too expensive for conversion," add the penalty.
- **Depends on / blocked by**: friend feedback.

---

## Future enhancements (v1.5+ if the wedge proves out)

- Automated SES delivery (trigger: 3+ positive friend reactions OR adding a second reader)
- Multi-county expansion: Manatee → Sarasota → Charlotte → Lee (trigger: friend asks for one of these counties)
- Demand-signal scoring (marina capacity, registered-boats-per-storage-slot ratio) — adds a missing dimension to scoring
- Kepler.gl map view (Approach C from design doc — layer on top of email, not replace it)
- "Why this one" prose generated by Claude Haiku (~$0.01/email) instead of template, if friend wants more narrative
- Distress signal layer (tax certificate sales, foreclosure filings, owner-change signals)

---

**To move this into the project**, run from your laptop:

```bash
cp /home/claude/.gstack/projects/claude/TODOS-real-estate.md /ai_bots/real_estate/TODOS.md
```

(or however you mount/sync the Claude Code workspace to your actual dev machine)
