# UTS User Guide — JackTest

**For:** Jack (login: `JackTest`)  
**UTS URL:** [http://144.91.113.113:5050](http://144.91.113.113:5050)  
**Purpose:** How to run Scan / Generate / Automation on **your PC** or on the **UTS server**

---

## 1. Login

1. Open [http://144.91.113.113:5050/login](http://144.91.113.113:5050/login)
2. Enter:

| Field | Value |
|--------|--------|
| Username | `JackTest` |
| Password | `C!sco@123` |

3. Click **Login**

You land on **Projects**. Your role is **Tester** — you can **view** projects and **Scan / Run**. You cannot create or delete projects.

---

## 2. Choose where the browser opens

On every project page you see:

**Where should the browser run?**

| Option | What happens |
|--------|----------------|
| **My PC (local)** | Chrome/Edge opens on **Jack’s laptop** |
| **Server** | Browser opens on the **UTS server** (`144.91.113.113`) — not on your screen |

Pick one **before** you click Scan / Generate / Run.

---

## Option A — Run on Jack’s machine (local)

Use this when you want to **see the browser** on your desk (login screens, clicks, errors).

### A1. One-time: connect your PC

1. Login as `JackTest`
2. Open any project (or Dashboard)
3. If you see **Worker not connected**, download the connector:
   - **Windows:** click **Windows (.bat)**
   - **Mac:** click **Mac (.sh)**
4. Run the downloaded file:

**Windows**
- Double-click `UTS-Connect-JackTest.bat` (or similar name)
- Keep the black window open

**Mac**
```bash
chmod +x ~/Downloads/UTS-Connect-*.sh
~/Downloads/UTS-Connect-*.sh
```
- Keep Terminal open

5. Refresh the UTS page in the browser  
6. You should see a green pill: **Worker · &lt;your-pc-name&gt;**

> Tip: Leave the worker window running while you work. If you close it, local runs will fail until you start it again.

### A2. Run a scan / tests on your PC

1. Open the project (example: [Projects](http://144.91.113.113:5050/dashboard))
2. Select **My PC (local)**
3. Click one of:
   - **Scan application** — opens browser, discovers modules
   - **AI understand & generate** — after modules exist
   - **Run automation** / **Run full pipeline** — runs selected cases
4. Watch Chrome/Edge open **on your PC**
5. Use **Stop** if you need to cancel and close the browser

### A3. Checklist (local)

- [ ] Logged in as `JackTest`
- [ ] Worker window is open and green **Worker · …** shows
- [ ] **My PC (local)** is selected
- [ ] Chrome or Edge is installed on your PC
- [ ] App URL is reachable from your PC (VPN if needed)

---

## Option B — Run on the server machine

Use this when you do **not** need to watch the browser, or your PC cannot open the app.

### B1. Steps

1. Login as `JackTest`
2. Open the project
3. Select **Server**
4. Click **Scan application** / **Generate** / **Run**
5. Browser runs on the UTS server (you will **not** see it on your laptop)
6. Wait for the job banner to finish, then open **History & reports**

### B2. Checklist (server)

- [ ] Logged in as `JackTest`
- [ ] **Server** is selected (no worker required)
- [ ] App URL is reachable **from the UTS server** (firewall/VPN on server side)

---

## 3. Typical day for Jack (recommended)

```
Login → Connect worker (once per day) → Open project
     → My PC (local) → Scan application
     → Select modules → AI generate
     → Select test cases → Run automation
     → Open report
```

If worker is offline or you are remote without VPN to the app:

```
Login → Open project → Server → Scan / Run → Check report
```

---

## 4. What each button does

| Button | Result |
|--------|--------|
| **Scan application** | Opens browser, finds modules/pages |
| **AI understand & generate** | Builds test cases / objects / BDD from selected modules |
| **Run automation** | Runs selected test cases in the browser |
| **Run full pipeline** | Generate + execute + report in one go |
| **Stop** | Stops the job and closes the automation browser |

---

## 5. Common problems

| Problem | Fix |
|---------|-----|
| “Worker not connected” / local fails | Download connector again, run it, keep window open, refresh page |
| Browser opens on server, not my PC | You selected **Server** — switch to **My PC (local)** |
| Job stuck / browser frozen | Click **Stop**, then retry |
| Cannot login to app under test | Check username/password on **Edit project** (ask Admin if you cannot edit) |
| Mac: script not executable | Run `chmod +x` then execute the `.sh` file |
| Windows: SmartScreen blocks `.bat` | Click More info → Run anyway |

---

## 6. Security notes for Jack

- Do not share `JackTest` / `C!sco@123` outside the team
- Change password with Admin if this account is shared beyond Jack
- Worker installer contains your login token for **your** machine only — do not email the `.bat`/`.sh` to others

---

## 7. Quick reference

| Item | Value |
|------|--------|
| UTS portal | http://144.91.113.113:5050 |
| Username | JackTest |
| Password | C!sco@123 |
| Role | Tester (scan & run) |
| Local run | My PC (local) + worker connector |
| Server run | Server (no connector needed) |

---

*UTS Test Automation Suite — user guide for JackTest*  
*Last updated: August 2026*
