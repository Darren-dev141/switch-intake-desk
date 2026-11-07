# Intake Desk — a Switch agent that files your link inbox

**Built for the [Flip the Switch](https://wemakedevs.org/hackathons/switch) hackathon (WeMakeDevs × SandboxAQ).**
Track: Best Personal or Creative Workflow.

## The problem

I run a link-intake system by hand: every article, repo, or tool I find gets
evaluated (what is it, does it fit my work, steal / adopt / log / skip),
written up, and filed in a ledger — but only after I approve the verdict.
Doing that by hand, in a chat with myself across five apps, is slow and the
queue rots.

## What Intake Desk does

Intake Desk moves the whole loop into team chat, with **Switch** as the
connective tissue between me and the agent:

1. I drop a link into the **#intake-desk** channel in Mattermost and mention
   `@intake-desk`.
2. Switch's Mattermost bridge delivers the message to my agent as an
   *addressed event* over the Switch agent protocol (WebSocket).
3. The agent fetches the link (GitHub API + README for repos), asks my local
   **Laya** decision server to pick the verdict bucket (STEAL / ADOPT /
   LOG + WATCH / LOG / SKIP — Laya decides, per my standing Laya-first rule),
   and has a worker LLM draft the summary prose from the fetched evidence.
4. The agent posts the draft evaluation **back into the channel** and waits.
5. I reply **GO** or **NO** in chat. On GO — and only on GO — the filing is
   appended to my real intake ledger (`second-brain/ledger/tweets.md`) and
   index, and the Laya decision is logged with its outcome. On NO, the staged
   draft is discarded.

A human and an agent completing a real task together, in chat, with the
human's approval as a hard gate — that's the workflow Switch was built for.

## How Switch is used

- **Self-hosted Switch** (switch-core 0.31.0, from
  [sandbox-quantum/switch](https://github.com/sandbox-quantum/switch)) with
  its bundled **Mattermost** (11.9.0) as the collaboration bridge — no
  external workspace needed.
- **One room**: `intake-desk` (Switch room, bridged to the Mattermost channel
  of the same name), created by the agent through the `create_room`
  operation; the bridge adds the human owner automatically.
- **One agent**: `intake-desk`, a `custom-python` always-on agent registered
  through the Switch gateway API with a registration API key, owned by the
  gateway admin whose identity Switch links to the human's Mattermost
  account (so owner addressing works: the agent only acts when *I* address
  it).
- **Protocol**: raw agent protocol — no Console, no framework. The agent
  holds a WebSocket to `/agents/{id}/connection/ws`, answers the server's
  2-second pings *before* processing events (evaluations run in tasks so a
  one-minute evaluation never starves the ping loop — a lesson learned the
  hard way), and acts through operations (`post_message`, `create_room`,
  `list_rooms`, …) over HTTP.
- **Gateway dashboard** runs at the core's `/` for agent/room management.

## Layout of this repo

- `agent/intake_agent.py` — the whole agent (~360 lines, Python + aiohttp).
  Uses the Laya client from my local stack when present and degrades to a
  flagged default verdict without it; posts drafts through Switch ops.
- `agent/start-agent.sh` — launcher (agent credentials live in
  `agent/agent.json`, created at registration, never committed).
- `deploy/` — how the stack was actually run for this entry: **natively, no
  Docker** (see below). These scripts carry the build machine's own paths
  and are kept as the run record; to run the stack yourself, use the
  upstream compose route in "Reproduce it" below.

## Running it

The upstream route is the standalone Docker Compose in the Switch repo. This
entry ran the same stack **without Docker**, because the build VM has no
usable container runtime (no `CAP_NET_ADMIN`/userns mappings for dockerd —
verified the slow way). The native equivalent, service for service:

| Compose service | Native equivalent here |
| --- | --- |
| `postgres` | PostgreSQL 16 from the image's own rootfs, run under its musl loader |
| `switch` | `switch-core` 0.31.0 in a `uv` venv — `deploy/run-core.sh` |
| `mattermost` | Mattermost 11.9.0 binary from its image rootfs — `deploy/run-mm.sh` |
| `setup` | The repo's own `deploy/shared_resources/setup.py`, run against the native endpoints |

With Docker available, prefer the upstream compose file; the workflow, room,
and agent are identical either way.

Agent setup after the stack is up:

```bash
# 1. In the gateway dashboard, create a registration-type API key.
# 2. Register the agent:
curl -X POST $SWITCH_URL/agents -H "Authorization: Bearer $REG_KEY" \
  -d '{"name":"intake-desk","connector_type":"custom-python",
       "integration_profile":{"connection_model":"always_on",
       "message_exchange":true}}'
# 3. Save the returned {id, api_key} as agent/agent.json (mode 600).
# 4. Run it:
agent/start-agent.sh
# 5. In Mattermost, open #intake-desk and drop a link with @intake-desk.
```

## Reproduce it

What a fresh clone needs, in order:

1. **The Switch stack.** This repo is the agent, not the stack. Run the
   stack from the upstream Switch repo's standalone Docker Compose
   (switch-core + Mattermost + Postgres). The `deploy/` scripts in this
   repo are the record of how the entry ran natively on the build machine;
   they reference that machine's paths and are not a portable installer.
2. **Python deps.** `python3 -m venv .venv && .venv/bin/pip install -r
   agent/requirements.txt` (aiohttp is the only hard dependency).
3. **Register the agent** (steps 1–3 under "Agent setup" above) and save
   the returned credentials as `agent/agent.json`. Without that file the
   agent exits immediately and tells you why.
4. **Run it:** `agent/start-agent.sh`. Configuration is by environment:
   `SWITCH_URL` (default `http://127.0.0.1:8000`) and `OMNI_URL` for the
   drafting model endpoint.
5. **Optional pieces degrade honestly.** Without Darren's Laya decision
   server (or any Jev-compatible client for `POST /choose`), verdicts fall
   back to a flagged default instead of crashing. Filings approved with GO
   append to `INTAKE_LEDGER`/`INTAKE_INDEX` if set; otherwise to Darren's
   ledger paths when that tree exists, or to `agent/ledger/` in the clone.

Verified from a fresh clone (agent side, steps 2–3): the agent imports and
starts cleanly with no Laya present, verdicts degrade to the flagged
default, a GO filing lands in the clone's `agent/ledger/`, and a missing
`agent.json` stops it with a clear message instead of a traceback.

## What I'd tell the next builder

- Register your agent with a **gateway-admin-owned** registration key, not
  the bootstrap key — bootstrap-registered agents are owned by a separate
  "Agent Bootstrap" account, and owner-only addressing will refuse your
  human.
- The ping cadence is real: reply to pings from the receive loop and never
  let work block it.
- `taken_over` eviction is final; a plain socket close is not — handle them
  differently.

## License note

Intake Desk's own code is MIT. Switch itself is Apache 2.0 + Commons Clause
(see the upstream repo) — nothing here sells Switch or a derivative.
