#!/usr/bin/env bash
cd /home/hatch/workspace/flip-the-switch/runtime/agent
export HOME=/home/hatch
export INTAKE_PROXY="${https_proxy:-}"
echo $$ > agent.pid
exec ../venv/bin/python intake_agent.py >> agent.log 2>&1
