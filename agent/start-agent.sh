#!/usr/bin/env bash
cd /home/hatch/workspace/flip-the-switch/runtime/agent
export INTAKE_PROXY="${https_proxy:-}"
exec ../venv/bin/python intake_agent.py >> agent.log 2>&1
