"""Run OpenSenseMap checks through the UTS API Test Farm endpoints."""

from __future__ import annotations

import json
from pathlib import Path

import requests

BASE = "http://127.0.0.1:5050"
OUT = Path(__file__).resolve().parent / "web-data" / "api-farm" / "reports"


def main() -> None:
    s = requests.Session()
    s.get(f"{BASE}/login", timeout=20)
    login = s.post(
        f"{BASE}/login",
        data={
            "username": "admin",
            "password": "admin123",
            "role": "Tester",
            "language": "en",
        },
        allow_redirects=True,
        timeout=20,
    )
    print("login:", login.status_code, login.url)

    # Prefer fast endpoints; full /boxes listing is huge/slow on opensensemap.
    tests = [
        {
            "id": "osm_root",
            "name": "OpenSenseMap API root",
            "method": "GET",
            "url": "https://api.opensensemap.org/",
            "expected_status": 200,
            "headers": {"Accept": "application/json, text/plain, */*"},
            "body": "",
            "assertions": [],
            "tags": ["opensensemap", "positive"],
            "auth": {"type": "none"},
            "extractors": [],
        },
        {
            "id": "osm_stats",
            "name": "OpenSenseMap stats",
            "method": "GET",
            "url": "https://api.opensensemap.org/stats",
            "expected_status": 200,
            "headers": {"Accept": "application/json"},
            "body": "",
            "assertions": [],
            "tags": ["opensensemap", "positive"],
            "auth": {"type": "none"},
            "extractors": [],
        },
        {
            "id": "osm_box_berlin",
            "name": "OpenSenseMap box LeKa Berlin",
            "method": "GET",
            "url": "https://api.opensensemap.org/boxes/5391be52a8341554157792e6",
            "expected_status": 200,
            "headers": {"Accept": "application/json"},
            "body": "",
            "assertions": [],
            "tags": ["opensensemap", "positive"],
            "auth": {"type": "none"},
            "extractors": [],
        },
        {
            "id": "osm_boxes_near_berlin",
            "name": "OpenSenseMap boxes near Berlin",
            "method": "GET",
            "url": "https://api.opensensemap.org/boxes?near=13.404954,52.520008&maxDistance=1000",
            "expected_status": 200,
            "headers": {"Accept": "application/json"},
            "body": "",
            "assertions": [],
            "tags": ["opensensemap", "positive"],
            "auth": {"type": "none"},
            "extractors": [],
        },
    ]

    results = []
    for spec in tests:
        send = s.post(f"{BASE}/api-farm/send", json=spec, timeout=180)
        data = send.json()
        preview = (data.get("full_body") or data.get("body") or "")[:400]
        row = {
            "name": spec["name"],
            "url": spec["url"],
            "ok": data.get("ok"),
            "status": data.get("status"),
            "http_status": data.get("http_status"),
            "duration_ms": data.get("duration_ms"),
            "error": data.get("error"),
            "body_preview": preview,
        }
        results.append(row)
        print(
            f"SEND {spec['name']}: {data.get('status')} "
            f"HTTP {data.get('http_status')} {data.get('duration_ms')}ms"
        )
        print(" ", preview.replace("\n", " ")[:260])
        save = s.post(f"{BASE}/api-farm/save", json=spec, timeout=60)
        print("  save:", save.status_code)

    # Run only the OpenSenseMap requests we just saved by using farm run
    # (collection may contain older requests too — report still useful).
    run = s.post(f"{BASE}/api-farm/run", timeout=300, allow_redirects=True)
    print("RUN ALL:", run.status_code, run.url)

    report = s.get(f"{BASE}/api-farm/report", timeout=60)
    OUT.mkdir(parents=True, exist_ok=True)
    summary_path = OUT / "opensensemap-run-summary.json"
    summary_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    report_copy = OUT / "opensensemap-api-farm-report.html"
    if report.status_code == 200:
        report_copy.write_text(report.text, encoding="utf-8")
    print("summary:", summary_path)
    print(
        "report_copy:",
        report_copy,
        "bytes",
        report_copy.stat().st_size if report_copy.exists() else 0,
    )
    print("report_url: http://127.0.0.1:5050/api-farm/report")


if __name__ == "__main__":
    main()
