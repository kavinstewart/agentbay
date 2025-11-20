#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

SENTINEL_START = "<<<AGENT_RESULT_START>>>"
SENTINEL_END = "<<<AGENT_RESULT_END>>>"


def main() -> None:
    if len(sys.argv) < 3:
        print("Usage: tool_runner.py <tool_name> <spec_path>", file=sys.stderr)
        sys.exit(1)
    tool = sys.argv[1]
    spec_path = Path(sys.argv[2])
    spec = json.loads(spec_path.read_text())
    if tool == "codex":
        run_codex_cli(spec)
        return
    if tool in {"claude", "gemini"}:
        result = run_coder_tool(tool, spec)
    elif tool == "critic_llm":
        result = run_critic_tool(spec)
    else:
        raise SystemExit(f"Unknown tool {tool}")
    print(SENTINEL_START)
    print(json.dumps(result))
    print(SENTINEL_END)


def run_codex_cli(spec: dict[str, Any]) -> None:
    spec_json = json.dumps(spec, indent=2)
    prompt = f"""
You are running inside the PTY-based conductor as the Codex CLI worker.
Specification (JSON):
{spec_json}

Instructions:
- Treat the spec above as the source of truth for what work to perform.
- Edit any referenced files relative to the current working directory.
- Summarize the work you performed.
- When finished, output exactly once the following sentinel block:
<<<AGENT_RESULT_START>>>
<JSON_SUMMARY>
<<<AGENT_RESULT_END>>>
- Replace `<JSON_SUMMARY>` with actual JSON containing at least the keys `status`, `summary`, and `changed_files`, plus any optional metadata you deem helpful.
- The JSON must be valid and may include any additional fields you deem useful.
- Do not print the sentinels anywhere else.
- Ensure the summary text describes the work you performed and `changed_files` lists the files you touched.
- Emit `<JSON_SUMMARY>` as a single line with no literal newline characters.
""".strip()

    cmd = [
        "codex",
        "exec",
        "--skip-git-repo-check",
        "--sandbox",
        "workspace-write",
        "--full-auto",
        "-",
    ]
    result = subprocess.run(cmd, input=prompt, capture_output=True, text=True, check=True)
    stdout = result.stdout
    stderr = result.stderr
    start = stdout.find(SENTINEL_START)
    end = stdout.find(SENTINEL_END)
    if start == -1 or end == -1 or end <= start:
        print(stdout, end="")
        if stderr:
            print(stderr, file=sys.stderr)
        raise SystemExit("Codex output missing sentinels")
    payload = stdout[start + len(SENTINEL_START) : end].strip()
    compact_payload = " ".join(payload.split())
    parsed = json.loads(compact_payload)
    before = stdout[:start]
    after = stdout[end + len(SENTINEL_END) :]
    sys.stdout.write(before)
    sys.stdout.write(after)
    sys.stdout.write("\n" + SENTINEL_START + "\n")
    sys.stdout.write(json.dumps(parsed) + "\n")
    sys.stdout.write(SENTINEL_END + "\n")
    sys.stdout.flush()
    if stderr:
        sys.stderr.write(stderr)


def run_coder_tool(tool: str, spec: dict[str, Any]) -> dict[str, Any]:
    workspace = Path.cwd()
    design_path = workspace / "design.md"
    design_path.parent.mkdir(parents=True, exist_ok=True)
    if not design_path.exists():
        design_path.write_text("# Design Draft\n\n")
    content = design_path.read_text()
    iteration = spec.get("context", {}).get("iteration", "?")
    section = spec.get("description", "Updated design section")
    instructions = spec.get("instructions", "")
    new_section = f"\n\n## Iteration {iteration} ({tool})\n\n{instructions}\n"
    content += new_section
    design_path.write_text(content)
    return {
        "status": "ok",
        "summary": f"Updated design via {tool} with iteration {iteration}",
        "changed_files": ["design.md"],
    }


def run_critic_tool(spec: dict[str, Any]) -> dict[str, Any]:
    workspace = Path.cwd()
    design_path = workspace / spec.get("design_file", "design.md")
    text = design_path.read_text() if design_path.exists() else ""
    words = len(text.split())
    heading_count = text.count("#")
    score = min(10, 5 + (words // 150) + heading_count)
    issues = []
    if words < 200:
        issues.append("Design is too short; expand each section with more depth.")
    if "testing" not in text.lower():
        issues.append("Add a section about testing and validation.")
    return {
        "status": "ok",
        "score": score,
        "issues": issues,
        "summary": "Automated critic evaluation",
    }


if __name__ == "__main__":
    main()
