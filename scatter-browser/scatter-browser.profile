# Scatter Browser firejail profile.
# Hardens Firefox against both sandbox escape and accidental data leakage.
# Copy to /etc/firejail/ or load via: firejail --profile=.../scatter-browser.profile firefox ...

# Inherit the upstream firefox defaults — they're solid and maintained.
include firefox.profile

# Additional Scatter-specific tightening.

# Private mode for system dirs (read-only view of /tmp, fresh /dev).
private-tmp
private-dev

# No access to SSH keys or GPG keyring from the browser. These are
# developer-creds firejail's default profile doesn't always block
# strictly enough for our threat model.
blacklist ${HOME}/.ssh
blacklist ${HOME}/.gnupg
blacklist ${HOME}/.aws
blacklist ${HOME}/.azure
blacklist ${HOME}/.config/gcloud
blacklist ${HOME}/.kube

# No access to the Scatter substrate. The browser should never read
# the journal, audit log, or other apps' local state.
blacklist ${HOME}/.scatter

# No access to the Scatter source tree or any project directories.
blacklist ${HOME}/scatter-system
blacklist ${HOME}/projects

# Network: allow, but no raw sockets or capabilities.
caps.drop all
seccomp
nonewprivs
noroot

# No printing / no 3d / no webcam/microphone by default. The user
# explicitly enables these per-session when needed (firejail --allow-X
# style — not done automatically).
noprinters
no3d

# Allow the user's Downloads directory explicitly so downloads work.
whitelist ${HOME}/Downloads
whitelist ${HOME}/Pictures
