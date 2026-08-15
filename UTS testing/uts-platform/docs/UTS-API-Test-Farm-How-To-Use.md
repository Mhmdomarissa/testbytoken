# UTS Platform — Working Guide (How to Use)

**Project path:** `D:\A\UTS-Test-Automation-Suite`  
**Web UI:** http://127.0.0.1:5050 (LAN: http://192.168.1.94:5050)  
**Default login:** `admin` / `admin123`

This document explains how to run the platform and use **API Test Farm** (direct API testing) and optional **UI automation projects**.

---

## 1. Start the platform

1. Open a terminal in `D:\A\UTS-Test-Automation-Suite`.
2. Run:
   - `RUN-WEB.bat`  
   - or `python run_web.py`
3. Open http://127.0.0.1:5050 in the browser.
4. Sign in with **Language**, **User Role** (Tester / Admin / Guest), username, and password.

After login you see:
- **Projects** — UI Selenium scan/generate/run (optional)
- **API Test Farm** — hit APIs, assert, chain login → next APIs (main focus)

---

## 2. API Test Farm (main tool)

Open: **API Test Farm** in the top bar, or http://127.0.0.1:5050/api-farm

### 2.1 What you can do

| Feature | Purpose |
|--------|---------|
| Send request | Live call any HTTP API |
| Auth presets | None / Bearer / Basic / API Key |
| Parameters | `{{var}}` placeholders |
| Timestamps | `{{timestamp}}`, `{{date}}`, `{{uuid}}`, etc. |
| Extractors | Save values from response (e.g. login token) |
| Operators | Assert with eq, contains, gt, … |
| Import | OpenAPI / Swagger / Postman JSON |
| POS/NEG | Auto positive & negative cases |
| Run all | Run suite in order + pie chart report |

---

## 3. Quick start (one API)

1. Open **API Test Farm**.
2. Method: `GET`
3. URL: `https://jsonplaceholder.typicode.com/posts/1`
4. Expected status: `200`
5. Click **Send request** → see PASS/FAIL and response body.
6. Click **Save to collection**.
7. Click **Run all saved APIs** → open report.

---

## 4. Parametrization (`{{var}}`)

### 4.1 Collection parameters

In **Parameters & timestamps**, save JSON, for example:

```json
{
  "baseUrl": "https://api.example.com",
  "username": "demo.user",
  "password": "Secret123"
}
```

Click **Save parameters**.

### 4.2 Use in requests

| Field | Example |
|-------|---------|
| URL | `{{baseUrl}}/api/login` |
| Body | `{"username":"{{username}}","password":"{{password}}"}` |
| Header | `{"Authorization":"Bearer {{token}}"}` |
| Bearer token | `{{token}}` |

### 4.3 Built-in timestamps (no setup)

| Placeholder | Meaning |
|-------------|---------|
| `{{timestamp}}` | Unix seconds |
| `{{timestamp_ms}}` | Unix milliseconds |
| `{{date}}` | `YYYY-MM-DD` |
| `{{datetime}}` | Local datetime |
| `{{datetime_utc}}` | UTC datetime |
| `{{uuid}}` / `{{guid}}` | Random UUID |

Example body:

```json
{
  "requestId": "{{uuid}}",
  "sentAt": "{{timestamp}}"
}
```

---

## 5. Auth presets

In **Auth preset**:

| Type | Use |
|------|-----|
| None | Public APIs |
| Bearer | Token APIs — paste JWT or use `{{token}}` |
| Basic | Username + password |
| API Key | Header name + value (e.g. `X-API-Key`) |

Auth is applied on **Send** and on **Run all**.

---

## 6. Operators (assertions)

In **Operator asserts (JSON array)**:

```json
[
  {"kind": "status", "operator": "eq", "expected": "200"},
  {"kind": "json_path", "path": "status", "operator": "eq", "expected": "success"},
  {"kind": "json_path", "path": "data.id", "operator": "gt", "expected": "0"},
  {"kind": "body", "operator": "contains", "expected": "token"}
]
```

### Supported operators

`eq`, `ne`, `contains`, `not_contains`, `gt`, `gte`, `lt`, `lte`, `regex`, `exists`, `not_exists`

### Kind values

| kind | Meaning |
|------|---------|
| `json_path` | JSON field path (`data.token`, `user.id`) |
| `status` | HTTP status code |
| `body` | Full response text |
| `header` | Response header (`path` = header name) |

You can also use **Assert body contains** for a simple text check.

---

## 7. Auto chain — Login API → next APIs (most important)

Goal: first call **Login**; on success, take token (or any field) and automatically use it in later APIs.

### Step A — Login request

1. Name: `Login`
2. Method: `POST`
3. URL: `{{baseUrl}}/auth/login` (or your real login URL)
4. Body example:

```json
{
  "username": "{{username}}",
  "password": "{{password}}"
}
```

5. **Extractors** (JSON array) — map response → variables:

```json
[
  {"name": "token", "path": "access_token", "source": "json"},
  {"name": "userId", "path": "user.id", "source": "json"}
]
```

- `name` = variable name used later as `{{token}}`
- `path` = JSON path in response (`access_token`, or `data.token` if nested)
- `source` = usually `json` (also `header` or `status`)

6. Save the request. Keep it **first** in the list (use ↑ ↓ if needed).

### Step B — Next API (uses login response)

1. Name: `Get Profile` (or Orders, etc.)
2. Auth: **Bearer** → token field: `{{token}}`  
   **or** Headers:

```json
{
  "Authorization": "Bearer {{token}}"
}
```

3. URL example: `{{baseUrl}}/users/{{userId}}`
4. Save.

### Step C — Run suite

1. Confirm order: **Login first**, then other APIs.
2. Click **Run all saved APIs**.
3. Engine runs in order:
   - Login → extracts `token`, `userId`
   - Next APIs resolve `{{token}}`, `{{userId}}` automatically
4. Open **Open last report** for pass/fail pie chart.

**Tip:** After a single **Send** on Login, extracted values also appear under the response and are saved into Parameters for the next manual Send.

---

## 8. Import OpenAPI / Postman

1. Section **Import OpenAPI / Postman**
2. Upload `.json` **or** paste JSON
3. Optional **Base URL override** (OpenAPI)
4. Click **Import into collection**
5. Edit extractors/auth as needed, then Run all

---

## 9. Positive / negative cases

- Per request: **+/-**
- Builder: **Save + POS/NEG**
- Header: **Generate POS/NEG for all**

Creates `[POS]` and `[NEG]` variants (invalid body / bad path / bad token).

---

## 10. UI automation projects (optional)

Separate from API Farm:

1. Dashboard → **New project** (app URL + credentials + optional role)
2. **Scan application** → discover modules
3. Select modules → **Discover flows & generate tests** or **Run full pipeline**
4. Console shows live step banners while automation runs
5. History → open HTML report (pie chart)

Use this for browser/Selenium flows. Use **API Test Farm** for HTTP APIs.

---

## 11. Reports & data locations

| Item | Location |
|------|----------|
| API HTML reports | `web-data/api-farm/reports/` |
| Latest API report | `web-data/api-farm/reports/latest-api-report.html` |
| Saved API collection | `web-data/api-farm/user-<id>.json` |
| UI automation reports | `reports/` and `web-data/projects/` |

---

## 12. Recommended workflow (API testing)

1. Start web server → login as **Tester**
2. Open **API Test Farm**
3. Save parameters (`baseUrl`, credentials)
4. Create **Login** with extractors (`token`)
5. Create business APIs using `{{token}}`
6. Reorder: Login = #1
7. **Run all saved APIs**
8. Review pie chart report
9. Optionally generate POS/NEG and re-run

---

## 13. Troubleshooting

| Problem | What to do |
|---------|------------|
| Page 500 / old UI | Restart `python run_web.py` (only one process on port 5050). Hard refresh Ctrl+F5 |
| `{{token}}` not replaced | Login must run first; check extractor `path` matches real JSON |
| Import fails | File must be OpenAPI/Swagger or Postman Collection v2 JSON |
| Auth fails | Check Bearer/Basic values; try Send alone before Run all |
| Cannot reach LAN URL | Use machine IP; firewall allow TCP 5050 |

---

## 14. Example: Login then Get User

**Parameters**

```json
{
  "baseUrl": "https://reqres.in/api"
}
```

**1) Login (or Register)**  
POST `{{baseUrl}}/login`  
Body: `{"email":"eve.holt@reqres.in","password":"cityslicka"}`  
Extractor: `[{"name":"token","path":"token","source":"json"}]`

**2) Next call**  
GET `{{baseUrl}}/users/2`  
Header / Bearer: `{{token}}` (if API requires it)

**Run all** → Login extracts token → second request uses it.

*(Replace URLs/fields with your real APIs.)*

---

*Document version: UTS API Test Farm working guide — parametrization, operators, timestamps, response chaining.*
