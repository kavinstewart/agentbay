# tmux PTY Readiness Monitor Design

## Goal
- Spin up multiple tmux windows (one per PTY) rooted in user-specified directories.
- Let users switch between PTYs using native tmux commands while keeping automation entirely CLI-based.
- Continuously poll each PTY (every 5s) to determine whether it is READY (idle), BUSY (still running), or NEEDS_CONFIRMATION (waiting for approval), using screen diffs + an LLM classifier.
- Surface those statuses in-band (tmux status line + CLI command) so humans know when it’s safe to issue the next instruction.
- Keep the poller isolated from the main conductor CLI by running a separate watcher daemon.

## Current State
- Conductor already creates tmux workers and launches Codex (or other CLIs) inside them via shims.
- Prototype `scripts/interactive_codex_demo.py` shows how to:
  - wait for Codex’s prompt to stabilize
  - paste text via tmux buffer
  - sample pane output and call an LLM classifier to determine READY/BUSY/NEEDS_CONFIRMATION
- No global service currently polls all PTYs or updates a status display.

## Functional Requirements
1. **PTY creation** – command to create a new tmux window rooted in a given directory (e.g., `conductor pty create /path/to/dir` → `tmux new-window -c dir -n worker-X`).
2. **PTY switching** – rely on tmux’s native switching (`Ctrl+b n/p`, `select-window -t worker-X`). Optionally expose a helper CLI (`conductor pty switch worker-X`) that runs `tmux switch-client -t worker-X`.
3. **Readiness polling** – a dedicated `conductor pty watch` daemon samples each PTY every 5 seconds:
   - compute a full diff between the most recent ANSI-stripped snapshot and the previous one to detect changes
   - once the screen is stable for N=3 consecutive polls (configurable per CLI), send the snapshot to the classifier
   - classifier returns READY / BUSY / NEEDS_CONFIRMATION / ERROR + summary
4. **Status display** – watcher persists the latest state + timestamp per PTY (e.g., `.workers/<id>/status.json`) and a global cache (sqlite or jsonl) that downstream CLIs read. Update tmux status line (`[worker-a: READY] …`) via that cache. Provide a CLI (`conductor pty status`) to list all PTYs with their states and summaries.
5. **Notifications (optional)** – when a PTY transitions to READY or NEEDS_CONFIRMATION, the watcher prints a tmux message or desktop notification.

## Classification Strategy
- Use OpenRouter API (keys from `.env`) with a standard prompt: given pane snapshot text, output JSON `{state, summary, actions_needed}`.
- A no-LLM fallback (if keys missing) can base decisions on simple regexes (presence of shell prompt, Codex approval text, etc.).
- Maintain per-CLI classifier packs stored under `design/classifier_packs/<cli>.yml` that define:
  - prompt snippets or regex cues for READY (idle prompt detected + no trailing `...` continuations)
  - BUSY heuristics (progress bars, `%` complete, `> Task:` banners)
  - NEEDS_CONFIRMATION patterns (e.g., `Allow? (y/N)`, `Press ENTER to continue`)
  - ERROR indicators (tracebacks, `ERR`, non-zero exit summaries)
  - few-shot examples pulled directly from recorded panes (Codex idle prompt, Claude summary screen, Gemini completion screen)
  These packs let each CLI encode its own regex/keyword knowledge without hard-coding everything in the watcher.

### State Definitions (Watcher + Classifier Contract)
- **READY** – latest snapshot matches a CLI-specific idle regex (from the classifier pack) and contains no running-progress keywords; watchers treat READY as “safe to accept a new command.”
- **BUSY** – snapshot shows active output (diff detected within last stability window) or matches progress indicators; watchers keep polling until stability threshold is satisfied.
- **NEEDS_CONFIRMATION** – snapshot matches explicit confirmation prompts (regex from the CLI pack) or the classifier explicitly returns this state; watcher triggers notifications.
- **ERROR** – classifier detects stack traces, `Traceback`, `Exception`, or CLI pack error regexes; watcher surfaces summary and actions_needed.

If the no-LLM fallback is active, the watcher loads the same `classifier_packs/<cli>.yml` cues to make deterministic decisions.

## Implementation Plan
1. **Watcher Daemon (`conductor pty watch`)**
   - Implement `app/services/pty_watcher.py` that runs as a separate long-lived process, enumerates tmux windows, and polls them.
   - For each PTY, keep `last_snapshot`, `last_change_ts`, `stable_count`, and current status, and write results under `.workers/<id>/status.json`.
   - Daemon owns `.workers/<id>` lifecycle: create when first seeing a PTY, delete when its tmux window disappears.
2. **Classifier Wrapper**
   - Utility that takes stripped snapshot text + PTY metadata and returns the structured state.
   - Handles API retries, timeouts, and JSON parsing errors.
3. **Status Store + Display**
   - Persist per-PTY status files plus a global sqlite cache (`.workers/status.db`) so `conductor pty status`, the tmux status-line script, and other tools can read without talking to the daemon directly.
   - Recommended schema:
     - `ptys(id TEXT PRIMARY KEY, tmux_session TEXT, tmux_window TEXT, cwd TEXT, cli_type TEXT)`
     - `status(id TEXT PRIMARY KEY REFERENCES ptys(id), state TEXT, summary TEXT, actions_needed TEXT, last_snapshot_hash TEXT, last_change_ts INTEGER, last_polled_ts INTEGER, stable_count INTEGER)`
     - `status_history(id TEXT, ts INTEGER, state TEXT, summary TEXT)` for optional tailing.
   - Add tmux status-line script (`tmux set -g status-right '#(conductor pty status --short)'`).
   - Implement `conductor pty status` (full listing) and `conductor pty tail <id>` to show recap/logs; these CLIs read from the cache.
4. **Creation Command**
   - `conductor pty create <dir>` → `tmux new-window -c <dir> -n worker-<uuid>` plus notify the watcher (e.g., via filesystem flag or `tmux display-message`) so it begins tracking immediately.
5. **Switch Helper (optional)**
   - `conductor pty switch worker-X` → `tmux switch-client -t worker-X` (for users unfamiliar with tmux).
6. **Notifications**
   - When state transitions READY→BUSY or BUSY→READY, the watcher logs and optionally triggers `tmux display-message` or `osascript` notifications.

## Open Questions
- How to handle PTYs that aren’t Codex (plain bash, Gemini, Claude). Need classifier examples for each.
- When classifier says NEEDS_CONFIRMATION, should we auto-send `y` for certain tools or just notify the user?
- How to detect/cleanup PTYs that were closed (remove from status list) beyond the daemon’s filesystem cleanup (e.g., clear orphaned status files on startup).

## Next Steps
1. Build the watcher module that polls tmux windows every 5s and emits status JSON/logs.
2. Implement `conductor pty create` and `conductor pty status` commands (CLI helpers around tmux).
3. Wire tmux status line to show `[name: STATE]` entries (update script whenever status cache changes).
4. Expand classifier prompt with examples for READY/BUSY/NEEDS_CONFIRMATION/ERROR.
5. Test end-to-end by creating two PTYs (e.g., Codex and bash), running a long command, and watching the status updates.
