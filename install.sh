#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PREFIX="${EVERRUN_PREFIX:-$HOME/.local/share/everrun-agent}"
AGENT="auto"
PROFILE="default"
NON_INTERACTIVE=0
UNINSTALL=0

usage() {
  cat <<'EOF'
Usage: ./install.sh [--prefix PATH] [--agent auto|none|hermes] [--profile NAME]
                    [--non-interactive] [--upgrade] [--uninstall]
EOF
}

while (($#)); do
  case "$1" in
    --prefix) PREFIX="$2"; shift 2 ;;
    --agent) AGENT="$2"; shift 2 ;;
    --profile) PROFILE="$2"; shift 2 ;;
    --non-interactive) NON_INTERACTIVE=1; shift ;;
    --upgrade) shift ;;
    --uninstall) UNINSTALL=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

case "$AGENT" in auto|none|hermes) ;; *) echo "Invalid --agent: $AGENT" >&2; exit 2 ;; esac
if [[ ! "$PROFILE" =~ ^[A-Za-z0-9_-]+$ ]]; then
  echo "Invalid --profile: $PROFILE" >&2
  exit 2
fi

VENV="$PREFIX/venv"
STATE="$PREFIX/state"
REPORT="$PREFIX/install-report.json"

if ((UNINSTALL)); then
  if [[ "$AGENT" == "hermes" || ( "$AGENT" == "auto" && -x "$VENV/bin/everrun" && -x "$(command -v hermes 2>/dev/null || true)" ) ]]; then
    "$VENV/bin/everrun" integrate hermes --profile "$PROFILE" --uninstall || true
  fi
  rm -rf "$VENV"
  rm -f "$REPORT"
  printf 'EverRun runtime removed. Mission state preserved at %s\n' "$STATE"
  exit 0
fi

PYTHON="${PYTHON:-$(command -v python3 || true)}"
if [[ -z "$PYTHON" ]]; then
  echo "Python 3.11+ not found." >&2
  exit 1
fi
"$PYTHON" - <<'PY'
import sys
if sys.version_info < (3, 11):
    raise SystemExit("EverRun requires Python 3.11+")
PY

mkdir -p "$PREFIX" "$STATE"
chmod 700 "$PREFIX" "$STATE" 2>/dev/null || true
if [[ ! -x "$VENV/bin/python" ]]; then
  "$PYTHON" -m venv "$VENV"
fi
"$VENV/bin/python" -m pip install --disable-pip-version-check --upgrade pip >/dev/null
"$VENV/bin/python" -m pip install --disable-pip-version-check --upgrade "$ROOT[mcp]" >/dev/null

SELECTED="$AGENT"
if [[ "$SELECTED" == "auto" ]]; then
  if command -v hermes >/dev/null 2>&1; then SELECTED="hermes"; else SELECTED="none"; fi
fi
if [[ "$SELECTED" == "hermes" && "${EVERRUN_SKIP_AGENT_INTEGRATION:-0}" != "1" ]]; then
  "$VENV/bin/everrun" integrate hermes --profile "$PROFILE" >/dev/null
fi

"$VENV/bin/everrun" doctor --agent "$SELECTED" --profile "$PROFILE" --state-dir "$STATE" > "$REPORT"
"$VENV/bin/python" - "$REPORT" <<'PY'
import json, pathlib, sys
report = json.loads(pathlib.Path(sys.argv[1]).read_text())
if not report["ready"]:
    for name, check in report["checks"].items():
        if not check["ok"]:
            print(f"FAIL {name}: {check['detail']}\n  {check['hint']}", file=sys.stderr)
    raise SystemExit(20)
print(f"READY — EverRun is installed (agent={report['agent']}, profile={report['profile']})")
PY
printf 'CLI: %s\nReport: %s\n' "$VENV/bin/everrun" "$REPORT"
