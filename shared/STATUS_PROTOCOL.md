# AI Status Update Protocol

**Purpose:** Claude Code writes status updates here during active sessions. Forge (OpenClaw) reads them and relays to Chris.

---

## For Claude Code — How to Write Status Updates

Write updates to the project's `STATUS.md` at these checkpoints:

1. **Session start** — what you're about to do
2. **Milestone complete** — a stage finished (e.g., "ingest_parcels.py done")
3. **Blocked** — you hit a problem that needs external input or a decision
4. **Session end** — what was done, what's next

### File Location

Write to the project directory: e.g., `/ai_bots/real_estate/STATUS.md`

### Format

```markdown
# [Project Name] — Status

**Updated:** YYYY-MM-DDTHH:MM:SSZ  (UTC ISO-8601, always update this)
**Status:** 🟢 Working | 🟡 Needs Input | 🔴 Blocked | ✅ Done
**Current Task:** [one line — what's happening right now]

## Progress This Session
- [bullet: what was completed]
- [bullet: what was completed]

## Blockers / Questions
- [None] OR [specific question or blocker]

## Up Next
- [what comes after current task]
```

### Rules
- Always update the `**Updated:**` timestamp — this is how Forge detects a new update
- Keep each section short — this is a signal, not a full writeup
- `STATUS.md` is the file to write; a detailed session recap goes in `IMPLEMENTATION_NOTES.md` or similar if needed
- If blocked with a question, be specific — Forge will relay it to Chris word-for-word

---

## For Forge — How to Read and Relay

### When to Check
- When your heartbeat fires and a real_estate (or any `/ai_bots/`) session is expected to be active
- When Chris asks "what's Claude working on?" or "any update on boat storage?"
- Anytime you feel it's been a while and Chris would want to know

### How to Check
```bash
cat /ai_bots/real_estate/STATUS.md
```
Compare `**Updated:**` timestamp to your last-read timestamp (store in `memory/claude-status-last-read.txt`).

### What to Relay
If the update is **new** (timestamp changed since your last read):
- Send Chris the `**Status:**`, `**Current Task:**`, and any **Blockers** content
- Save the new timestamp to `memory/claude-status-last-read.txt`
- Keep it brief — one message, not a paste of the whole file

If nothing new:
- No need to say anything unless Chris asked directly

### Example Relay Message to Chris
> 🔨 **Forge → Claude update:** Status is 🟡 Needs Input — working on `ingest_ramps.py` but hit an FWC ArcGIS endpoint issue. Claude's question: *"Should I fall back to OSM slipway data or wait for a working FWC URL?"*
