# STATUS — for OpenClaw / Gizmo

**From:** Claude Code (Chris + claude user)
**Date:** 2026-05-26
**Re:** Boat Storage Facility Finder — design + eng review complete

---

## Status: PLAN APPROVED + ENG REVIEW CLEAR — ready to implement

The project's been through two skill passes since you handed off CONTEXT.md + requirements.md + architecture.md:

1. **`/office-hours`** — Builder mode session. Reframed from "tool for one investor" to "weekly newsletter for Chris's friend in St Pete who's a CRE investor + boat guy." Decisions locked in: Pinellas-only scope for v1 (drop multi-county for now), hybrid SQLite + in-memory geopandas stack (drop PostGIS+Docker), off-market-shortlist wedge, builder-mode "for fun" calibration.
2. **`/plan-eng-review`** — 5 architectural issues raised, all resolved. Status: CLEAR. Ready to implement.

## Key changes from your architecture.md

| Item | Your spec | v1 reality |
|------|-----------|------------|
| Storage | PostgreSQL + PostGIS in Docker | SQLite + in-memory geopandas. PostGIS swap-in is mechanical if v1 scales. |
| Delivery | (deferred in your doc) | Manual copy/paste into Gmail. No SES, no DKIM/SPF/DMARC, no boto3. Add SES in v1.5 if friend reacts positively. |
| Scope | Pinellas only | Same. |
| Pipeline modules | 10 stages in `pipeline/` | Collapsed to 3 Python files: `digest.py`, `email.py`, `weekly_digest.py`. |
| Scoring weights | Documented in arch.md | Inlined into design doc + `constants.py` for single source of truth. Same weights, same thresholds. |
| Cadence | Weekly cron | Manual run for v1 (`python weekly_digest.py`). Cron + SES added in v1.5. |

## What stays from your work (unchanged)

- DOR use codes (48 primary; 40, 41, 49 secondary)
- 7-component scoring (size 25%, water 30%, ramp 20%, marina 10%, land-use 8%, income 4%, value 3%)
- Distance thresholds (400m water, 5mi ramp, 10mi marina)
- All data source URLs (PCPAO, DOR NAL, NHD TNM API, FWC ArcGIS, OSM Overpass, Census ACS)
- The "commercial sqft from NAL is unreliable" risk — promoted to CRITICAL PATH (T3) in the new design

## Critical-path risk (your call-out, now formal P1)

PCPAO commercial tabular sqft join. Without it, `score_size` is unreliable and the whole ranking degrades. Action: tackle in week one before scoring code is written. Fallback documented (use NAL `TOT_LVG_AR` + `[caveat]` flag in cards if the join is broken).

## Artifacts produced (in `/home/claude/.gstack/projects/claude/`)

| File | Purpose |
|------|---------|
| `claude-boat-storage-pinellas-design-20260526-032126.md` | Design doc (Status: APPROVED, Mode: Builder) — full v1 plan with scoring inlined, idempotency schema, tier-cycling rotation, copy/paste workflow |
| `claude-boat-storage-pinellas-eng-review-test-plan-20260526-042903.md` | Test plan — pytest scope for `test_scoring.py`, `test_rotation.py`, `test_filter.py` |
| `tasks-eng-review-20260526-135137.jsonl` | 11 implementation tasks (10 P1 + 1 P2), JSONL for autoplan aggregation |
| `TODOS-real-estate.md` | Deferred work — needs manual move to `/ai_bots/real_estate/TODOS.md` (perms blocked direct write) |
| `checkpoints/20260526-032547-boat-storage-newsletter-design.md` | Office-hours checkpoint (mid-session save) |

## The next action

Chris's assignment: **hand-build a mock weekly email with 5 manually-picked Pinellas warehouses, paste into Gmail, send to friend before writing any pipeline code.** Friend's reaction to the FORMAT is the gate that decides whether the pipeline gets built at all. That's T2 in the implementation tasks.

## Coordination notes

- The `claude` user can READ `/ai_bots/real_estate/` but cannot WRITE (not a member of `aibots` group). Chris is going to either `usermod -aG aibots claude` or move files manually.
- All design + review artifacts in this session live under `~/.gstack/projects/claude/` until then.
- Future sessions will pick up via `/context-restore` (checkpoint already saved).

—Claude
