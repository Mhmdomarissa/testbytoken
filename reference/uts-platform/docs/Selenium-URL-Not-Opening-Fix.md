# Selenium Script – Client Machine URL Not Opening (ERR_NAME_NOT_RESOLVED) – Fix Document

**Issue:** On the client machine, when the Selenium script runs, the browser opens but the application URL does not load.
Error seen: `unknown error: net::ERR_NAME_NOT_RESOLVED` / `SmartScreenDnsResolver ... DidTimeOut`.

**Root cause:** This is a **DNS / name-resolution problem on the client machine**, not a browser or Selenium code problem.
The browser (Edge) launches fine — the failure happens when it tries to translate the hostname into an IP address.

URL in question:
`https://uat-svb.uat.rosa-uat-de-aws-west1.zurich.cpm`

Note the domain ends in **`.cpm`** — this is not a valid domain. The correct domain is **`.com`**.

---

## Step-by-Step Solution

### Step 1 – Correct the URL spelling
Open `config/app-input.json` on the client machine and fix the domain from `.cpm` to `.com`:

```json
{
  "url": "https://uat-svb.uat.rosa-uat-de-aws-west1.zurich.com/applications/svb"
}
```

Also set the browser to match what the client is using (log shows Edge):

```json
{
  "browser": "edge"
}
```

In most cases the URL opens after just this step.

---

### Step 2 – Confirm VPN is connected, then clear DNS cache
Internal UAT hosts only resolve on the corporate network.
Connect the VPN, then run in PowerShell:

```powershell
ipconfig /flushdns
nslookup uat-svb.uat.rosa-uat-de-aws-west1.zurich.com
```

- If `nslookup` returns an IP → run the Selenium script, it will work.
- If it says "Non-existent domain" even on VPN → the hostname is retired; ask the infra team for the current UAT hostname.

---

### Step 3 – If manual browser opens the URL but Selenium does not
This is the most common case. Selenium launches the browser with a fresh temporary profile that enables Secure DNS and ignores the corporate proxy, so internal hostnames fail even though the same URL works when opened manually.

Fix already applied in the automation code (Secure DNS is now disabled automatically).
For the proxy, get the PAC URL from the working browser (`edge://net-internals/#proxy`) and add it to `config/selenium.json`:

```json
{
  "proxy_pac_url": "http://pac.zurich.com/proxy.pac"
}
```

---

### Step 4 – Guaranteed fallback: run against the client's real browser profile
If Step 3 is not enough, point the automation at the client's actual Edge profile so it inherits all proxy, certificate, and DNS settings from the working browser.

In `config/selenium.json`:

```json
{
  "user_data_dir": "C:\\Users\\<client-username>\\AppData\\Local\\Microsoft\\Edge\\User Data",
  "profile_directory": "Default"
}
```

**Important:** Close all Edge windows before running, otherwise the driver cannot attach to the locked profile.

---

## Summary
1. Fix `.cpm` → `.com` in `config/app-input.json`.
2. Ensure VPN is connected and flush DNS.
3. Selenium code now auto-disables Secure DNS; add proxy PAC URL if needed.
4. Fallback: run against the client's real Edge profile.

The code changes are in `automation/selenium_session.py` and `config/selenium.json`. All new settings default to off/empty, so existing runs are unaffected.
