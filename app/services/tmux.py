from __future__ import annotations

import subprocess
from dataclasses import dataclass

from app.config import settings


class TmuxCommandError(RuntimeError):
    pass


@dataclass
class PaneSnapshot:
    text: str
    new_text: str


class TmuxController:
    """Lightweight helper that interacts with tmux for a worker."""

    def __init__(self, session: str, pane: str = "0") -> None:
        self.session = session
        self.pane = pane
        self.tmux_bin = settings.tmux_bin
        self._last_size = 0

    def _run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        cmd = [self.tmux_bin, *args]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
        if check and result.returncode != 0:
            raise TmuxCommandError(result.stderr.strip() or "tmux command failed")
        return result

    def send_line(self, command: str) -> None:
        self._run("send-keys", "-t", f"{self.session}:{self.pane}", command)
        self._run("send-keys", "-t", f"{self.session}:{self.pane}", "C-m")

    def capture_pane(self) -> PaneSnapshot:
        result = self._run("capture-pane", "-pJ", "-t", f"{self.session}:{self.pane}")
        text = result.stdout
        new_text = ""
        if self._last_size <= len(text):
            new_text = text[self._last_size :]
        else:
            new_text = text
        self._last_size = len(text)
        return PaneSnapshot(text=text, new_text=new_text)
