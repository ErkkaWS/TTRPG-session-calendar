# 100% vibe coded: TTRPG Session Scheduler

Fighting against the TTRPG curse: a publicly shared, login-free
availability calendar for TTRPG groups, including a Discord server
bot that "motivates" players to mark their availability in the
calendar and, of course, **ANNOUNCES** when a common session date is
found!

> **Note:** every Firebase and hosting URL in this repo is a
> placeholder. The app is designed so that no login is required to
> use it, which means the URL itself is the only thing keeping it
> private — see [Configuration](#configuration) to fill in your own
> values.

---

## Built from

- **Frontend:** a single static HTML file (`calendar.html`) — no
  framework, no build step. Vanilla JS + CSS, Firebase JS SDK loaded
  via `<script>` tag. All the campaign-specific text (name, intro
  title, date range) lives in one clearly marked config block near
  the top of the `<script>` section.
- **Database:** Firebase Realtime Database — free tier, open
  read/write rules (no accounts to check against, by design).
- **Hosting:** any static host works (Netlify, Vercel, GitHub Pages,
  your own server).
- **Bot logic:** a small script, written twice — once in Python
  (`check.py`) and once in Node.js (`check.js`) — doing the exact
  same thing, for whichever runtime your machine has available.
- **Scheduling:** `cron` on an always-on Linux box (e.g. a
  Raspberry Pi). GitHub Actions is included as an alternative but
  turned out to be unreliable for this — see
  [Why not GitHub Actions](#why-not-github-actions).
- **Notifications:** plain Discord incoming webhooks — no bot
  application, no gateway connection, just HTTP POST.

## How it works

```
┌─────────────┐        ┌──────────────────┐        ┌─────────────┐
│  Player's   │  HTTPS │  Static hosting   │        │  Firebase   │
│  browser    │◄──────►│  (e.g. Netlify)   │        │  Realtime   │
│             │        │                   │        │  Database   │
└─────────────┘        └──────────────────┘        └──────┬──────┘
                                                            │
                                                     read / write
                                                            │
                                                    ┌───────▼───────┐
                                                    │  check.py     │
                                                    │  (cron, every │
                                                    │   5 minutes)  │
                                                    └───────┬───────┘
                                                            │
                                                    webhook (POST)
                                                            │
                                                    ┌───────▼───────┐
                                                    │   Discord     │
                                                    │  #schedule    │
                                                    │  #announce    │
                                                    └───────────────┘
```

The calendar page is fully static (no server of its own) — all state
lives in Firebase. The check script is a completely separate,
independent process; it doesn't matter whether anyone is on the
calendar page when it runs. Every 5 minutes it:

1. Pulls the current calendar data from Firebase
2. Works out which upcoming days have enough people free (and nobody
   marked busy)
3. Decides, based on cooldowns and what's already been announced,
   whether anything needs posting
4. Posts to Discord via webhook if so, and writes back a small
   amount of state (last notified time, which dates have already
   been announced) so it doesn't repeat itself

## Customizing it for your group

Everything you're likely to want to change lives in two clearly
marked blocks:

**`calendar.html`**, near the top of the `<script>` tag:
```javascript
const CAMPAIGN_NAME = "YOUR CAMPAIGN NAME HERE";
const INTRO_TITLE = "YOUR GAME TITLE";
const INTRO_SUBTITLE = "YOUR EDITION / YEAR";
const START_YEAR = 2026;
const START_MONTH = 9;       // 0 = January ... 11 = December
const NUMBER_OF_MONTHS = 15;
```

**`check.py`** / **`check.js`**, near the top of the file:
```python
CALENDAR_LINK = 'https://YOUR_SITE.netlify.app/'
COOLDOWN_MS = 15 * 60 * 1000
REMINDER_INTERVAL_MS = 3 * 24 * 60 * 60 * 1000
MIN_FREE_FOR_RECAP = 4
ANNOUNCE_THRESHOLD = 6
ANNOUNCEMENT_MESSAGE = "Heads up — we found a shared session date! ..."
```

Both files also need the matching `firebaseConfig` / `FIREBASE_URL`
for your own Firebase project (see [Configuration](#configuration)).

## Current implementation spec

This reflects the exact settings and message logic as last tested
and deployed. All of these are just the *default* values of the
constants above — change them freely.

**Scheduling:**
- Check script runs every **5 minutes** via `cron`
- **Recap cooldown:** 15 minutes after the last calendar edit before
  a recap is sent — lets one person finish marking several days
  before anything is posted
- **Leave button bypass:** clicking "Leave" on the calendar
  backdates the last-edit timestamp so the *next* check (within 5
  min) sends the recap immediately, instead of waiting out the full
  cooldown
- **Reminder interval:** every 3 days, independent of whether anyone
  has edited anything
- **Post-session quiet period:** 3 days of no reminders after a
  found date has passed, before reminders resume

**Recap thresholds** (a "candidate day" = at least this many people
marked free, and nobody marked busy on it):
- `MIN_FREE_FOR_RECAP = 4` — minimum to count as a candidate at all
- **0 candidate days:** light nudge message only
- **1+ candidate days, best day below the announce threshold:** full
  recap with a ranked list of candidate days
- **Best day ≥ `ANNOUNCE_THRESHOLD` (default 6):** nothing posted to
  the schedule channel; instead a one-time announcement goes to the
  announcement channel (only once per date — re-editing the calendar
  afterward won't repeat it)

**Message texts** (channel in brackets):

```
[schedule] Reminder: mark your availability in the calendar so we
can find a shared session date!
<calendar link>
```

```
[schedule] <name> made some updates, go check it out!
<calendar link>
```

```
[schedule] <name> made some updates to the calendar!

Possible session days: <count>

<date> — <count> players
<date> — <count> players
<calendar link>
```

```
[announce] <your ANNOUNCEMENT_MESSAGE>
<calendar link>
```

## Files

| File | What it is |
|---|---|
| `calendar.html` | The whole calendar app, single file |
| `check.py` | Check script for Python 3 (Raspberry Pi or any Linux box) |
| `check.js` | Same logic in Node.js (e.g. for GitHub Actions) |
| `.github/workflows/check.yml` | GitHub Actions workflow (see reliability note below) |
| `run.sh` | Startup wrapper — loads secrets, then runs `check.py` |
| `secrets.env.example` | Template for the two webhook URLs — copy to `secrets.env`, never commit the filled-in version |
| `logrotate.conf` | Optional logrotate config to keep the local log file small long-term |

`.gitignore` excludes `secrets.env` (real secrets) and `bot.log`
(local log) — only `secrets.env.example` belongs in the repo.

## Configuration

### 1. Firebase

1. Create a project at [console.firebase.google.com](https://console.firebase.google.com)
2. Enable **Realtime Database**
3. Set rules to allow open access (no accounts exist to check
   against, by design):
   ```json
   {
     "rules": {
       ".read": true,
       ".write": true
     }
   }
   ```
   Firebase's default "test mode" rules expire after 30 days — use
   the permanent rule above for real use.
4. Register a web app, copy the `firebaseConfig` values
5. Paste them into the `firebaseConfig` block at the top of
   `calendar.html`, and set the matching `FIREBASE_URL` in
   `check.py` / `check.js`

### 2. Hosting the calendar

Any static host works — `calendar.html` is fully self-contained, no
build step. Put the resulting URL into `CALENDAR_LINK` in
`check.py` / `check.js`.

### 3. Discord webhooks

1. Channel settings → Integrations → Webhooks → New Webhook, for
   each of two channels (regular updates, and the big "we found a
   date" announcement)
2. `cp secrets.env.example secrets.env`
3. Fill in the real webhook URLs in `secrets.env`
4. `chmod 600 secrets.env`

### 4. Scheduling the check script

**Recommended: cron on any always-on Linux machine** (e.g. a
Raspberry Pi):

```bash
chmod +x run.sh check.py
crontab -e
```
Add:
```
*/5 * * * * /path/to/run.sh >> /path/to/bot.log 2>&1
```

### Why not GitHub Actions

`.github/workflows/check.yml` is included and works, but with a real
caveat found during testing: GitHub does not guarantee sub-5-minute
scheduling, and in practice, scheduled runs were sometimes delayed
by hours during high load — GitHub's own docs acknowledge this ("the
schedule event can be delayed... some queued jobs may be dropped").
Fine for the 3-day reminder, not reliable for timely recaps. A
dedicated machine with `cron` was far more consistent in testing.

## Implementation notes

- **Firebase silently converts sequential numeric keys into a JSON
  array** instead of an object (e.g. if player names happen to be
  `"1"`, `"2"`, `"3"`) — `check.py` handles both shapes defensively
  (`check.js` doesn't need to — `Object.values()` works on arrays
  too in JavaScript).
- **Cloudflare (in front of Discord) rejects default HTTP requests**
  with no `User-Agent` header (HTTP 403, Cloudflare error 1010) —
  every request sets an explicit one.
- **Firebase's "test mode" rules expire after 30 days** — switch to
  the permanent rule above before that happens, or both the
  calendar and the bot stop working with no warning.

## Security note

- `secrets.env` (real webhook URLs) must never enter git history —
  only the `.example` template belongs in this repo.
- Open read/write Firebase rules are a deliberate choice for this
  low-sensitivity use case (just availability data), not a general
  recommendation for other projects.
