#!/usr/bin/env bash
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
if ! command -v poetry >/dev/null 2>&1; then
  echo "FAIL poetry not found in PATH"
  exit 1
fi
echo "== Agent Safe Devcontainer Self-Audit =="
whoami; id -u
test ! -e /var/run/docker.sock && echo "PASS no docker.sock" || echo "FAIL docker.sock present"
if command -v capsh >/dev/null 2>&1; then capsh --print | grep -q "Current: =" && echo "PASS caps dropped" || echo "CHECK caps"; fi
grep -q "NoNewPrivs:.*1" /proc/$$/status && echo "PASS nnp=1" || echo "FAIL nnp!=1"
touch /bin/_rotest 2>/dev/null && echo "FAIL /bin writable" || echo "PASS /bin not writable"
poetry run python - <<'PY'
import os, tempfile
targets=[("/", False), ("/tmp", True), ("/var/tmp", True)]
run_dir="/run"
run_should=os.access(run_dir, os.W_OK | os.X_OK)
targets.append((run_dir, run_should))
for p, should in targets:
    ok=True
    try:
        d=tempfile.mkdtemp(dir=p); open(os.path.join(d,"t"),"w").write("x")
    except Exception:
        ok=False
    print(("PASS" if ok==should else "FAIL"), "write @", p, "=", ok)
PY
for f in /run/secrets/*.key; do
  [[ -f "$f" ]] || { echo "WARN missing $f"; continue; }
  [[ -w "$f" ]] && echo "FAIL $f writable" || echo "PASS $f RO"
done
getent hosts example.com >/dev/null 2>&1 && echo "PASS DNS" || echo "FAIL DNS"
poetry run python - <<'PY'
import urllib.request
try:
    urllib.request.urlopen("https://example.com", timeout=5).read(1)
    print("PASS HTTPS")
except Exception as e:
    print("FAIL HTTPS", e)
PY
