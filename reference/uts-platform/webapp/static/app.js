const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || "";

// Add CSRF protection to every HTML form without duplicating hidden fields in templates.
document.querySelectorAll("form[method]").forEach((form) => {
  if ((form.method || "").toUpperCase() === "GET") return;
  let input = form.querySelector('input[name="_csrf_token"]');
  if (!input) {
    input = document.createElement("input");
    input.type = "hidden";
    input.name = "_csrf_token";
    form.appendChild(input);
  }
  input.value = csrfToken;
});

// Copy project "run location" choice into Scan / Generate / Execute forms.
function syncRunLocationToForm(form) {
  const choice = document.querySelector('input[name="run_location_choice"]:checked')?.value;
  if (!choice) return;
  let input = form.querySelector('input[name="run_location"]');
  if (!input) {
    input = document.createElement("input");
    input.type = "hidden";
    input.name = "run_location";
    form.appendChild(input);
  }
  input.value = choice;
}

document.querySelectorAll("form[data-run-location-sync]").forEach((form) => {
  form.addEventListener("submit", () => syncRunLocationToForm(form));
});

// Add CSRF protection to same-origin JavaScript mutations.
const nativeFetch = window.fetch.bind(window);
window.fetch = (resource, options = {}) => {
  const method = (options.method || "GET").toUpperCase();
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
    options.headers = new Headers(options.headers || {});
    options.headers.set("X-CSRF-Token", csrfToken);
  }
  return nativeFetch(resource, options);
};

document.querySelectorAll("[data-dialog-open]").forEach((button) => {
  button.addEventListener("click", () => {
    document.getElementById(button.dataset.dialogOpen)?.showModal();
  });
});

document.querySelectorAll("[data-dialog-close]").forEach((button) => {
  button.addEventListener("click", () => button.closest("dialog")?.close());
});

document.querySelectorAll("[data-tabs]").forEach((tabs) => {
  tabs.querySelectorAll("[data-tab]").forEach((button) => {
    button.addEventListener("click", () => {
      tabs.querySelectorAll("[data-tab]").forEach((item) => item.classList.remove("active"));
      document.querySelectorAll("[data-panel]").forEach((item) => item.classList.remove("active"));
      button.classList.add("active");
      document.querySelector(`[data-panel="${button.dataset.tab}"]`)?.classList.add("active");
    });
  });
});

document.querySelectorAll("[data-select-all]").forEach((button) => {
  button.addEventListener("click", () => {
    button.closest("form")?.querySelectorAll("[data-check-group] input[type=checkbox]")
      .forEach((input) => { input.checked = true; });
  });
});

document.querySelectorAll("[data-deselect-all]").forEach((button) => {
  button.addEventListener("click", () => {
    button.closest("form")?.querySelectorAll("[data-check-group] input[type=checkbox]")
      .forEach((input) => { input.checked = false; });
  });
});

document.querySelectorAll("[data-module-select-all]").forEach((button) => {
  button.addEventListener("click", () => {
    const group = button.closest(".testcase-module-group");
    const checkboxes = group?.querySelectorAll("input[type=checkbox][name='test_case_ids']");
    if (!checkboxes?.length) return;
    const allChecked = [...checkboxes].every((input) => input.checked);
    checkboxes.forEach((input) => { input.checked = !allChecked; });
    button.textContent = allChecked ? "Select all" : "Deselect all";
  });
});

document.querySelectorAll("[data-permission-all]").forEach((button) => {
  button.addEventListener("click", () => {
    const checked = button.dataset.permissionAll === "on";
    button.closest("form")?.querySelectorAll(".permission-table input[type=checkbox]:not(:disabled)")
      .forEach((input) => { input.checked = checked; });
  });
});

function pollJob(element, endpoint) {
  const text = element.querySelector("p");
  const spinner = element.querySelector(".spinner");
  const strong = element.querySelector("strong");
  const isExecution = endpoint.includes("/executions/");
  const timer = setInterval(async () => {
    try {
      const response = await fetch(endpoint, { headers: { Accept: "application/json" } });
      if (!response.ok) return;
      const data = await response.json();
      if (data.current_step) {
        text.textContent = data.current_step;
        if (isExecution && strong && data.status === "RUNNING") {
          strong.textContent = "Executing step…";
        }
      } else {
        text.textContent = data.message || data.status;
      }
      const complete = ["COMPLETED", "FAILED", "PASSED", "STOPPED"].includes(data.status);
      if (complete) {
        clearInterval(timer);
        spinner?.remove();
        element.querySelector("[data-stop-project]")?.remove();
        if (strong) strong.textContent = data.status;
        if (data.status === "STOPPED") {
          text.textContent = data.message || "Stopped by user";
        }
        if (data.passed !== undefined && data.failed !== undefined && data.status !== "STOPPED") {
          const summary = document.createElement("p");
          summary.textContent = `${data.passed} passed · ${data.failed} failed · ${data.total || 0} total`;
          element.querySelector(".job-banner-body, div")?.appendChild(summary);
          if (data.report_url) {
            const link = document.createElement("a");
            link.href = data.report_url;
            link.target = "_blank";
            link.textContent = "Open report with pie chart";
            link.style.marginLeft = "12px";
            element.querySelector(".job-banner-body, div")?.appendChild(link);
          }
        }
        element.classList.add(data.status.toLowerCase());
        setTimeout(() => window.location.assign(window.location.pathname), 2500);
      }
    } catch (_) {
      // A temporary request failure should not cancel the local automation.
    }
  }, isExecution ? 800 : 1800);
  element._pollTimer = timer;
}

async function stopProject(projectId, button) {
  if (!projectId) return;
  if (button) {
    button.disabled = true;
    button.textContent = "Stopping…";
  }
  try {
    const response = await fetch(`/projects/${projectId}/stop`, {
      method: "POST",
      headers: {
        Accept: "application/json",
        "X-Requested-With": "XMLHttpRequest",
      },
    });
    const data = await response.json().catch(() => ({}));
    const banner = button?.closest(".job-banner");
    if (banner?._pollTimer) clearInterval(banner._pollTimer);
    banner?.querySelector(".spinner")?.remove();
    const strong = banner?.querySelector("strong");
    const text = banner?.querySelector("p");
    if (strong) strong.textContent = "STOPPED";
    if (text) text.textContent = data.message || "Stopped by user — browser closed.";
    banner?.classList.add("stopped");
    setTimeout(() => window.location.assign(window.location.pathname), 1200);
  } catch (_) {
    if (button) {
      button.disabled = false;
      button.textContent = "Stop";
    }
    window.location.assign(`/projects/${projectId}`);
  }
}

document.querySelectorAll("[data-scan-job]").forEach((element) => {
  pollJob(element, `/api/scans/${element.dataset.scanJob}`);
});

document.querySelectorAll("[data-execution-job]").forEach((element) => {
  pollJob(element, `/api/executions/${element.dataset.executionJob}`);
});

document.querySelectorAll("[data-stop-project]").forEach((button) => {
  button.addEventListener("click", (event) => {
    event.preventDefault();
    stopProject(button.dataset.stopProject, button);
  });
});

document.querySelectorAll(".stop-form").forEach((form) => {
  form.addEventListener("submit", () => {
    const button = form.querySelector("button");
    if (button) {
      button.disabled = true;
      button.textContent = "Stopping…";
    }
  });
});

/* ---- API Test Farm ---- */
function syncAuthFields() {
  const type = document.getElementById("api-auth-type")?.value || "none";
  document.getElementById("auth-token-wrap")?.classList.toggle("hidden", type !== "bearer");
  document.getElementById("auth-basic-wrap")?.classList.toggle("hidden", type !== "basic");
  document.getElementById("auth-apikey-wrap")?.classList.toggle("hidden", type !== "apikey");
}

function buildAuth() {
  const type = document.getElementById("api-auth-type")?.value || "none";
  if (type === "bearer") {
    return { type: "bearer", token: document.getElementById("api-auth-token")?.value || "" };
  }
  if (type === "basic") {
    return {
      type: "basic",
      username: document.getElementById("api-auth-user")?.value || "",
      password: document.getElementById("api-auth-pass")?.value || "",
    };
  }
  if (type === "apikey") {
    return {
      type: "apikey",
      header: document.getElementById("api-auth-header")?.value || "X-API-Key",
      value: document.getElementById("api-auth-key")?.value || "",
    };
  }
  return { type: "none" };
}

function applyAuthToForm(auth) {
  auth = auth || { type: "none" };
  const type = auth.type || "none";
  const sel = document.getElementById("api-auth-type");
  if (sel) sel.value = type;
  if (document.getElementById("api-auth-token")) document.getElementById("api-auth-token").value = auth.token || "";
  if (document.getElementById("api-auth-user")) document.getElementById("api-auth-user").value = auth.username || "";
  if (document.getElementById("api-auth-pass")) document.getElementById("api-auth-pass").value = auth.password || "";
  if (document.getElementById("api-auth-header")) document.getElementById("api-auth-header").value = auth.header || "X-API-Key";
  if (document.getElementById("api-auth-key")) document.getElementById("api-auth-key").value = auth.value || "";
  syncAuthFields();
}

function parseJsonField(value, fallback) {
  try {
    return JSON.parse(value || (Array.isArray(fallback) ? "[]" : "{}"));
  } catch (_) {
    throw new Error("Invalid JSON");
  }
}

function loadEscuelajsLoginSample() {
  document.getElementById("api-name").value = "EscuelaJS Login";
  document.getElementById("api-method").value = "POST";
  document.getElementById("api-url").value = "https://api.escuelajs.co/api/v1/auth/login";
  document.getElementById("api-expected").value = "201";
  document.getElementById("api-headers").value = JSON.stringify({ "Content-Type": "application/json" }, null, 2);
  document.getElementById("api-body").value = JSON.stringify(
    { email: "john@mail.com", password: "changeme" },
    null,
    2
  );
  document.getElementById("api-extractors").value = JSON.stringify(
    [{ name: "token", path: "access_token", source: "json" }],
    null,
    2
  );
  document.getElementById("api-operators").value = "[]";
  document.getElementById("api-contains").value = "";
  applyAuthToForm({ type: "none" });
}

function loadEscuelajsProfileSample() {
  document.getElementById("api-name").value = "EscuelaJS Profile";
  document.getElementById("api-method").value = "GET";
  document.getElementById("api-url").value = "https://api.escuelajs.co/api/v1/auth/profile";
  document.getElementById("api-expected").value = "200";
  document.getElementById("api-headers").value = "{}";
  document.getElementById("api-body").value = "";
  document.getElementById("api-extractors").value = "[]";
  document.getElementById("api-operators").value = "[]";
  document.getElementById("api-contains").value = "";
  applyAuthToForm({ type: "bearer", token: "{{token}}" });
}

document.getElementById("btn-sample-login")?.addEventListener("click", loadEscuelajsLoginSample);
document.getElementById("btn-sample-profile")?.addEventListener("click", loadEscuelajsProfileSample);

function apiBuilderPayload() {
  let headers = {};
  const rawHeaders = document.getElementById("api-headers")?.value || "{}";
  try {
    headers = JSON.parse(rawHeaders || "{}");
  } catch (_) {
    throw new Error("Headers must be valid JSON");
  }
  const contains = document.getElementById("api-contains")?.value?.trim();
  const assertions = [];
  if (contains) {
    assertions.push({ kind: "body_contains", expected: contains, path: "" });
  }
  const operators = parseJsonField(document.getElementById("api-operators")?.value || "[]", []);
  if (Array.isArray(operators)) {
    operators.forEach((item) => assertions.push(item));
  }
  const extractors = parseJsonField(document.getElementById("api-extractors")?.value || "[]", []);
  return {
    name: document.getElementById("api-name")?.value || "API Request",
    method: document.getElementById("api-method")?.value || "GET",
    url: document.getElementById("api-url")?.value || "",
    headers,
    body: document.getElementById("api-body")?.value || "",
    expected_status: Number(document.getElementById("api-expected")?.value || 200),
    assertions,
    extractors: Array.isArray(extractors) ? extractors : [],
    auth: buildAuth(),
  };
}

document.getElementById("api-auth-type")?.addEventListener("change", syncAuthFields);
syncAuthFields();

document.getElementById("btn-save-vars")?.addEventListener("click", async () => {
  try {
    const variables = parseJsonField(document.getElementById("api-variables")?.value || "{}", {});
    const response = await fetch("/api-farm/variables", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ variables }),
    });
    const data = await response.json();
    if (!data.ok) {
      alert(data.error || "Save failed");
      return;
    }
    alert("Parameters saved");
  } catch (err) {
    alert(String(err.message || err));
  }
});

document.getElementById("btn-send")?.addEventListener("click", async () => {
  const pill = document.getElementById("api-result-pill");
  const meta = document.getElementById("api-meta");
  const extractedEl = document.getElementById("api-extracted");
  const box = document.getElementById("api-response");
  try {
    const payload = apiBuilderPayload();
    pill.textContent = "Sending…";
    meta.textContent = `${payload.method} ${payload.url}`;
    if (extractedEl) extractedEl.textContent = "";
    const response = await fetch("/api-farm/send", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    pill.textContent = data.status || (data.ok ? "PASS" : "FAIL");
    pill.className = `pill ${data.ok ? "pass" : "fail"}`;
    const normalized = data.normalized;
    const normalizedNote = normalized
      ? ` · parsed URL: ${normalized.url || payload.url}`
      : "";
    meta.textContent = `HTTP ${data.http_status ?? "—"} · ${data.duration_ms ?? 0} ms · resolved: ${data.resolved_url || payload.url}${normalizedNote} · ${(data.messages || []).join(" · ")}`;
    if (extractedEl && data.extracted && Object.keys(data.extracted).length) {
      extractedEl.innerHTML = `<strong>Extracted for next APIs:</strong> ${Object.entries(data.extracted).map(([k, v]) => `<code>{{${k}}}</code>=${String(v).slice(0, 80)}`).join(" · ")}`;
      const varsBox = document.getElementById("api-variables");
      if (varsBox && data.variables) {
        varsBox.value = JSON.stringify(data.variables, null, 2);
      }
    } else if (extractedEl && !data.ok && (data.messages || []).some((m) => /Extract failed|not resolved/i.test(m))) {
      extractedEl.innerHTML = `<span class="fail"><strong>Token chain issue:</strong> ${(data.messages || []).filter((m) => /Extract|token|resolved|Expected status|Tip:/i.test(m)).join(" · ")}</span>`;
    }
    box.textContent = data.body || data.full_body || data.error || JSON.stringify(data, null, 2);
  } catch (err) {
    pill.textContent = "ERROR";
    pill.className = "pill fail";
    meta.textContent = String(err.message || err);
    box.textContent = String(err);
  }
});

async function saveApiPayload(payload) {
  const response = await fetch("/api-farm/save", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(payload),
  });
  return response.json();
}

document.getElementById("btn-save")?.addEventListener("click", async () => {
  try {
    const data = await saveApiPayload(apiBuilderPayload());
    if (!data.ok) {
      alert(data.error || "Save failed");
      return;
    }
    window.location.reload();
  } catch (err) {
    alert(String(err.message || err));
  }
});

document.getElementById("btn-gen-one")?.addEventListener("click", async () => {
  try {
    const payload = apiBuilderPayload();
    const data = await saveApiPayload(payload);
    if (!data.ok) {
      alert(data.error || "Save failed");
      return;
    }
    const form = document.createElement("form");
    form.method = "post";
    form.action = "/api-farm/generate-cases";
    const input = document.createElement("input");
    input.type = "hidden";
    input.name = "request_id";
    input.value = data.id;
    form.appendChild(input);
    document.body.appendChild(form);
    form.submit();
  } catch (err) {
    alert(String(err.message || err));
  }
});

document.querySelectorAll("[data-load-api]").forEach((button) => {
  button.addEventListener("click", () => {
    const req = JSON.parse(button.getAttribute("data-load-api") || "{}");
    document.getElementById("api-name").value = req.name || "";
    document.getElementById("api-method").value = req.method || "GET";
    document.getElementById("api-url").value = req.url || "";
    document.getElementById("api-expected").value = req.expected_status || 200;
    document.getElementById("api-headers").value = JSON.stringify(req.headers || {}, null, 2);
    document.getElementById("api-body").value = req.body || "";
    document.getElementById("api-extractors").value = JSON.stringify(req.extractors || [], null, 2);
    const ops = (req.assertions || []).filter((a) => a.operator);
    const contains = (req.assertions || []).find((a) => a.kind === "body_contains" && !a.operator);
    document.getElementById("api-operators").value = JSON.stringify(ops, null, 2);
    document.getElementById("api-contains").value = contains?.expected || "";
    applyAuthToForm(req.auth || { type: "none" });
    window.scrollTo({ top: 0, behavior: "smooth" });
  });
});

async function persistOrder() {
  const rows = [...document.querySelectorAll("#api-request-rows tr[data-req-id]")];
  const order = rows.map((row) => row.dataset.reqId);
  await fetch("/api-farm/reorder", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ order }),
  });
  rows.forEach((row, index) => {
    const cell = row.querySelector(".order-cell");
    if (cell) cell.textContent = String(index + 1);
  });
}

document.querySelectorAll("[data-move-up]").forEach((button) => {
  button.addEventListener("click", async () => {
    const row = button.closest("tr");
    const prev = row?.previousElementSibling;
    if (row && prev) {
      row.parentNode.insertBefore(row, prev);
      await persistOrder();
    }
  });
});

document.querySelectorAll("[data-move-down]").forEach((button) => {
  button.addEventListener("click", async () => {
    const row = button.closest("tr");
    const next = row?.nextElementSibling;
    if (row && next) {
      row.parentNode.insertBefore(next, row);
      await persistOrder();
    }
  });
});
