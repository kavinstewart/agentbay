from app.services.terminal_emulator import TerminalDimensions, TerminalEmulator


def test_terminal_emulator_strips_ansi_and_renders_lines() -> None:
    raw = "\x1b[31mHello\x1b[0m, \x1b[32mWorld\x1b[0m!\nSecond line\n"
    emulator = TerminalEmulator(TerminalDimensions(width=80, height=5))
    rendered = emulator.render(raw)
    assert rendered.splitlines() == ["Hello, World!", "Second line"]


def test_terminal_emulator_handles_cursor_movements() -> None:
    raw = "Loading-\rLoading\\"
    emulator = TerminalEmulator(TerminalDimensions(width=80, height=3))
    rendered = emulator.render(raw)
    # Carriage return rewrites the same line; final spinner glyph should be backslash.
    assert rendered == "Loading\\"
