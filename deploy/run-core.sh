#!/usr/bin/env bash
# Run switch-core natively (equivalent of the standalone stack's `switch` service).
RT="$HOME/workspace/flip-the-switch/runtime"
source "$RT/stack-env.sh"
cd "$RT/app"
# The sandbox's proxy env (bracketed IPv6 no_proxy entries) crashes httpx's
# URL parser; the core only talks to loopback services, so drop proxies.
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY all_proxy
export no_proxy="127.0.0.1,localhost" NO_PROXY="127.0.0.1,localhost"
exec "$RT/venv/bin/python" -m switch_core.main >> "$RT/core.log" 2>&1
