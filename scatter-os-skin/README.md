# Scatter OS Skin

The deepest layer of the reskin: boot, login, shell-greeting.
Everything above app-chrome is installed without sudo; these four
touch `/boot`, `/etc`, `/usr` so they need one `sudo` pass.

## Run

```
sudo bash ~/scatter-system/scatter-os-skin/install.sh            # skin only
sudo bash ~/scatter-system/scatter-os-skin/install.sh --hostname # + rename machine to "scatter"
```

Then:

```
sudo reboot
```

You will see:

- **GRUB menu** — black, `SCATTER — the alignment OS`, green highlight.
- **Plymouth** (boot splash) — HZL face `(◉.◉)` + SCATTER wordmark, green/amber progress dots on pure black. No Ubuntu logo.
- **TTY + SSH login banner** — Scatter greeting in `/etc/issue` and `/etc/motd`.
- (with `--hostname`) **terminal prompt** — `ryannlynnmurphy@scatter:~$` instead of the factory hostname.

## Undo

```
sudo update-alternatives --config default.plymouth   # pick ubuntu-logo
sudo sed -i 's|^GRUB_THEME=.*||' /etc/default/grub && sudo update-grub
sudo cp /etc/issue.scatter-backup /etc/issue
sudo cp /etc/motd.scatter-backup  /etc/motd
```

## Regenerate artwork

```
python3 ~/scatter-system/scatter-os-skin/generate_assets.py
```

## Not covered here (yet)

- **GDM greeter (the login screen wallpaper/widgets).** GNOME 46 on Ubuntu gates this behind the user-themes shell extension, so the clean path is installing `gnome-shell-extension-user-theme` and a matching `gnome-shell` theme — out of scope for this single-pass installer.
