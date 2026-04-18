# Scatter Browser

Firefox with a locked, hardened profile, launched inside a firejail bubble. The web, in your own bubble.

## Threat model

Defends against: telemetry, phone-home services, drive-by fingerprinting, and accidental data leakage from the browser into other parts of your machine. Does NOT defend against a rooted adversary or sophisticated forensic recovery (see the main README for the full threat model statement).

## What it does

- **Locked Firefox profile** at `~/.scatter/firefox-profile/` with `user.js` copied from this directory on every launch. Disables telemetry, safe-browsing phone-home, Pocket, Firefox Accounts, studies/experiments, DNS prefetch, search suggestions, geolocation API, WebRTC IP leakage. DNS-over-HTTPS to Cloudflare (change in user.js if you prefer a different resolver). HTTPS-only mode on.
- **firejail sandbox** via `scatter-browser.profile`. Inherits the upstream `firefox.profile` (maintained) and adds Scatter-specific blacklists: `~/.ssh`, `~/.gnupg`, `~/.aws`, `~/.config/gcloud`, `~/.scatter`, `~/scatter-system`, `~/projects` — none of which the browser has any business reading.
- **Journal on launch** via scatter_core (the only scatter-centric trace; no site-visit tracking).

## Launch

Via the app menu: click **Scatter Browser**.
Via the terminal: `~/scatter-system/scatter-browser/launcher.sh`

## Installation (one-time, needs sudo)

```bash
# Install firejail if not present
sudo apt install firejail

# Optional: place the Scatter firejail profile system-wide so it's
# auto-detected by firejail. (The launcher.sh --profile= flag works
# without this step.)
sudo cp ~/scatter-system/scatter-browser/scatter-browser.profile /etc/firejail/

# The Scatter launcher copies user.js to the profile dir on every
# launch, so edits to scatter-browser/profile/user.js take effect
# after restart.
```

## Relationship to `scatter wrap` firefox entry

`scatter wrap --all` creates a generic `scatter-firefox` desktop entry that uses firejail's default profile with Firefox defaults. **Scatter Browser** (this directory) is the dedicated, hardened variant with the locked user.js and the scatter-browser firejail profile. When Ryann runs `scatter-bootstrap --apply-sudo`, the bootstrap promotes Scatter Browser over the generic wrap by writing a dedicated `.desktop` entry pointing at `launcher.sh`.

## Adjusting hardening

Every setting in `profile/user.js` has a comment explaining what it does. Comment out any line to revert to Firefox's default. To tighten further, read the Arkenfox `user.js` (external project) — it maintains an aggressive baseline Scatter's subset is consistent with but doesn't fully implement.
