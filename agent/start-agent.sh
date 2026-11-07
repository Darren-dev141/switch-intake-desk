#!/usr/bin/env bash
# Start the Intake Desk agent from this repo, wherever it was cloned.
cd "$(dirname "$0")"
if [ -x ../.venv/bin/python ]; then PY=../.venv/bin/python;
elif [ -x .venv/bin/python ]; then PY=.venv/bin/python;
else PY=python3; fi
export INTAKE_PROXY="${INTAKE_PROXY:-${https_proxy:-}}"
echo $$ > agent.pid
exec "$PY" intake_agent.py >> agent.log 2>&1
