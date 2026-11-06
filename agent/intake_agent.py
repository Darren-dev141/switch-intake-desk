#!/usr/bin/env python3
"""Intake Desk — a custom Switch agent (agent protocol, no Console).

Darren drops a link in the Intake Desk room (Mattermost, bridged by Switch).
The agent fetches it, evaluates it (Laya picks the verdict bucket, an
Omnirouter worker model drafts the prose), stages an intake filing in
Darren's ledger format, and posts the summary back to the room. The filing
only lands in the real ledger when Darren replies GO in the room.

Protocol: Switch agent protocol (docs.switchagents.ai/switch-rooms/
internals/agent-protocol.md) — WebSocket events + HTTP operations.
"""
import asyncio
import json
import os
import re
import sys
import time
import traceback
import uuid
from pathlib import Path

import aiohttp

sys.path.insert(0, os.path.expanduser("~/workspace/laya"))
import client as laya  # noqa: E402  (Darren's Laya decision server client)

HERE = Path(__file__).parent
STATE_F = HERE / "state.json"
PENDING_DIR = HERE / "pending"
PENDING_DIR.mkdir(exist_ok=True)

SWITCH = "http://127.0.0.1:8000"
OMNI = "http://127.0.0.1:8799/v1/chat/completions"
LEDGER = Path(os.path.expanduser("~/workspace/second-brain/ledger/tweets.md"))
INDEX = Path(os.path.expanduser("~/workspace/second-brain/INDEX.md"))
TOOLS_LOG = Path(os.path.expanduser("~/workspace/notes/x-tools-log.md"))
ROOM_NAME = "intake-desk"
VERDICTS = ["STEAL", "ADOPT", "LOG + WATCH", "LOG", "SKIP"]

AGENT = json.loads((HERE / "agent.json").read_text())
AGENT_ID = AGENT["id"]
API_KEY = AGENT["api_key"]
HDRS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def load_state():
    if STATE_F.exists():
        return json.loads(STATE_F.read_text())
    return {"connection_id": str(uuid.uuid4()), "cursor": 0, "generation": None,
            "room_id": None, "pending": {}}


def save_state(st):
    STATE_F.write_text(json.dumps(st, indent=1))


STATE = load_state()


async def op(session, name, args, conn=True):
    headers = dict(HDRS)
    if conn:
        headers["X-Switch-Connection-Id"] = STATE["connection_id"]
    async with session.post(f"{SWITCH}/agents/{AGENT_ID}/ops/{name}",
                            headers=headers, json=args) as r:
        data = await r.json(content_type=None)
        if r.status != 200:
            raise RuntimeError(f"op {name} -> {r.status}: {data}")
        return data.get("result", data)


async def post_message(session, room_id, body):
    return await op(session, "post_message", {"body": body})


# ---------- evaluation ----------

URL_RE = re.compile(r"https?://[^\s<>\]\)\"']+")


async def fetch_evidence(url):
    """Return (title, text) evidence for a URL. GitHub repos via the API."""
    m = re.match(r"https?://github\.com/([^/]+)/([^/#?\s]+)", url)
    timeout = aiohttp.ClientTimeout(total=30)
    proxy = os.environ.get("INTAKE_PROXY") or os.environ.get("https_proxy") or None
    async with aiohttp.ClientSession(timeout=timeout) as s:
        if m:
            api = f"https://api.github.com/repos/{m.group(1)}/{m.group(2).rstrip('/')}"
            async with s.get(api, headers={"Accept": "application/vnd.github+json"}, proxy=proxy) as r:
                if r.status == 200:
                    d = await r.json()
                    text = (f"GitHub repo {d.get('full_name')}: {d.get('description')}\n"
                            f"stars={d.get('stargazers_count')} forks={d.get('forks_count')} "
                            f"language={d.get('language')} license={(d.get('license') or {}).get('spdx_id')} "
                            f"created={d.get('created_at')} pushed={d.get('pushed_at')} "
                            f"topics={d.get('topics')}")
                    try:
                        async with s.get(api + "/readme",
                                         headers={"Accept": "application/vnd.github.raw"},
                                         proxy=proxy) as rr:
                            if rr.status == 200:
                                readme = await rr.text(errors="replace")
                                text += "\nREADME excerpt:\n" + readme[:2500]
                    except Exception:
                        pass
                    return d.get("full_name") or url, text
        async with s.get(url, headers={"User-Agent": "intake-desk/1.0"}, proxy=proxy) as r:
            html = await r.text(errors="replace")
        title_m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
        title = re.sub(r"\s+", " ", title_m.group(1)).strip() if title_m else url
        text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S | re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return title, text[:6000]


def laya_verdict_sync(title, evidence):
    """Laya-first: the local decision server picks the verdict bucket."""
    try:
        state = (f"New intake link for Darren Foote Jr. (UMBC IS grad, job hunting, builds "
                 f"agent systems: Laya decision server, Omnirouter, ONE BLOCK simulation, "
                 f"grid forecasting). Title: {title}. Evidence: {evidence[:1500]}")
        options = {
            "STEAL": "a pattern/idea worth taking and making ours now",
            "ADOPT": "an open-source tool worth adopting into the stack now",
            "LOG + WATCH": "interesting and adjacent, but no socket in active work yet; watch it",
            "LOG": "record it for the record; no action implied",
            "SKIP": "not relevant to Darren's work",
        }
        res = laya.choose(state, options,
                          instructions="Which intake verdict best fits this item for Darren?")
        return res["choice"], float(res.get("confidence", 0)), res.get("decision_id")
    except Exception as e:  # Laya down -> caller falls back, and says so
        log(f"laya failed: {e}")
        return None, 0.0, None


async def llm_draft(title, evidence, verdict):
    prompt = (
        "You are the Intake Desk agent in Darren Foote Jr.'s team chat. A link was dropped "
        "for intake evaluation.\n"
        f"URL title: {title}\nEvidence:\n{evidence[:3500]}\n\n"
        f"The verdict (already decided by the Laya decision server) is: {verdict}.\n"
        "Write, in plain English:\n"
        "1) WHAT IT IS — 2 sentences max, only facts supported by the evidence.\n"
        "2) WHY THIS VERDICT — 1-2 sentences tied to Darren's active work "
        "(job search, Laya/Omnirouter agent stack, ONE BLOCK, grid forecasting).\n"
        "3) WATCH-OUT — one line: license catch, maturity, or nothing-found (say 'none seen').\n"
        "No hype, no invented facts. If the evidence is thin, say so."
    )
    timeout = aiohttp.ClientTimeout(total=90)
    async with aiohttp.ClientSession(timeout=timeout) as s:
        async with s.post(OMNI, json={"model": "mechanical",
                                      "messages": [{"role": "user", "content": prompt}],
                                      "max_tokens": 500}) as r:
            d = await r.json()
            return d["choices"][0]["message"]["content"].strip()


def next_intake_number():
    nums = [int(n) for n in re.findall(r"^## #(\d+)", LEDGER.read_text(errors="replace"), re.M)]
    return (max(nums) + 1) if nums else 1


async def handle_url(session, room_id, url, sender_name):
    await post_message(session, room_id, f"On it — evaluating {url}")
    title, evidence = await fetch_evidence(url)
    verdict, conf, decision_id = await asyncio.to_thread(laya_verdict_sync, title, evidence)
    fallback = verdict is None
    if fallback:
        verdict = "LOG"
    draft = await llm_draft(title, evidence, verdict)
    number = next_intake_number()
    today = time.strftime("%b %-d, %Y") if os.name != "nt" else time.strftime("%b %d, %Y")
    filing = (f"\n## #{number} — {title} — via Intake Desk (Switch room), "
              f"sent by Darren {today} — verdict {verdict}\n\n"
              f"**Source:** {url}\n\n{draft}\n\n"
              f"Filed by the Intake Desk agent after Darren's GO in the Switch room. "
              f"Laya verdict: {verdict} (confidence {conf:.2f}"
              f"{', LAYA FALLBACK — verdict defaulted to LOG' if fallback else ''}).\n")
    low_conf = (not fallback) and conf < 0.35
    (PENDING_DIR / f"{room_id}.md").write_text(filing)
    STATE["pending"][room_id] = {"number": number, "url": url, "verdict": verdict,
                                 "decision_id": decision_id}
    save_state(STATE)
    await post_message(session, room_id,
                       f"**Intake draft #{number} — {title}**\n\n{draft}\n\n"
                       f"**Verdict: {verdict}** (Laya confidence {conf:.2f}"
                       f"{' — Laya unreachable, defaulted' if fallback else ''}"
                       f"{' — LOW CONFIDENCE: provisional, your call carries it' if low_conf else ''}).\n"
                       f"{sender_name}, reply **GO** to file it in the ledger, or **NO** to discard.")


async def handle_go(session, room_id, yes):
    pend = STATE["pending"].pop(room_id, None)
    if not pend:
        await post_message(session, room_id, "Nothing pending in this room.")
        save_state(STATE)
        return
    f = PENDING_DIR / f"{room_id}.md"
    if yes:
        filing = f.read_text()
        with LEDGER.open("a") as fh:
            fh.write(filing)
        with INDEX.open("a") as fh:
            fh.write(f"\n- #{pend['number']} — {pend['url']} — {pend['verdict']} "
                     f"(filed by Intake Desk after Darren's GO in Switch room)\n")
        if pend.get("decision_id"):
            try:
                laya.outcome(pend["decision_id"], "accepted",
                             note=f"filed as intake #{pend['number']} after GO in Switch room")
            except Exception:
                pass
        await post_message(session, room_id,
                           f"Filed as intake #{pend['number']} in the ledger. Done.")
    else:
        if pend.get("decision_id"):
            try:
                laya.outcome(pend["decision_id"], "rejected", note="discarded by Darren in Switch room")
            except Exception:
                pass
        await post_message(session, room_id, "Discarded — nothing filed.")
    f.unlink(missing_ok=True)
    save_state(STATE)


# ---------- connection ----------

async def ensure_room(session):
    if STATE.get("room_id"):
        return STATE["room_id"]
    rooms = await op(session, "list_rooms", {}, conn=False)
    items = rooms if isinstance(rooms, list) else rooms.get("rooms", [])
    for r in items:
        if r.get("name") == ROOM_NAME:
            STATE["room_id"] = r["id"]
            save_state(STATE)
            return r["id"]
    res = await op(session, "create_room",
                   {"name": ROOM_NAME,
                    "description": "Drop a link; the Intake Desk agent evaluates it and "
                                   "files the intake on Darren's GO.",
                    "agent_names": ["intake-desk"]}, conn=False)
    room_id = res.get("id") or res.get("room_id")
    STATE["room_id"] = room_id
    save_state(STATE)
    log(f"created room {room_id}")
    return room_id


async def run():
    timeout = aiohttp.ClientTimeout(total=None, sock_read=None)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        room_id = await ensure_room(session)
        log(f"room: {room_id}")
        while True:
            try:
                result = await connect_loop(session, room_id)
                if result == "TAKEN_OVER":
                    log("taken over by another stream; exiting (protocol: final)")
                    return
            except Exception as e:
                log(f"connection dropped: {e!r}; reconnecting in 3s")
                traceback.print_exc()
                await asyncio.sleep(3)


async def connect_loop(session, room_id):
    params = {"connection_id": STATE["connection_id"], "scope": "all",
              "filter": "all", "rooms": room_id}
    if STATE.get("cursor"):
        params["start_from"] = str(STATE["cursor"])
    if STATE.get("generation") is not None:
        params["expected_generation"] = str(STATE["generation"])
    ws_url = f"{SWITCH.replace('http', 'ws')}/agents/{AGENT_ID}/connection/ws"
    async with session.ws_connect(ws_url, headers={"Authorization": f"Bearer {API_KEY}"},
                                  params=params, heartbeat=None) as ws:
        log("websocket open")
        async for msg in ws:
            if msg.type != aiohttp.WSMsgType.TEXT:
                continue
            frame = json.loads(msg.data)
            ftype = frame.get("type") or frame.get("event")
            if ftype == "ping":
                await ws.send_json({"type": "pong", "cursor": STATE["cursor"]})
                continue
            if ftype == "connection_state":
                STATE["rooms"] = frame.get("rooms")
                STATE["generation"] = frame.get("generation")
                if frame.get("cursor"):
                    STATE["cursor"] = frame["cursor"]
                save_state(STATE)
                log(f"connection_state rooms={frame.get('rooms')} cursor={frame.get('cursor')}")
                continue
            if ftype == "evicted":
                log(f"evicted: {frame}")
                code = (frame.get("data") or {}).get("code") or frame.get("code")
                if code == "taken_over":
                    return "TAKEN_OVER"
                raise RuntimeError("evicted")
            data = frame.get("data") or {}
            seq = data.get("sequence") or frame.get("id")
            if isinstance(seq, int) and seq > STATE["cursor"]:
                STATE["cursor"] = seq
                save_state(STATE)
            if data.get("type") != "message" or data.get("room_id") != room_id:
                continue
            payload = data.get("payload") or {}
            if not payload.get("addressed"):
                continue
            mid = payload.get("message_id")
            seen = STATE.setdefault("seen", [])
            if mid and mid in seen:
                continue
            if mid:
                seen.append(mid)
                STATE["seen"] = seen[-50:]
                save_state(STATE)
            # Handle in a task: the receive loop must keep answering pings
            # (2s cadence) while an evaluation runs for ~a minute.
            asyncio.create_task(dispatch(session, room_id, payload))
    raise ConnectionError("websocket closed by server")


async def dispatch(session, room_id, payload):
    body = (payload.get("body") or "").strip()
    body = re.sub(r"^@intake-desk[:,]?\s*", "", body, flags=re.I)
    sender = payload.get("sender") or ""
    sender_name = payload.get("sender_name") or "there"
    if "switch-agent" in sender or sender_name == "Intake Desk":
        return  # never react to ourselves
    log(f"addressed message from {sender_name}: {body[:80]!r}")
    try:
        m = URL_RE.search(body)
        low = body.lower()
        if m:
            await handle_url(session, room_id, m.group(0), sender_name)
        elif low in ("go", "go.", "yes", "file it", "go!"):
            await handle_go(session, room_id, True)
        elif low in ("no", "no.", "discard", "drop it"):
            await handle_go(session, room_id, False)
        else:
            await post_message(session, room_id,
                               "Drop a link and I'll evaluate it and draft the intake. "
                               "When a draft is waiting, reply GO to file it or NO to discard it.")
    except Exception as e:
        traceback.print_exc()
        try:
            await post_message(session, room_id, f"That one failed on my side: {e}")
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(run())
