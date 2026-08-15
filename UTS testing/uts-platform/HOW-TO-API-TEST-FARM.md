# UTS API Test Farm — How to Use

Working guide for the **UTS API Test Farm**: build requests, parametrize, assert with operators, use timestamps, and chain login responses into the next APIs.

---

## 1. Start the platform

1. Open a terminal in `D:\A\UTS-Test-Automation-Suite`.
2. Run `RUN-WEB.bat` (or `python run_web.py`).
3. Open in browser:
   - Local: http://127.0.0.1:5050  
   - Network: http://192.168.1.94:5050  

**Login**

| Field | Example |
|--------|---------|
| Language | English |
| User Role | Tester / Admin / Guest |
| Username | `admin` |
| Password | `admin123` |

After login, click **API Test Farm** in the top bar (or open http://127.0.0.1:5050/api-farm).

---

## 2. Screen overview

| Area | Purpose |
|------|---------|
| **Parameters & timestamps** | Collection variables for `{{var}}` placeholders |
| **Import OpenAPI / Postman** | Load APIs from Swagger/OpenAPI or Postman JSON |
| **Request builder** | Method, URL, auth, headers, body, extractors, operators |
| **Live response** | Status, time, body, extracted values |
| **Saved API tests** | Ordered list — **run order = chain order** |

---

## 3. Send a simple request (quick start)

1. **Name:** e.g. `Get post`
2. **Method:** `GET`
3. **URL:** `https://jsonplaceholder.typicode.com/posts/1`
4. **Expected status:** `200`
5. Click **Send request**
6. Check **Live response** for PASS/FAIL and body
7. Click **Save to collection** to keep it

---

## 4. Parametrization (`{{var}}`)

### Collection variables

In **Parameters & timestamps**, save JSON, then click **Save parameters**:

```json
{
  "baseUrl": "https://api.example.com",
  "username": "demo",
  "password": "secret"
}
```

### Use in requests

| Place | Example |
|--------|---------|
| URL | `{{baseUrl}}/login` |
| Body | `{"username":"{{username}}","password":"{{password}}"}` |
| Header | `{"Authorization":"Bearer {{token}}"}` |
| Bearer token field | `{{token}}` |

Variables are replaced when you **Send** or **Run all saved APIs**.

---

## 5. Timestamps & built-in values

No setup needed — use these placeholders anywhere (URL / body / headers / auth):

| Placeholder | Meaning |
|-------------|---------|
| `{{timestamp}}` | Unix seconds |
| `{{timestamp_ms}}` | Unix milliseconds |
| `{{date}}` | `YYYY-MM-DD` |
| `{{datetime}}` | Local ISO-like datetime |
| `{{datetime_utc}}` | UTC datetime with `Z` |
| `{{uuid}}` / `{{guid}}` | Random UUID |

**Example body:**

```json
{
  "requestId": "{{uuid}}",
  "sentAt": "{{timestamp_ms}}"
}
```

---

## 6. Auth presets

In **Auth preset**:

| Type | Use |
|------|-----|
| None | No auth header |
| Bearer Token | `Authorization: Bearer …` (supports `{{token}}`) |
| Basic Auth | Username + password → Basic header |
| API Key header | Custom header name + value |

You can also put auth in **Headers (JSON)** manually.

---

## 7. Operators (assertions)

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

| Operator | Meaning |
|----------|---------|
| `eq` | Equals |
| `ne` | Not equals |
| `contains` | Text/string contains |
| `not_contains` | Does not contain |
| `gt` / `gte` | Greater than / ≥ (numeric) |
| `lt` / `lte` | Less than / ≤ (numeric) |
| `regex` | Regular expression match |
| `exists` / `not_exists` | Value present / empty |

### `kind` values

- `status` — HTTP status code  
- `json_path` — JSON field (`data.token`, `user.id`, `items[0].id`)  
- `body` — Full response text  
- `header` — Response header (`path` = header name)  

Optional: **Assert body contains** for a simple text check.

---

## 8. Auto chain — login response → next APIs

This is the main “first login API, then pass token to other APIs” flow.

### Step A — Create Login API (run first)

1. Method `POST`, URL e.g. `{{baseUrl}}/auth/login`
2. Body with credentials
3. Expected status `200` (or `201`)
4. **Extractors (JSON array)** — save values from the response:

```json
[
  {"name": "token", "path": "access_token", "source": "json"},
  {"name": "userId", "path": "user.id", "source": "json"}
]
```

| Field | Meaning |
|--------|---------|
| `name` | Variable name used later as `{{token}}` |
| `path` | JSON path in response (`access_token`, `data.token`, `user.id`) |
| `source` | `json` (default), `header`, `status`, or `body` |

5. **Save to collection**
6. Keep this request **#1** in the list (use **↑** if needed)

### Step B — Create second API (uses login values)

1. Method e.g. `GET`, URL `{{baseUrl}}/users/{{userId}}`
2. Auth → **Bearer Token** → `{{token}}`  
   **or** header:
   ```json
   {"Authorization": "Bearer {{token}}"}
   ```
3. Save — place it **after** login (order #2, #3, …)

### Step C — Run the chain

1. Confirm order: Login first, then dependent APIs (**↑ / ↓**)
2. Click **Run all saved APIs**
3. Open **Open last report** for pass/fail pie chart and extracted values

**Live test tip:** Send Login alone first — under Live response you should see **Extracted for next APIs**. Those values are stored and reused by later Send / Run.

---

## 9. Import OpenAPI / Postman

1. Upload a `.json` file **or** paste JSON  
2. Optional: **Base URL override** for OpenAPI  
3. Click **Import into collection**  
4. Edit extractors / auth / order as needed  

Supported:

- OpenAPI 3 / Swagger 2  
- Postman Collection v2.x  

---

## 10. Positive / negative auto cases

| Action | Result |
|--------|--------|
| **+/-** on a row | Adds `[POS]` and `[NEG]` variants for that request |
| **Save + POS/NEG** | Saves current builder request, then generates POS/NEG |
| **Generate POS/NEG for all** | Expands the whole collection |

Negative cases typically use invalid body / bad path / bad token and expect 4xx.

---

## 11. Typical end-to-end checklist

1. Login to UTS → open **API Test Farm**  
2. Set **Parameters** (`baseUrl`, etc.) → Save  
3. Create **Login** request + **extractors** for `token` → Save  
4. Create **Get Profile** (or any API) with `{{token}}` → Save  
5. Order list: Login = #1, others after  
6. **Run all saved APIs**  
7. Open report → confirm PASS and chained values  

---

## 12. Where data is stored

| Item | Location |
|------|----------|
| Your API collection | `web-data/api-farm/user-<id>.json` |
| Suite HTML reports | `web-data/api-farm/reports/` |
| Latest report | `web-data/api-farm/reports/latest-api-report.html` |

---

## 13. Troubleshooting

| Problem | What to check |
|---------|----------------|
| `{{token}}` not replaced | Login extractor `path` must match real JSON; Login must run first and PASS |
| 401 on second API | Token path wrong, or Bearer not set to `{{token}}` |
| Wrong API order | Use ↑ ↓ so Login is #1 |
| Import fails | Valid OpenAPI/Postman JSON; try Base URL override |
| Page looks old | Hard refresh **Ctrl+F5** after server restart |
| Server not reachable | Run `RUN-WEB.bat`; confirm port **5050** |

---

## 14. UI automation projects (separate from API Farm)

UTS also has **UI Selenium** projects (scan app → modules → generate/run browser tests):

1. Dashboard → **New project** (application URL + credentials)  
2. **Scan application** → select modules  
3. **Discover flows & generate tests** or **Run full pipeline**  
4. Watch **console** for live step banners during execution  

API Farm and UI projects share the same login; they are different workflows.

---

*Document version: aligned with UTS API Test Farm features (parametrization, operators, timestamps, response chaining).*
