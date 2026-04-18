# scatter-backup

Encrypted snapshots of the Scatter substrate. Sovereignty needs backup — a single drive failure must not erase the thesis.

No external Python dependencies. Encryption via `openssl enc` (on every Ubuntu install). Archives via `tar + gzip` (ditto).

## What it backs up

By default:
- `~/.scatter/` — the substrate (journal, audit, watts, dialectical, sessions, config)
- `~/scatter-system/` — the code (also in git, but this snapshot includes local-only state)

Override via `~/.scatter/config.json`:

```json
{
  "backup": {
    "include": ["~/.scatter", "~/Documents/scatter-workspace", "~/projects/hazel"],
    "exclude": ["node_modules", ".next", "__pycache__"],
    "destination": "/media/ryann/ScatterBackup",
    "keep": 10
  }
}
```

Default destination: `~/scatter-backups/`. Change to an external drive mount when one is attached.

## Manual use

```bash
# Snapshot now (prompts for passphrase)
python3 ~/scatter-system/scatter-backup/backup.py run

# Or via env var for scripting
SCATTER_BACKUP_PASSPHRASE='...' python3 backup.py run

# Or via a file containing the passphrase on the first line
python3 backup.py run --passphrase-file ~/.scatter/backup-passphrase

# List snapshots
python3 backup.py list

# Restore one into a staging directory
python3 ~/scatter-system/scatter-backup/restore.py ~/scatter-backups/scatter-backup-20260417-123456.tar.gz.enc
# → files land in ~/scatter-restore-20260417-123456/ for inspection
```

## Automatic backups via systemd

Unit files in this directory:
- `scatter-backup.service` — runs the backup once
- `scatter-backup.timer`   — fires the service daily at 03:00

Install (user-level, no root required):

```bash
# 1. Write your passphrase to a protected file (one-time).
#    chmod enforces user-only read.
umask 077
printf '%s\n' "your long strong passphrase here" > ~/.scatter/backup-passphrase

# 2. Copy units into systemd's user config dir.
mkdir -p ~/.config/systemd/user
cp scatter-backup.service scatter-backup.timer ~/.config/systemd/user/

# 3. Enable and start the timer.
systemctl --user daemon-reload
systemctl --user enable --now scatter-backup.timer

# 4. Check status.
systemctl --user list-timers | grep scatter
systemctl --user status scatter-backup.service
```

To disable:

```bash
systemctl --user disable --now scatter-backup.timer
```

## Security notes

- Encryption: AES-256-CBC with PBKDF2 key derivation and random salt. `openssl enc` is the standard tool; the same command decrypts.
- Passphrase storage: `~/.scatter/backup-passphrase` is chmod 600 by the umask above. It lives on the same drive you're backing up — if the drive fails, you lose the passphrase too. **Store a copy of the passphrase off-machine** (printed on paper, in a password manager on your phone, wherever your threat model permits).
- The passphrase is NEVER logged to syslog or the journal. Only backup start/complete/fail metadata is.
- Backups to an external drive: mount the drive before running (or use automount + a `ConditionPathExists` stanza in the service file if you want silent skip-when-detached).

## Restore protocol (what to do when the laptop dies)

1. Get the snapshot file onto the new machine. If it was on external media, plug it in. If you pushed it off-site, pull it.
2. `python3 restore.py <path-to-.enc> --into ~/scatter-recovered/`
3. Inspect `~/scatter-recovered/` by hand. This is NOT automatic overwrite — you move the pieces into place.
4. Most critical: `cp -a ~/scatter-recovered/.scatter/* ~/.scatter/` brings the substrate back (journal, audit, watts, dialectical, config).
5. `~/scatter-recovered/scatter-system/` is redundant if you've pulled from git; otherwise copy it back.
6. Re-run `scatter-bootstrap` to reconfigure the new machine.

The thesis survives.
