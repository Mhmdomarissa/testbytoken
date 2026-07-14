# Credentials & the vault pattern

The owner asked: "can users enter login details so we can test behind a login?"
The answer is **yes — but never the naive way.** This doc is the rule.

## What we will NEVER do
- No password field in the demo frontend.
- No credentials sent to the API in plaintext.
- No credentials written into the test trace, logs, or screenshots.
- The platform operator must never be able to see a customer's password.

Putting credentials in a chat box or a plain form *feels* easy and is the single
fastest way to lose customer trust (and to leak secrets). It also trains users into
an unsafe habit. We refuse it on purpose.

## What we WILL do (the real pattern, for later — not the demo)

1. **Vault, once.** A signed-in customer stores credentials in an encrypted,
   per-tenant secrets vault. Encryption key is per-tenant. The app stores
   ciphertext, never plaintext.
2. **Inject at runtime.** When a test needs to log in, the orchestrator pulls the
   secret and injects it into the **disposable container** as an environment
   variable, just for that run.
3. **Use, then destroy.** The browser logs in using the injected value. The value
   never enters the trace or any screenshot (mask the password field). The
   container — and the secret with it — is destroyed after the run.
4. **Operator-blind.** Build it so even you, the operator, can't read stored
   secrets. Decryption only happens inside the ephemeral runner.

## What to build in THIS demo

Just the **UI shell** of the safe flow, so users see the right pattern from day one:

- After signup, a "Connect a login to test behind auth" panel.
- Fields that *say* they go to a secure vault (lock iconography, "encrypted, never
  shown again" copy).
- On submit, **store nothing real** — just acknowledge and mark the connection as
  configured. A clear `// TODO: real vault` marker in the code.

Do not implement encryption, storage, or injection in the demo. The point is to
prove the journey and the trust posture, not to hold real secrets yet.
