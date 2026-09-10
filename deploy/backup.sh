#!/bin/bash
# Daily backup of the school database. Keeps the last 30 days locally.
#
# Set up as a cron job on the server (edit paths first):
#   crontab -e
#   0 2 * * * /var/www/school_management/deploy/backup.sh >> /var/www/school_management/logs/backup.log 2>&1
#
# This backs up LOCALLY on the same server, which protects against
# accidental data corruption or a bad deploy, but NOT against the server
# itself failing. For real protection, also copy backups off the server —
# e.g. add `rclone copy` or `scp` to another machine at the end of this
# script once you have somewhere to send them.

APP_DIR="/var/www/school_management"
DB_FILE="$APP_DIR/school.db"
BACKUP_DIR="$APP_DIR/backups"
DATE=$(date +%Y-%m-%d_%H-%M-%S)

mkdir -p "$BACKUP_DIR"
sqlite3 "$DB_FILE" ".backup '$BACKUP_DIR/school_$DATE.db'"

# Delete backups older than 30 days
find "$BACKUP_DIR" -name "school_*.db" -mtime +30 -delete

echo "Backup complete: school_$DATE.db"
