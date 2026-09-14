// ============================================================
// SESSION SCHEDULER — CHECK SCRIPT
// Node.js version — same logic as check.py, useful for
// GitHub Actions or any environment with Node instead of Python.
// ============================================================

// ============================================================
// CUSTOMIZE THESE VALUES
// ============================================================

// Your Firebase Realtime Database URL (same project as calendar.html)
const FIREBASE_URL = 'https://YOUR_PROJECT_ID-default-rtdb.YOUR_REGION.firebasedatabase.app';

// The public URL where the calendar is hosted (e.g. your Netlify site)
const CALENDAR_LINK = 'https://YOUR_SITE.netlify.app/';

// How long to wait after the last edit before sending a recap
const COOLDOWN_MS = 15 * 60 * 1000;

// How often the "please mark your availability" reminder repeats
const REMINDER_INTERVAL_MS = 3 * 24 * 60 * 60 * 1000;

// Minimum number of people free on a day for it to count as a candidate
const MIN_FREE_FOR_RECAP = 4;

// Minimum number of people free for a day to trigger the big
// "we found a date!" announcement (separate channel, one-time per date)
const ANNOUNCE_THRESHOLD = 6;

// The big announcement message — write your own here
const ANNOUNCEMENT_MESSAGE = "Heads up — we found a shared session date! Time to get the party together.";

// ============================================================

const SCHEDULE_WEBHOOK = process.env.DISCORD_WEBHOOK_SCHEDULE;
const ANNOUNCE_WEBHOOK = process.env.DISCORD_WEBHOOK_ANNOUNCE;

function formatDate(key){
  const [y, m, d] = key.split('-');
  return `${d}.${m}.${y}`;
}

function todayKey(){
  return new Date().toISOString().slice(0, 10);
}

async function getJSON(path){
  const res = await fetch(`${FIREBASE_URL}/${path}.json`, {
    headers: { 'User-Agent': 'SessionScheduler/1.0 (cron script)' }
  });
  return await res.json();
}

async function putJSON(path, value){
  await fetch(`${FIREBASE_URL}/${path}.json`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', 'User-Agent': 'SessionScheduler/1.0 (cron script)' },
    body: JSON.stringify(value)
  });
}

async function sendWebhook(url, content){
  if(!url){
    console.log('ERROR: webhook URL is missing (env var is empty or misnamed).');
    return;
  }
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'User-Agent': 'SessionScheduler/1.0 (cron script)' },
    body: JSON.stringify({ content })
  });
  if(!res.ok){
    const text = await res.text();
    console.log(`ERROR: Discord rejected the message. Status ${res.status}: ${text}`);
  } else {
    console.log('Webhook sent successfully.');
  }
}

// Note: Firebase silently turns sequential numeric keys (e.g. "1","2","3")
// into a JSON array instead of an object — Object.values() handles both
// shapes fine in JavaScript, so no special-casing is needed here.
function analyzeDays(data){
  const today = todayKey();
  return Object.keys(data)
    .filter(key => key >= today)
    .map(key => {
      const values = Object.values(data[key]);
      return {
        key,
        free: values.filter(v => v === 'free').length,
        busy: values.filter(v => v === 'busy').length
      };
    });
}

function bestDays(days, minFree){
  return days
    .filter(d => d.free >= minFree && d.busy === 0)
    .sort((a, b) => b.free - a.free);
}

function formatList(days){
  if(!days.length) return null;
  return days.map(d => `${formatDate(d.key)} — ${d.free} players`).join('\n');
}

async function runReminder(days){
  const maxFree = days.reduce((max, d) => (d.busy === 0 ? Math.max(max, d.free) : max), 0);
  if(maxFree >= ANNOUNCE_THRESHOLD){
    console.log('No reminder needed, a suitable date has already been found.');
    return;
  }

  const today = todayKey();
  const announced = (await getJSON('announced')) || {};
  const pastSessions = Object.keys(announced).filter(key => key < today).sort();

  if(pastSessions.length){
    const lastSession = pastSessions[pastSessions.length - 1];
    const daysSince = (Date.now() - new Date(lastSession + 'T00:00:00Z').getTime()) / (24 * 60 * 60 * 1000);
    if(daysSince < 3){
      console.log(`Less than 3 days since the last session (${lastSession}), staying quiet for now.`);
      return;
    }
  }

  const lastReminder = await getJSON('meta/last_reminder_time');
  const now = Date.now();
  if(lastReminder && (now - lastReminder) < REMINDER_INTERVAL_MS){
    console.log(`Last reminder was ${Math.round((now - lastReminder) / 3600000)}h ago, not due yet.`);
    return;
  }

  const message = 'Reminder: mark your availability in the calendar so we can find a shared session date!';
  await sendWebhook(SCHEDULE_WEBHOOK, `*${message}*\n\n${CALENDAR_LINK}`);
  await putJSON('meta/last_reminder_time', now);
}

async function runRecap(days, data){
  const lastEditTime = await getJSON('meta/last_edit_time');
  const lastEditor = await getJSON('meta/last_editor');
  const lastNotified = await getJSON('meta/last_notified_edit_time');

  if(!lastEditTime){ console.log('No edits yet.'); return; }
  if(lastNotified === lastEditTime){ console.log('This edit has already been reported.'); return; }

  const elapsed = Date.now() - lastEditTime;
  if(elapsed < COOLDOWN_MS){
    console.log(`Cooldown in progress (${Math.round(elapsed / 1000)}s / ${Math.round(COOLDOWN_MS / 1000)}s).`);
    return;
  }

  if(Object.keys(data).length === 0){
    console.log('The calendar has no entries at all, skipping recap.');
    await putJSON('meta/last_notified_edit_time', lastEditTime);
    return;
  }

  const candidates = bestDays(days, MIN_FREE_FOR_RECAP);
  const total = candidates.length;

  if(total === 0){
    await sendWebhook(SCHEDULE_WEBHOOK,
      `*${lastEditor} made some updates, go check it out!*\n\n${CALENDAR_LINK}`);
    await putJSON('meta/last_notified_edit_time', lastEditTime);
    return;
  }

  const listText = formatList(candidates.slice(0, 10));
  const maxCount = candidates[0].free;

  if(maxCount < ANNOUNCE_THRESHOLD){
    await sendWebhook(SCHEDULE_WEBHOOK,
      `*${lastEditor} made some updates to the calendar!\n\n` +
      `Possible session days: ${total}\n\n${listText}*\n\n${CALENDAR_LINK}`);
  }

  if(maxCount >= ANNOUNCE_THRESHOLD){
    const announced = (await getJSON('announced')) || {};
    const newDate = candidates.find(d => d.free === maxCount && !announced[d.key]);
    if(newDate){
      await sendWebhook(ANNOUNCE_WEBHOOK, `${ANNOUNCEMENT_MESSAGE}\n\n${CALENDAR_LINK}`);
      await putJSON(`announced/${newDate.key}`, true);
    }
  }

  await putJSON('meta/last_notified_edit_time', lastEditTime);
}

async function main(){
  console.log('VERSION: check-js-1');
  const data = (await getJSON('data')) || {};
  const days = analyzeDays(data);

  await runReminder(days);
  await runRecap(days, data);
}

main().catch(err => { console.error(err); process.exit(1); });
