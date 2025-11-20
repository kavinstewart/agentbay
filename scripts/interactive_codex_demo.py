#!/usr/bin/env python3
"""Minimal prototype for monitoring interactive Codex with an LLM classifier."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict

import requests
from dotenv import load_dotenv

load_dotenv()

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = REPO_ROOT / ".tmp_worker"
SESSION = "codex_monitor_demo"
POLL_INTERVAL = 1.5
STABLE_THRESHOLD = 2
NO_ACTIVITY_TIMEOUT = 20
TIMEOUT = 180
CLASSIFIER_MODEL = os.environ.get("OPENROUTER_MODEL", "anthropic/claude-3.5-sonnet")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")

ANSI_REGEX = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
prompt_regex = re.compile(r"(OpenAI Codex|› )", re.IGNORECASE)


def run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=True, text=True, capture_output=True, **kwargs)


def run_no_capture(cmd: list[str], **kwargs: Any) -> None:
    subprocess.run(cmd, check=True, text=True, **kwargs)


def strip_ansi(text: str) -> str:
    return ANSI_REGEX.sub("", text)


def setup_workspace() -> None:
    if WORKSPACE.exists():
        shutil.rmtree(WORKSPACE)
    WORKSPACE.mkdir(parents=True)
    (WORKSPACE / "design.md").write_text("# Design Draft\n\nDocument the conductor architecture\n", encoding="utf-8")
    (WORKSPACE / "spec.txt").write_text(
        "Add a '## Smoke Test' heading to design.md with a single placeholder sentence explaining it covers quick validation.",
        encoding="utf-8",
    )


def start_codex() -> None:
    run_no_capture([
        "tmux",
        "new-session",
        "-d",
        "-s",
        SESSION,
        "-c",
        str(WORKSPACE),
        "codex",
    ])


def load_buffer(text: str) -> None:
    tmp_file = WORKSPACE / "_buffer.txt"
    tmp_file.write_text(text, encoding="utf-8")
    run_no_capture(["tmux", "load-buffer", str(tmp_file)])


def send_text(text: str) -> None:
    load_buffer(text)
    run_no_capture(["tmux", "paste-buffer", "-t", SESSION])
    run_no_capture(["tmux", "send-keys", "-t", SESSION, "C-m"])
    time.sleep(0.2)
    run_no_capture(["tmux", "send-keys", "-t", SESSION, "C-m"])


def ensure_activity(action: str) -> None:
    start = time.time()
    prev = capture_pane()
    while time.time() - start < NO_ACTIVITY_TIMEOUT:
        time.sleep(1)
        curr = capture_pane()
        if curr != prev:
            print(f"[monitor] activity detected after {action}")
            return
    print(f"[monitor] no activity detected for {action}; sending blank enter")
    run_no_capture(["tmux", "send-keys", "-t", SESSION, "C-m"])


def capture_pane() -> str:
    return run(["tmux", "capture-pane", "-pJ", "-t", SESSION]).stdout


def classify_screen(screen: str) -> Dict[str, Any]:
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY not set in .env")
    system = (
        "You examine snapshots of interactive coding CLIs and decide whether they are waiting for input."
        " Respond with valid JSON: {\"state\": READY|BUSY|NEEDS_CONFIRMATION|ERROR,"
        " \"summary\": <string>, \"actions_needed\": <string or null>}"
    )
    user = (
        "SCREEN:\n" + screen.strip() + "\n\nReturn ONLY JSON."
    )
    payload = {
        "model": CLASSIFIER_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    resp = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    try:
        content = data["choices"][0]["message"]["content"]
        if isinstance(content, list):
            text = content[0].get("text", "")
        else:
            text = content
        parsed = json.loads(text)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Unexpected classifier response: {data}") from exc
    return parsed


def wait_for_ready(step: str, require_activity: bool = True) -> Dict[str, Any]:
    print(f"\n[monitor] Waiting for completion of step: {step}")
    start = time.time()
    prev = None
    saw_activity = False
    stable = 0
    while time.time() - start < TIMEOUT:
        raw = capture_pane()
        changed = prev is None or raw != prev
        if prev is not None and changed:
            saw_activity = True
            stable = 0
        elif not changed and saw_activity:
            stable += 1
        prev = raw
        stripped = strip_ansi(raw)
        print(
            f"[monitor] capture={'change' if changed else 'same'} saw_activity={saw_activity} stable={stable}"
        )
        if (saw_activity or not require_activity) and stable >= STABLE_THRESHOLD and prompt_regex.search(stripped):
            classification = classify_screen(stripped)
            print(f"[classifier] {classification}")
            state = classification.get("state", "").upper()
            if state == "READY":
                return {"raw": raw, "stripped": stripped, "classification": classification}
            if state == "NEEDS_CONFIRMATION":
                print("[monitor] Auto-confirming...")
                send_text("y")
                ensure_activity("confirmation")
                saw_activity = False
                stable = 0
                prev = None
            elif state == "BUSY":
                stable = 0
        time.sleep(POLL_INTERVAL)
    raise TimeoutError("Timed out waiting for CLI to become ready")


def wait_for_prompt(label: str = "initial prompt") -> None:
    print(f"[monitor] Waiting for {label}...")
    start = time.time()
    prev = None
    stable = 0
    while time.time() - start < TIMEOUT:
        raw = capture_pane()
        changed = prev is None or raw != prev
        prev = raw
        stripped = strip_ansi(raw)
        if changed:
            stable = 0
        else:
            stable += 1
        if prompt_regex.search(stripped) and stable >= STABLE_THRESHOLD:
            print("[monitor] Prompt detected.")
            return
        time.sleep(POLL_INTERVAL)
    raise TimeoutError("Timed out waiting for prompt")


def summarize_results(label: str, info: Dict[str, Any]) -> None:
    print(f"\n--- {label} RESULT ---")
    print(info["stripped"])
    print(f"Classification: {info['classification']}")


def main() -> None:
    try:
        setup_workspace()
        start_codex()
        wait_for_prompt()
        send_text((WORKSPACE / "spec.txt").read_text())
        ensure_activity("initial instruction")
        first = wait_for_ready("Add smoke test heading")
        summarize_results("After edit", first)
        send_text("/review")
        ensure_activity("/review")
        second = wait_for_ready("Review changes", require_activity=True)
        summarize_results("/review output", second)
        final_design = (WORKSPACE / "design.md").read_text()
        print("\nFinal design.md:\n" + final_design)
    finally:
        try:
            run_no_capture(["tmux", "send-keys", "-t", SESSION, "C-c"])
        except Exception:  # noqa: BLE001
            pass
        try:
            run_no_capture(["tmux", "kill-session", "-t", SESSION])
        except Exception:
            pass


if __name__ == "__main__":
    main()
