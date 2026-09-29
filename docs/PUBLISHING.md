# Preparing a public release

This tree was assembled from selected sources, not copied from a live working
directory. It excludes personal configuration, keys, passwords, tokens, SSIDs,
home-network/radio identities, SSH keys, flash/NVS backups and raw captures.
The experimental key-transfer receiver, key export and installation-specific
authentication witness were removed from the firmware.

The Overkiz CA PEM is a public verification certificate, not a private key.
Tests use dummy tokens, documentation addresses and anonymized payloads. The
AES self-test uses the public zero-key known-answer vector; it is never used
to authenticate commands to motors.

The initial public source tree passed a standalone firmware build, 28 isolated
HA tests and native C++ tests. Publication checks compare the public texts with
known local credentials without printing those credentials. Build cache and
private validation artifacts stay outside the public tree.

Before publishing changes:

```sh
python tools/check_public_tree.py
git status --short
git add .
git diff --cached
# Commit and push only after reviewing the staged contents.
```

The upstream repository is [HA_Somfy](https://github.com/jstepnicka81/HA_Somfy).
`.gitignore` excludes private/, .env, builds and backups, but does not protect
files that are already tracked. Pattern checks cannot detect every future
mistake. Review the complete staged diff, including documentation examples.
Never replace a placeholder in public documentation with an actual credential.
