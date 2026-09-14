#!/usr/bin/env python3
# ============================================================
# SESSION SCHEDULER — CHECK SCRIPT
# Python version — works on any Linux box (e.g. a Raspberry Pi),
# no Node.js or Docker required.
# ============================================================

import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone

# ============================================================
# CUSTOMIZE THESE VALUES
# ============================================================

# Your Firebase Realtime Database URL (same project as calendar.html)
FIREBASE_URL = 'https://YOUR_PROJECT_ID-default-rtdb.YOUR_REGION.firebasedatabase.app'

# The public URL where the calendar is hosted (e.g. your Netlify site)
CALENDAR_LINK = 'https://YOUR_SITE.netlify.app/'

# How long to wait after the last edit before sending a recap
COOLDOWN_MS = 15 * 60 * 1000

# How often the "please mark your availability" reminder repeats
REMINDER_INTERVAL_MS = 3 * 24 * 60 * 60 * 1000

# Minimum number of people free on a day for it to count as a candidate
MIN_FREE_FOR_RECAP = 4

# Minimum number of people free for a day to trigger the big
# "we found a date!" announcement (separate channel, one-time per date)
ANNOUNCE_THRESHOLD = 6

# The big announcement message — write your own here
ANNOUNCEMENT_MESSAGE = "Heads up — we found a shared session date! Time to get the party together."

# ============================================================

AIKATAULU_WEBHOOK = os.environ.get('DISCORD_WEBHOOK_SCHEDULE')
ANNOUNCE_WEBHOOK = os.environ.get('DISCORD_WEBHOOK_ANNOUNCE')


def format_date(key):
    y, m, d = key.split('-')
    return f'{d}.{m}.{y}'


def today_key():
    return datetime.now(timezone.utc).strftime('%Y-%m-%d')


def now_ms():
    return int(time.time() * 1000)


HEADERS_JSON = {'Content-Type': 'application/json', 'User-Agent': 'SessionScheduler/1.0 (cron script)'}


def get_json(path):
    url = f'{FIREBASE_URL}/{path}.json'
    req = urllib.request.Request(url, headers={'User-Agent': HEADERS_JSON['User-Agent']})
    with urllib.request.urlopen(req, timeout=15) as res:
        raw = res.read().decode('utf-8')
        return json.loads(raw) if raw != 'null' else None


def put_json(path, value):
    url = f'{FIREBASE_URL}/{path}.json'
    data = json.dumps(value).encode('utf-8')
    req = urllib.request.Request(url, data=data, method='PUT', headers=HEADERS_JSON)
    with urllib.request.urlopen(req, timeout=15):
        pass


def send_webhook(url, content):
    if not url:
        print('ERROR: webhook URL is missing (env var is empty or misnamed).')
        return
    data = json.dumps({'content': content}).encode('utf-8')
    req = urllib.request.Request(url, data=data, method='POST', headers=HEADERS_JSON)
    try:
        with urllib.request.urlopen(req, timeout=15) as res:
            if res.status < 200 or res.status >= 300:
                print(f'ERROR: Discord rejected the message. Status {res.status}')
            else:
                print('Webhook sent successfully.')
    except urllib.error.HTTPError as e:
        print(f'ERROR: Discord rejected the message. Status {e.code}: {e.read().decode("utf-8", "ignore")}')


def analyze_days(data):
    # Note: Firebase silently turns sequential numeric keys (e.g. "1","2","3")
    # into a JSON array instead of an object, so both shapes are handled here.
    today = today_key()
    days = []
    for key, entries in (data or {}).items():
        if key < today:
            continue
        if isinstance(entries, dict):
            values = list(entries.values())
        elif isinstance(entries, list):
            values = [v for v in entries if v is not None]
        else:
            values = []
        days.append({
            'key': key,
            'free': values.count('free'),
            'busy': values.count('busy')
        })
    return days


def best_days(days, min_free):
    candidates = [d for d in days if d['free'] >= min_free and d['busy'] == 0]
    candidates.sort(key=lambda d: d['free'], reverse=True)
    return candidates


def format_list(days):
    if not days:
        return None
    return '\n'.join(f"{format_date(d['key'])} — {d['free']} players" for d in days)


def run_reminder(days):
    max_free = max([d['free'] for d in days if d['busy'] == 0], default=0)
    if max_free >= ANNOUNCE_THRESHOLD:
        print('No reminder needed, a suitable date has already been found.')
        return

    today = today_key()
    announced = get_json('announced') or {}
    past_sessions = sorted(k for k in announced.keys() if k < today)

    if past_sessions:
        last_session = past_sessions[-1]
        last_session_dt = datetime.strptime(last_session, '%Y-%m-%d').replace(tzinfo=timezone.utc)
        days_since = (datetime.now(timezone.utc) - last_session_dt) / timedelta(days=1)
        if days_since < 3:
            print(f'Less than 3 days since the last session ({last_session}), staying quiet for now.')
            return

    last_reminder = get_json('meta/last_reminder_time')
    now = now_ms()
    if last_reminder and (now - last_reminder) < REMINDER_INTERVAL_MS:
        hours = round((now - last_reminder) / 3600000)
        print(f'Last reminder was {hours}h ago, not due yet.')
        return

    message = 'Reminder: mark your availability in the calendar so we can find a shared session date!'
    send_webhook(AIKATAULU_WEBHOOK, f'*{message}*\n\n{CALENDAR_LINK}')
    put_json('meta/last_reminder_time', now)


def run_recap(days, data):
    last_edit_time = get_json('meta/last_edit_time')
    last_editor = get_json('meta/last_editor')
    last_notified = get_json('meta/last_notified_edit_time')

    if not last_edit_time:
        print('No edits yet.')
        return
    if last_notified == last_edit_time:
        print('This edit has already been reported.')
        return

    elapsed = now_ms() - last_edit_time
    if elapsed < COOLDOWN_MS:
        print(f'Cooldown in progress ({round(elapsed / 1000)}s / {round(COOLDOWN_MS / 1000)}s).')
        return

    if not data:
        print('The calendar has no entries at all, skipping recap.')
        put_json('meta/last_notified_edit_time', last_edit_time)
        return

    candidates = best_days(days, MIN_FREE_FOR_RECAP)
    total = len(candidates)

    if total == 0:
        send_webhook(AIKATAULU_WEBHOOK,
            f'*{last_editor} made some updates, go check it out!*\n\n{CALENDAR_LINK}')
        put_json('meta/last_notified_edit_time', last_edit_time)
        return

    list_text = format_list(candidates[:10])
    max_count = candidates[0]['free']

    if max_count < ANNOUNCE_THRESHOLD:
        send_webhook(AIKATAULU_WEBHOOK,
            f'*{last_editor} made some updates to the calendar!\n\n'
            f'Possible session days: {total}\n\n{list_text}*\n\n{CALENDAR_LINK}')

    if max_count >= ANNOUNCE_THRESHOLD:
        announced = get_json('announced') or {}
        new_date = next((d for d in candidates if d['free'] == max_count and not announced.get(d['key'])), None)
        if new_date:
            send_webhook(ANNOUNCE_WEBHOOK, f'{ANNOUNCEMENT_MESSAGE}\n\n{CALENDAR_LINK}')
            put_json(f"announced/{new_date['key']}", True)

    put_json('meta/last_notified_edit_time', last_edit_time)


def main():
    print('VERSION: check-py-1')
    data = get_json('data') or {}
    days = analyze_days(data)

    run_reminder(days)
    run_recap(days, data)


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(f'ERROR: {e}', file=sys.stderr)
        sys.exit(1)
