# Free Demo Deployment (Render)

This gets the app live on a free `https://yourapp.onrender.com` URL you
can send to a school before you have a paid contract. No credit card,
no domain purchase needed.

**Important trade-off, know this going in:** Render's free tier has no
persistent disk and no shell access. That means your SQLite database can
be wiped on any restart or redeploy. Rather than fight that, this setup
leans into it — the app **automatically re-seeds a realistic demo
dataset every time it boots**, so it always looks freshly populated
instead of empty. This is perfect for demos, but **do not use this free
setup for a real paying customer's actual data** — for that, follow
`DEPLOYMENT.md` instead, which uses a proper server with real persistent
storage.

---

## Step 1 — Put your code on GitHub

If you haven't already:

```bash
cd school_management
git init
git add .
git commit -m "Initial commit"
```

Create a new repository on [github.com](https://github.com/new) (make it
private if you don't want the code public), then:

```bash
git remote add origin https://github.com/YOUR_USERNAME/school-management.git
git branch -M main
git push -u origin main
```

## Step 2 — Create the Render service

1. Sign up free at [render.com](https://render.com) (no card required)
2. Click **New +** -> **Web Service**
3. Connect your GitHub account and select the repository you just pushed
4. Configure:
   - **Name:** anything, e.g. `schoolname-demo`
   - **Region:** Frankfurt or London (closest to Nigeria)
   - **Branch:** `main`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn wsgi:app`
   - **Instance Type:** **Free**

## Step 3 — Set environment variables

Still on the same setup screen, scroll to **Environment Variables** and add:

| Key | Value |
|---|---|
| `SECRET_KEY` | any long random string, generate one locally with `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `AUTO_SEED` | `true` |
| `AUTO_SEED_DEMO` | `true` |

Click **Create Web Service**. Render will build and deploy, this takes
2-5 minutes the first time. When it's done, you'll get a URL like
`https://schoolname-demo.onrender.com`.

## Step 4 — Log in and check it worked

Open the URL. Check Render's **Logs** tab for a line like:

```
Demo data seeded:
  Admin      -> phone 08011110001 | password: Demo123!
  ...
```

Use those credentials to log in as owner, admin, accountant, teacher, a
parent, or a student and show off each dashboard. Full list of demo
logins is printed in the logs and repeated below.

---

## Demo login reference

| Role | Username | Password |
|---|---|---|
| Owner | `owner@school.com` | `ChangeMe123!` |
| Admin | `08011110001` | `Demo123!` |
| Accountant | `08011110002` | `Demo123!` |
| Teacher (Maths, JSS1A) | `08011110003` | `Demo123!` |
| Teacher (English, JSS1A) | `08011110004` | `Demo123!` |
| Parent (guardian of Aisha Bello) | `08022220001` | `Demo123!` |
| Student (Aisha Bello) | `STU/2026/0001` | `Student123!` |

The demo data includes 8 students across Nursery-to-SSS classes, fee
invoices in different payment states, results, an exam with sample
questions, a few days of attendance, and one **voided payment** already
sitting on the Reconciliation page, so you can show a school exactly how
the discrepancy-catching feature works without setting anything up live.

---

## Before you demo to a school: wake it up first

Render's free tier sleeps the app after 15 minutes with no traffic, and
the next visit takes 30-60 seconds to wake up. **Two or three minutes
before your call**, open the URL yourself once to wake it up, so the
school doesn't sit staring at a blank loading screen.

If you're doing demos often enough that this gets annoying, a free
[UptimeRobot](https://uptimerobot.com) monitor pinging your URL every 10
minutes will keep it awake during business hours, not required, just
convenient.

## Resetting the demo

Data persists across sleep/wake, but if you ever want a clean reset (or
Render's disk gets wiped), just restart the service from the Render
dashboard (Manual Deploy -> Deploy latest commit, or the Restart button).
`AUTO_SEED_DEMO` will run again, but it's idempotent, so if the demo
admin account already exists it just skips straight past and leaves your
data alone.

## Updating the demo with new features

```bash
git add .
git commit -m "describe what changed"
git push
```

Render auto-deploys on every push to `main`. No manual restart needed.

---

## When a school signs

Don't try to convert this same Render deployment into their real system,
the auto-seed behavior would wipe their actual data. Instead: follow
`DEPLOYMENT.md` to stand up a proper VPS with persistent storage, run
`python seed.py` (without `--demo`) for a clean base, and register that
school's real students, staff, and fees from scratch.
