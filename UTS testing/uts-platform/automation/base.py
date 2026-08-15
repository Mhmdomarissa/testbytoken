"""Shared utilities for E2E automation tests."""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
LOGS_DIR = ROOT / "logs"
RESULTS_DIR = ROOT / "reports"
UTS_RESULTS = Path(r"D:\uts\results")
LIVE_STEP_FILE = LOGS_DIR / "latest-live-step.txt"


@dataclass
class StepResult:
    step_no: int
    action: str
    object_name: str
    input_value: str
    status: str  # PASS | FAIL | SKIP
    message: str
    duration_ms: float
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


@dataclass
class TestResult:
    tc_id: str
    title: str
    test_type: str
    status: str  # PASS | FAIL | MANUAL_PENDING
    steps: list[StepResult] = field(default_factory=list)
    started_at: str = ""
    ended_at: str = ""
    duration_ms: float = 0
    error: str = ""


class ExecutionLogger:
    """Logs what is executing during automation — console + file."""

    def __init__(self, log_name: str = "automation"):
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_path = LOGS_DIR / f"{log_name}-{timestamp}.log"
        self._lines: list[str] = []
        self.on_progress: Callable[[str], None] | None = None

    def _emit(self, line: str) -> None:
        self._lines.append(line)
        print(line, flush=True)
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        except Exception:  # noqa: BLE001
            pass
        self._flush()
        try:
            LIVE_STEP_FILE.write_text(line + "\n", encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
        if self.on_progress:
            try:
                self.on_progress(line)
            except Exception:  # noqa: BLE001
                pass

    def info(self, message: str) -> None:
        self._emit(f"[{datetime.now().strftime('%H:%M:%S')}] INFO  | {message}")

    def step(self, step_no: int, action: str, detail: str) -> None:
        self._emit(f"[{datetime.now().strftime('%H:%M:%S')}] STEP {step_no:02d} | {action} -> {detail}")

    def pass_(self, message: str) -> None:
        self._emit(f"[{datetime.now().strftime('%H:%M:%S')}] PASS  | {message}")

    def fail(self, message: str) -> None:
        self._emit(f"[{datetime.now().strftime('%H:%M:%S')}] FAIL  | {message}")

    def executing(self, what: str) -> None:
        """Highlight what is currently running."""
        self._emit(f"[{datetime.now().strftime('%H:%M:%S')}] >>> EXECUTING: {what}")

    def step_banner(
        self,
        tc_id: str,
        tc_title: str,
        step_no: int,
        total_steps: int,
        action: str,
        object_name: str,
        input_value: str = "",
    ) -> None:
        """Clear console banner so the user can see the active step."""
        value_part = f" = '{input_value}'" if input_value else ""
        banner = (
            f"\n{'=' * 68}\n"
            f"  NOW EXECUTING  |  {tc_id}\n"
            f"  Test case      |  {tc_title}\n"
            f"  Step           |  {step_no}/{total_steps}\n"
            f"  Action         |  {action}\n"
            f"  Object         |  {object_name}{value_part}\n"
            f"{'=' * 68}"
        )
        print(banner, flush=True)
        try:
            sys.stdout.flush()
        except Exception:  # noqa: BLE001
            pass
        short = f"Step {step_no}/{total_steps}: {action} on '{object_name}'"
        if input_value:
            short += f" = '{input_value}'"
        line = f"[{datetime.now().strftime('%H:%M:%S')}] >>> {tc_id} | {short}"
        self._lines.append(line)
        self._flush()
        try:
            LIVE_STEP_FILE.write_text(banner.strip() + "\n", encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
        if self.on_progress:
            try:
                self.on_progress(f"{tc_id}: {short}")
            except Exception:  # noqa: BLE001
                pass

    def _flush(self) -> None:
        self.log_path.write_text("\n".join(self._lines) + "\n", encoding="utf-8")

    @property
    def content(self) -> str:
        return "\n".join(self._lines)


def load_test_data() -> dict[str, Any]:
    path = CONFIG_DIR / "test-data.json"
    return json.loads(path.read_text(encoding="utf-8"))


def load_ui_objects(screen_name: str) -> list[dict[str, Any]]:
    """Load UTS screen JSON from results folder."""
    candidates = list(UTS_RESULTS.glob(f"*{screen_name}*.json"))
    candidates = [p for p in candidates if "ui-objects" not in p.name.lower()]
    if not candidates:
        return []
    data = json.loads(candidates[0].read_text(encoding="utf-8"))
    return data.get("controls", data.get("objects", []))


def find_control(controls: list[dict], name: str) -> dict | None:
    name_lower = name.lower()
    for ctrl in controls:
        obj = (ctrl.get("object_name") or ctrl.get("name") or "").lower()
        text = (ctrl.get("displayed_text") or "").lower()
        if name_lower in obj or name_lower in text:
            return ctrl
    return None


def run_step(
    logger: ExecutionLogger,
    step_no: int,
    action: str,
    object_name: str,
    input_value: str,
    executor: Callable[[], tuple[bool, str]],
    *,
    tc_id: str = "",
    tc_title: str = "",
    total_steps: int = 0,
) -> StepResult:
    started = time.perf_counter()
    if tc_id and total_steps:
        logger.step_banner(tc_id, tc_title or tc_id, step_no, total_steps, action, object_name, input_value)
    else:
        logger.executing(f"{action} on '{object_name}'" + (f" value='{input_value}'" if input_value else ""))
        logger.step(step_no, action, f"object={object_name}, input={input_value or '(none)'}")

    try:
        from automation.selenium_session import is_selenium_enabled
        from automation.selenium_step_overlay import locator_key_for_object, show_result, show_step

        if is_selenium_enabled() and load_selenium_config().get("show_steps_in_browser", True):
            loc_key = locator_key_for_object(object_name)
            show_step(step_no, action, object_name, input_value, "RUNNING", loc_key)
    except Exception:  # noqa: BLE001
        pass

    try:
        ok, message = executor()
        if isinstance(message, str) and message.startswith("SKIP:"):
            status = "SKIP"
            ok = True
        else:
            status = "PASS" if ok else "FAIL"
    except Exception as exc:  # noqa: BLE001
        ok, message, status = False, str(exc), "FAIL"

    try:
        from automation.selenium_session import is_selenium_enabled
        from automation.selenium_step_overlay import show_result

        if is_selenium_enabled():
            cfg = load_selenium_config()
            if cfg.get("show_steps_in_browser", True):
                show_result(step_no, action, object_name, ok, message)
    except Exception:  # noqa: BLE001
        pass

    elapsed = (time.perf_counter() - started) * 1000
    if status == "SKIP":
        logger.info(message)
    elif ok:
        logger.pass_(message)
    else:
        logger.fail(message)

    return StepResult(
        step_no=step_no,
        action=action,
        object_name=object_name,
        input_value=input_value,
        status=status,
        message=message,
        duration_ms=round(elapsed, 2),
    )


def load_selenium_config() -> dict[str, Any]:
    path = CONFIG_DIR / "selenium.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def simulate_delay(ms: int = 200) -> None:
    time.sleep(ms / 1000)
