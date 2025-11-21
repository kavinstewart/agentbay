from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sqlite3
import subprocess
import time
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable, Iterator

from app.config import settings

ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


@dataclass
class WorkerMetadata:
    worker_id: str
    tmux_session: str
    workspace: Path
    cli_type: str


@dataclass
class PaneInfo:
    pane_id: str
    session_name: str
    window_index: str
    pane_index: str
    cwd: Path
    title: str

    @property
    def target(self) -> str:
        return f"{self.session_name}:{self.window_index}.{self.pane_index}"


@dataclass
class PaneState:
    last_snapshot_hash: str | None = None
    last_classified_hash: str | None = None
    stable_count: int = 0
    last_change_ts: float = field(default_factory=lambda: time.time())
    state: str = "UNKNOWN"
    summary: str = ""
    actions_needed: str | None = None
    threshold: int = settings.watcher_default_stability


@dataclass
class ClassificationResult:
    state: str
    summary: str
    actions_needed: str | None = None


class ClassifierPack:
    """Loads regex cues + few-shot metadata for a CLI."""

    def __init__(
        self,
        name: str,
        stability_polls: int,
        idle_patterns: list[str],
        busy_patterns: list[str],
        confirm_patterns: list[str],
        error_patterns: list[str],
    ) -> None:
        self.name = name
        self.stability_polls = stability_polls
        flags = re.MULTILINE | re.IGNORECASE
        self.idle_regexes = [re.compile(pattern, flags) for pattern in idle_patterns]
        self.busy_regexes = [re.compile(pattern, flags) for pattern in busy_patterns]
        self.confirm_regexes = [re.compile(pattern, flags) for pattern in confirm_patterns]
        self.error_regexes = [re.compile(pattern, flags) for pattern in error_patterns]

    @classmethod
    def load(cls, cli_type: str) -> "ClassifierPack":
        packs_dir = settings.classifier_packs_dir
        packs_dir.mkdir(parents=True, exist_ok=True)
        pack_path = packs_dir / f"{cli_type}.yml"
        if not pack_path.exists():
            logging.warning("No classifier pack found for %s, falling back to defaults", cli_type)
            return cls(cli_type, settings.watcher_default_stability, [], [], [], [])
        try:
            raw = json.loads(pack_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            logging.error("Failed to parse classifier pack %s: %s", pack_path, exc)
            return cls(cli_type, settings.watcher_default_stability, [], [], [], [])
        return cls(
            cli_type,
            int(raw.get("stability_polls") or settings.watcher_default_stability),
            idle_patterns=list(raw.get("idle_patterns") or []),
            busy_patterns=list(raw.get("busy_patterns") or []),
            confirm_patterns=list(raw.get("needs_confirmation_patterns") or []),
            error_patterns=list(raw.get("error_patterns") or []),
        )


class RegexClassifier:
    """Deterministic classifier that uses CLI-specific regex cues."""

    def __init__(self, pack: ClassifierPack) -> None:
        self.pack = pack

    def classify(self, snapshot: str) -> ClassificationResult:
        if self._match_any(self.pack.error_regexes, snapshot):
            return ClassificationResult(
                state="ERROR",
                summary="Detected error output",
                actions_needed="Inspect the PTY logs to unblock the worker.",
            )
        if self._match_any(self.pack.confirm_regexes, snapshot):
            return ClassificationResult(
                state="NEEDS_CONFIRMATION",
                summary="Tool is waiting for explicit confirmation",
                actions_needed="Answer the confirmation prompt in the PTY.",
            )
        if self._match_any(self.pack.busy_regexes, snapshot):
            return ClassificationResult(
                state="BUSY",
                summary="Workload still running",
                actions_needed=None,
            )
        if self._match_any(self.pack.idle_regexes, snapshot):
            return ClassificationResult(
                state="READY",
                summary="Idle prompt detected",
                actions_needed=None,
            )
        # Default to READY if nothing matches and the snapshot is stable.
        return ClassificationResult(
            state="READY",
            summary="No activity detected in snapshot",
            actions_needed=None,
        )

    @staticmethod
    def _match_any(patterns: Iterable[re.Pattern[str]], text: str) -> bool:
        return any(pattern.search(text) for pattern in patterns)


class OpenRouterClassifier:
    """Optional LLM-powered classifier."""

    def __init__(self, pack: ClassifierPack) -> None:
        self.pack = pack
        self.api_key = settings.openrouter_api_key
        self.model = settings.openrouter_model
        self._session = None

    def classify(self, snapshot: str, metadata: dict[str, Any]) -> ClassificationResult:
        import requests  # lazy import to avoid dependency for users who skip LLM mode

        if not self.api_key:
            raise RuntimeError("No OpenRouter API key configured")
        if self._session is None:
            self._session = requests.Session()
        prompt = (
            "You read tmux pane text for a CLI worker. Infer the PTY state using four axes plus metadata.\n"
            "Return strict JSON matching:\n"
            "{\n"
            '  "session_lifecycle": "<DISCONNECTED|LOGIN_OR_SETUP|ACTIVE_SESSION|TEARDOWN>",\n'
            '  "terminal_mode": "<CANONICAL|RAW|UNKNOWN>",\n'
            '  "foreground_role": "<SHELL|CHILD_COMMAND|MULTIPLEXER|UNKNOWN>",\n'
            '  "io_disposition": "<IDLE_AT_PROMPT|STREAMING_OUTPUT|SILENT_PROCESSING|BLOCKED_ON_INPUT|INTERRUPTIBLE_BUSY|UNKNOWN>",\n'
            '  "error_recent": true,\n'
            '  "summary": "<short string>",\n'
            '  "actions_needed": "<string or null>"\n'
            "}\n"
            "Axis definitions:\n"
            "1. session_lifecycle: DISCONNECTED (pane closed), LOGIN_OR_SETUP (ssh/login banners before shell), ACTIVE_SESSION (shell or process running), TEARDOWN (logout/shutdown).\n"
            "2. terminal_mode: CANONICAL (line-buffered shell), RAW (application controls keys / alternate screen), UNKNOWN.\n"
            "3. foreground_role: SHELL (bash/zsh prompt owns tty), CHILD_COMMAND (non-shell program), MULTIPLEXER (tmux/screen hosting another shell), UNKNOWN.\n"
            "4. io_disposition: IDLE_AT_PROMPT (prompt visible, safe to send command), STREAMING_OUTPUT (logs/progress flowing), SILENT_PROCESSING (command running quietly), BLOCKED_ON_INPUT (explicit prompt waiting for y/N/password/etc.), INTERRUPTIBLE_BUSY (async REPLs like Codex that keep processing yet accept new instructions), UNKNOWN.\n"
            "error_recent indicates whether the last command clearly failed (traceback, non-zero exit). Provide a concise summary and optional actions_needed instruction."
        )
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": prompt,
                },
                {
                    "role": "user",
                    "content": f"CLI type: {metadata.get('cli_type')}\nSnapshot:\n{snapshot}",
                },
            ],
        }
        response = self._session.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        message = data["choices"][0]["message"]["content"]
        parsed = json.loads(message)
        return ClassificationResult(
            state=str(parsed.get("state") or "READY"),
            summary=str(parsed.get("summary") or "").strip(),
            actions_needed=parsed.get("actions_needed"),
        )


class HybridClassifier:
    """Attempts OpenRouter first, falling back to regex heuristics."""

    def __init__(self, pack: ClassifierPack) -> None:
        self.pack = pack
        self.regex = RegexClassifier(pack)
        self._llm: OpenRouterClassifier | None = None
        if settings.openrouter_api_key:
            self._llm = OpenRouterClassifier(pack)

    def classify(self, snapshot: str, metadata: dict[str, Any]) -> ClassificationResult:
        if self._llm:
            try:
                return self._llm.classify(snapshot, metadata)
            except Exception as exc:  # pragma: no cover - network failures
                logging.warning("LLM classification failed for %s: %s", metadata.get("pane_id"), exc)
        return self.regex.classify(snapshot)


class StatusStore:
    """Persists PTY metadata and their latest states."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ptys (
                id TEXT PRIMARY KEY,
                worker_id TEXT,
                tmux_session TEXT,
                tmux_window TEXT,
                tmux_pane TEXT,
                cwd TEXT,
                cli_type TEXT
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS status (
                id TEXT PRIMARY KEY,
                state TEXT NOT NULL,
                summary TEXT,
                actions_needed TEXT,
                last_snapshot_hash TEXT,
                last_change_ts REAL,
                last_polled_ts REAL,
                stable_count INTEGER
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS status_history (
                id TEXT,
                ts REAL,
                state TEXT,
                summary TEXT
            )
            """
        )
        self._conn.commit()

    def upsert(
        self,
        pane: PaneInfo,
        worker: WorkerMetadata,
        pane_state: PaneState,
        snapshot_hash: str,
        polled_ts: float,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO ptys (id, worker_id, tmux_session, tmux_window, tmux_pane, cwd, cli_type)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                worker_id=excluded.worker_id,
                tmux_session=excluded.tmux_session,
                tmux_window=excluded.tmux_window,
                tmux_pane=excluded.tmux_pane,
                cwd=excluded.cwd,
                cli_type=excluded.cli_type
            """,
            (
                pane.pane_id,
                worker.worker_id,
                pane.session_name,
                pane.window_index,
                pane.pane_index,
                str(pane.cwd),
                worker.cli_type,
            ),
        )
        self._conn.execute(
            """
            INSERT INTO status (id, state, summary, actions_needed, last_snapshot_hash, last_change_ts, last_polled_ts, stable_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                state=excluded.state,
                summary=excluded.summary,
                actions_needed=excluded.actions_needed,
                last_snapshot_hash=excluded.last_snapshot_hash,
                last_change_ts=excluded.last_change_ts,
                last_polled_ts=excluded.last_polled_ts,
                stable_count=excluded.stable_count
            """,
            (
                pane.pane_id,
                pane_state.state,
                pane_state.summary,
                pane_state.actions_needed,
                snapshot_hash,
                pane_state.last_change_ts,
                polled_ts,
                pane_state.stable_count,
            ),
        )
        self._conn.execute(
            "INSERT INTO status_history (id, ts, state, summary) VALUES (?, ?, ?, ?)",
            (pane.pane_id, polled_ts, pane_state.state, pane_state.summary),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()


class PtyWatcher:
    """Background daemon that polls tmux panes and emits readiness states."""

    def __init__(self, interval: float | None = None) -> None:
        self.interval = interval or settings.watcher_interval
        self.tmux_bin = settings.tmux_bin
        self.workspace_root = settings.workspace_root
        self.state: dict[str, PaneState] = {}
        self._classifiers: dict[str, HybridClassifier] = {}
        self.status_store = StatusStore(settings.status_db_path)

    async def run(self) -> None:
        logging.info("Starting PTY watcher loop (interval=%ss)", self.interval)
        try:
            while True:
                await self._poll_once()
                await asyncio.sleep(self.interval)
        except asyncio.CancelledError:  # pragma: no cover
            logging.info("PTY watcher cancelled")
        finally:
            self.status_store.close()

    async def _poll_once(self) -> None:
        workers = self._load_workers()
        panes = self._list_tmux_panes()
        now = time.time()
        seen: set[str] = set()
        for pane in panes:
            worker = workers.get(pane.session_name)
            if not worker:
                continue
            seen.add(pane.pane_id)
            await self._process_pane(pane, worker, now)
        # purge panes that disappeared
        removed = set(self.state.keys()) - seen
        for pane_id in removed:
            logging.info("Pane %s disappeared, removing cache entry", pane_id)
            del self.state[pane_id]

    async def _process_pane(self, pane: PaneInfo, worker: WorkerMetadata, ts: float) -> None:
        text = self._capture_pane_text(pane)
        stripped = strip_ansi(text)
        snapshot_hash = sha256(stripped.encode("utf-8")).hexdigest()
        pane_state = self.state.setdefault(
            pane.pane_id,
            PaneState(threshold=self._classifier_for(worker.cli_type).pack.stability_polls),
        )
        if pane_state.last_snapshot_hash != snapshot_hash:
            pane_state.last_snapshot_hash = snapshot_hash
            pane_state.stable_count = 0
            pane_state.last_change_ts = ts
            pane_state.state = "BUSY"
            pane_state.summary = "Pane output changing"
            pane_state.actions_needed = None
        else:
            pane_state.stable_count += 1
            threshold = pane_state.threshold or settings.watcher_default_stability
            if pane_state.stable_count >= threshold and pane_state.last_classified_hash != snapshot_hash:
                classifier = self._classifier_for(worker.cli_type)
                result = classifier.classify(
                    stripped,
                    {
                        "worker_id": worker.worker_id,
                        "pane_id": pane.pane_id,
                        "cli_type": worker.cli_type,
                    },
                )
                pane_state.state = result.state
                pane_state.summary = result.summary
                pane_state.actions_needed = result.actions_needed
                pane_state.last_classified_hash = snapshot_hash
        self._write_status(worker, pane, pane_state, snapshot_hash, ts)

    def _write_status(
        self,
        worker: WorkerMetadata,
        pane: PaneInfo,
        pane_state: PaneState,
        snapshot_hash: str,
        ts: float,
    ) -> None:
        status_payload = {
            "worker_id": worker.worker_id,
            "pane_id": pane.pane_id,
            "tmux_session": pane.session_name,
            "tmux_target": pane.target,
            "state": pane_state.state,
            "summary": pane_state.summary,
            "actions_needed": pane_state.actions_needed,
            "last_change_ts": pane_state.last_change_ts,
            "last_polled_ts": ts,
        }
        status_path = worker.workspace / "status.json"
        status_path.write_text(json.dumps(status_payload, indent=2), encoding="utf-8")
        self.status_store.upsert(pane, worker, pane_state, snapshot_hash, ts)

    def _classifier_for(self, cli_type: str) -> HybridClassifier:
        classifier = self._classifiers.get(cli_type)
        if classifier is None:
            pack = ClassifierPack.load(cli_type or settings.default_cli_type)
            classifier = HybridClassifier(pack)
            self._classifiers[cli_type] = classifier
        return classifier

    def _capture_pane_text(self, pane: PaneInfo) -> str:
        try:
            result = subprocess.run(
                [self.tmux_bin, "capture-pane", "-pJ", "-t", pane.target],
                check=True,
                capture_output=True,
                text=True,
            )
            return result.stdout
        except subprocess.CalledProcessError as exc:
            logging.error("tmux capture-pane failed for %s: %s", pane.target, exc)
            return ""

    def _list_tmux_panes(self) -> list[PaneInfo]:
        format_str = "#{pane_id}\t#{session_name}\t#{window_index}\t#{pane_index}\t#{pane_current_path}\t#{pane_title}"
        try:
            result = subprocess.run(
                [self.tmux_bin, "list-panes", "-a", "-F", format_str],
                check=True,
                text=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError as exc:
            logging.error("Failed to list tmux panes: %s", exc)
            return []
        panes: list[PaneInfo] = []
        for line in result.stdout.splitlines():
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) != 6:
                continue
            pane_id, session, window_index, pane_index, cwd, title = parts
            panes.append(
                PaneInfo(
                    pane_id=pane_id.strip(),
                    session_name=session.strip(),
                    window_index=window_index.strip(),
                    pane_index=pane_index.strip(),
                    cwd=Path(cwd.strip() or "."),
                    title=title.strip(),
                )
            )
        return panes

    def _load_workers(self) -> dict[str, WorkerMetadata]:
        workers: dict[str, WorkerMetadata] = {}
        if not self.workspace_root.exists():
            return workers
        for worker_dir in self.workspace_root.iterdir():
            if not worker_dir.is_dir():
                continue
            meta_path = worker_dir / "worker.json"
            if not meta_path.exists():
                continue
            try:
                data = json.loads(meta_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            worker_id = str(data.get("id") or "")
            session = str(data.get("tmux_session") or "")
            if not worker_id or not session:
                continue
            cli_type = str(data.get("cli_type") or settings.default_cli_type)
            workers[session] = WorkerMetadata(
                worker_id=worker_id,
                tmux_session=session,
                workspace=worker_dir,
                cli_type=cli_type,
            )
        return workers


def strip_ansi(text: str) -> str:
    return ANSI_ESCAPE_RE.sub("", text)
