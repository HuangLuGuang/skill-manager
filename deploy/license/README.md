# Trusted License keys

The public key file `public-keys/5fa1304ab4aa7ed0.pem` matches the independent
`license-issuer` workstation created with this project. It is an Ed25519 public
key, not a signing credential. The private key stays in that workstation's
protected runtime directory and must never enter this repository or an offline package.

Trust is provisioned with the application, independently of imported licenses.
The file name is the first 16 hex characters of SHA-256 of the raw public key.
`AGENT_MANAGER_LICENSE_KEYS_DIR` may point to an operations-managed directory.
Keep the keys needed to verify all retained imported revisions when rotating.
Rebuild the backend image when changing its bundled trust keys.

See `docs/license.md` for deployment identity, issuance and enforcement.
