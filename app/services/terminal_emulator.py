from __future__ import annotations

from dataclasses import dataclass

import pyte


@dataclass
class TerminalDimensions:
    width: int
    height: int


class TerminalEmulator:
    """Renders raw tmux output (with ANSI) into a screen buffer."""

    def __init__(self, dimensions: TerminalDimensions) -> None:
        self.dimensions = dimensions
        self._screen = pyte.Screen(dimensions.width, dimensions.height)
        self._stream = pyte.Stream(self._screen)

    def render(self, raw_text: str) -> str:
        self._screen.reset()
        self._stream.feed(self._ensure_crlf(raw_text))
        lines = [line.rstrip() for line in self._screen.display]
        # Trim trailing blank lines to reduce noise for hashing/classification.
        while lines and not lines[-1]:
            lines.pop()
        return "\n".join(lines)

    @staticmethod
    def _ensure_crlf(raw_text: str) -> str:
        # Terminals typically move to column 0 on CR; tmux capture may only include LF.
        if not raw_text:
            return raw_text
        chars: list[str] = []
        prev = ""
        for ch in raw_text:
            if ch == "\n" and prev != "\r":
                chars.append("\r\n")
            else:
                chars.append(ch)
            prev = ch
        return "".join(chars)
