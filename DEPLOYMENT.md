# Deploying to Production

This walks through putting the app on a real domain with HTTPS, on a $5-6/month
DigitalOcean VPS. Total time: 45-90 minutes the first time.

## What you'll end up with

```
Browser --HTTPS--> nginx --unix socket--> gunicorn (3 workers) --> Flask app --> SQLite
                     |
                     +-- serves /static/ files directly (faster than routing through Flask)
```

nginx handles incoming traffic and HTTPS certificates. gunicorn is the
production-grade server that actually runs your Flask app (never use
`python run.py` / the Flask dev server in production — it's not built for
real traffic and has no protection against crashes). systemd keeps
gunicorn running permanently and restarts it if it ever crashes or the
server reboots.

---

## Step 1 — Buy a domain

Any registrar works (Namecheap, Domain.com, a local Nigerian registrar).
A `.com` typically runs $8-15/year. You don't need anything else from the
registrar yet — just note your domain name.

## Step 2 — Create the VPS

1. Sign up at [digitalocean.com](https://www.digitalocean.com)
2. Create a Droplet:
   - Image: **Ubuntu 24.04 LTS**
   - Plan: Basic, **$6/month** (1GB RAM / 1 CPU is plenty for one school)
   - Choose a datacenter region close to Nigeria (London or Frankfurt are usually the lowest-latency options)
   - Authentication: SSH key (recommended) or password
3. Once created, note the Droplet's **public IP address**.

## Step 3 — Point your domain at the server

In your domain registrar's DNS settings, add two records:

| Type | Name | Value |
|---|---|---|
| A | @ | your Droplet's IP |
| A | www | your Droplet's IP |

DNS changes can take a few minutes to a few hours to take effect.

## Step 4 — Connect to the server and install dependencies

```bash
ssh root@YOUR_SERVER_IP

apt update && apt upgrade -y
apt install -y python3-venv python3-pip nginx sqlite3 certbot python3-certbot-nginx git
```

## Step 5 — Upload your project

From your own computer (not the server), zip your project and upload it,
or use `scp`:

```bash
# Run this on YOUR computer, not the server
scp -r school_management root@YOUR_SERVER_IP:/var/www/
```

Back on the server:

```bash
cd /var/www/school_management
mkdir -p logs backups
```

## Step 6 — Set up the Python environment

```bash
cd /var/www/school_management
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Step 7 — Configure production settings

```bash
cp .env.example .env
nano .env
```

Generate a real secret key and put it in `.env`:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Your `.env` should look like:

```
SECRET_KEY=<the long random string you just generated>
DATABASE_URL=sqlite:////var/www/school_management/school.db
```

(Note the **four** slashes for an absolute path with SQLite.)

## Step 8 — Create the database

```bash
python seed.py
```

This creates all tables and your first owner login. **Write down the
owner email/password it prints** — you'll need it to log in for the
first time, and you should change it immediately after.

## Step 9 — Test gunicorn directly (before wiring up nginx)

```bash
gunicorn --bind 0.0.0.0:8000 wsgi:app
```

Visit `http://YOUR_SERVER_IP:8000` in a browser. If you see the login
page, it's working — press `Ctrl+C` to stop it, then continue.

## Step 10 — Set up systemd (keeps the app running permanently)

```bash
cp deploy/school.service /etc/systemd/system/school.service
nano /etc/systemd/system/school.service
```

Double-check the paths and `User=www-data` line match your setup, then:

```bash
chown -R www-data:www-data /var/www/school_management
systemctl daemon-reload
systemctl enable school
systemctl start school
systemctl status school
```

You should see "active (running)". If not, check logs:

```bash
journalctl -u school -f
```

## Step 11 — Set up nginx

```bash
cp deploy/nginx.conf /etc/nginx/sites-available/school
nano /etc/nginx/sites-available/school
```

Replace `yourschooldomain.com` with your actual domain, then:

```bash
ln -s /etc/nginx/sites-available/school /etc/nginx/sites-enabled/
nginx -t          # should say "syntax is ok"
systemctl restart nginx
```

Visit `http://yourschooldomain.com` — you should see the app.

## Step 12 — Add HTTPS (free, via Let's Encrypt)

```bash
certbot --nginx -d yourschooldomain.com -d www.yourschooldomain.com
```

Follow the prompts (enter your email, agree to terms). Certbot
automatically edits your nginx config to redirect HTTP to HTTPS and sets
up auto-renewal. Visit `https://yourschooldomain.com` to confirm the
padlock shows.

## Step 13 — Set up the firewall

```bash
ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw enable
```

## Step 14 — Set up daily backups

```bash
chmod +x deploy/backup.sh
crontab -e
```

Add this line (backs up every night at 2am):

```
0 2 * * * /var/www/school_management/deploy/backup.sh >> /var/www/school_management/logs/backup.log 2>&1
```

**Important:** this backs up *on the same server*. It protects you from
a bad deploy or accidental data corruption, but not from the server
itself dying. Once you're comfortable, add a step to `backup.sh` that
copies backups somewhere else too (email them to yourself weekly, upload
to Google Drive/Dropbox, or use `rclone` — anything off-server).

---

## Deploying updates later

Whenever you have new files to push (like the ones I give you in this
chat):

```bash
# On your computer: upload the changed files
scp changed_file.py root@YOUR_SERVER_IP:/var/www/school_management/path/to/file.py

# On the server:
cd /var/www/school_management
source venv/bin/activate
pip install -r requirements.txt          # only if requirements.txt changed
python seed.py                           # only if a feature note says to re-seed
sudo systemctl restart school            # always do this last
```

## Quick troubleshooting

| Symptom | Check |
|---|---|
| "502 Bad Gateway" | `systemctl status school` — gunicorn probably isn't running. Check `journalctl -u school -f` |
| Changes don't show up | Did you run `systemctl restart school`? nginx doesn't need a restart for code changes, only gunicorn does |
| "This site can't be reached" | Check DNS has propagated: `dig yourschooldomain.com` should return your server IP |
| Static files (CSS) missing | Check the nginx `alias` path in Step 11 matches your actual project path |
