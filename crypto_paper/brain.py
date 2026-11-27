"""Ask Qwen (local Ollama). Any bad or late answer is a 'missed' decision.

Two jobs:
- decide: pick LONG / SHORT / WAIT / CLOSE for each coin (the "Qwen" and "Qwen + journal" accounts).
- veto (v4): the trend rule has proposed trades; Qwen may only TAKE or SKIP each one, by several votes.

The prompts and schemas are part of the written rules: `fingerprint` changes when any of them changes, and a changed
fingerprint starts a fresh record.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.request
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import rules as R

ACTIONS = ("LONG", "SHORT", "WAIT", "CLOSE")
VERDICTS = ("TAKE", "SKIP")
BASE_URL = "http://127.0.0.1:11434"

SYSTEM = (
    "You are Plutus, a crypto trader in a PAPER-MONEY research test (no real money). Every 15 minutes you see live data "
    "for BTC and ETH. The test measures whether your read of the market beats a coin flip, so for every coin listed in "
    "must_pick (coins where you have no open trade and are allowed to open one) you MUST choose LONG (buy) or SHORT (sell "
    "short): the side you think is more likely to reach its profit target before its stop. Being unsure is normal: say "
    "so with a low confidence (0 to 1), but still pick a side; SHORT is as valid as LONG. For a coin where you already "
    "have a trade open: WAIT keeps it, CLOSE exits it now, and the opposite side reverses it. Code sets the size, the "
    f"stop ({R.STOP_ATR} x the 1-hour ATR) and the profit target ({R.TARGET_ATR} x the 1-hour ATR); most trades end at one "
    "of those, which can take hours. Fees are charged on every entry and exit. Code also enforces limits: after any exit "
    f"in a coin, no new trade in that coin for {R.COOLDOWN_MINUTES} minutes; at most {R.MAX_ENTRIES_PER_DAY} new trades a "
    "day; and BTC and ETH in the same direction count as one bet. you_can_open shows which sides each coin can still "
    "open. Use only the numbers given. Reply with JSON only."
)
SCHEMA = {
    "type": "object",
    "properties": {"decisions": {"type": "array", "items": {"type": "object", "properties": {
        "symbol": {"type": "string", "enum": list(R.SYMBOLS)},
        "action": {"type": "string", "enum": list(ACTIONS)},
        "play": {"type": "string", "enum": ["TREND", "FADE", "NONE"]},
        "confidence": {"type": "number"},
        "reason": {"type": "string"}},
        "required": ["symbol", "action", "play", "confidence", "reason"]}}},
    "required": ["decisions"],
}
JOURNAL_NOTE = (
    " You also get your_track_record: counts from your own closed trades in this test, worked out by code. "
    "Use it to avoid repeating what has lost money and to lean on what has worked, but only for groups that show "
    "numbers; groups marked 'too few to judge' are luck. Market data still comes first."
)

VETO_SYSTEM = (
    "You are Plutus, the risk checker in a PAPER-MONEY research test (no real money). A plain rule, the 1-hour trend "
    "rule, wants to open the trades listed under proposed_trades. For each one answer TAKE or SKIP. You cannot open "
    "anything else, and you cannot change the size, the stop or the target: code does that. The rule is right often "
    "enough to be worth following, so TAKE is the normal answer. SKIP only when the facts argue against this trade, for "
    "example: the price is already stretched far from its 1-hour average in the trade's direction; the 4-hour trend "
    "points the other way; a LONG sits right under the 24-hour high or a SHORT right above the 24-hour low; the market "
    "is unusually quiet (noise hits the stop) or unusually wild; funding is extreme against the trade's side. Distances "
    "are in ATRs: 1 ATR is the size of a normal 1-hour move. Use only the facts given. Reply with JSON only."
)
VETO_SCHEMA = {
    "type": "object",
    "properties": {"verdicts": {"type": "array", "items": {"type": "object", "properties": {
        "symbol": {"type": "string", "enum": list(R.SYMBOLS)},
        "verdict": {"type": "string", "enum": list(VERDICTS)},
        "reason": {"type": "string"}},
        "required": ["symbol", "verdict", "reason"]}}},
    "required": ["verdicts"],
}

# ask(system, user, schema, model, think, sample) -> (answer text or None, info). The replay rig swaps in a cached one.
Ask = Callable[[str, str, Dict[str, Any], str, bool, int], Tuple[Optional[str], Dict[str, Any]]]


def fingerprint() -> str:
    """Short hash of everything that shapes a decision: the rule values, the prompts and the answer formats."""
    values = {k: v for k, v in vars(R).items() if k.isupper()}
    blob = json.dumps({"rules": values, "system": SYSTEM, "journal": JOURNAL_NOTE, "schema": SCHEMA,
                       "veto_system": VETO_SYSTEM, "veto_schema": VETO_SCHEMA}, sort_keys=True, default=list)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def model_digest(base_url: str = BASE_URL, model: Optional[str] = None) -> Optional[str]:
    """Ollama's own ID for the model file in use, or None if Ollama does not answer."""
    want = model or R.MODEL
    try:
        with urllib.request.urlopen(f"{base_url}/api/tags", timeout=2) as r:
            for m in json.loads(r.read().decode("utf-8")).get("models", []):
                if want in (m.get("name"), m.get("model")):
                    return str(m.get("digest") or "") or None
    except Exception:
        pass
    return None


def ask_ollama(system: str, user: str, schema: Dict[str, Any], model: str, think: bool = False, sample: int = 0,
               base_url: str = BASE_URL, timeout: float = R.DECISION_TIMEOUT_S) -> Tuple[Optional[str], Dict[str, Any]]:
    body = {"model": model, "stream": False, "think": think, "keep_alive": R.KEEP_ALIVE, "format": schema,
            "options": {"temperature": 0.3, "num_ctx": R.NUM_CTX},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    t0 = time.time()
    try:
        req = urllib.request.Request(f"{base_url}/api/chat", data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = json.loads(r.read().decode("utf-8"))
    except Exception as exc:
        return None, {"seconds": round(time.time() - t0, 2), "error": f"{type(exc).__name__}: {exc}"[:200]}
    info = {"seconds": round(time.time() - t0, 2), "tokens": raw.get("eval_count")}
    if (raw.get("prompt_eval_count") or 0) >= R.NUM_CTX - 8:
        # the question did not fit in the model's window, so part of it was cut off: the answer cannot be trusted
        info["error"] = "the question was too long for the model and was cut off"
        return None, info
    return raw.get("message", {}).get("content", ""), info


def parse(text: str) -> Optional[Dict[str, Dict[str, Any]]]:
    """Strict check. Returns {symbol: decision} for every symbol, or None."""
    try:
        data = json.loads(text)
        out = {}
        for d in data["decisions"]:
            sym, act = d["symbol"], d["action"]
            if sym in R.SYMBOLS and act in ACTIONS:
                out[sym] = {"action": act, "play": d.get("play", "NONE"),
                            "confidence": max(0.0, min(1.0, float(d.get("confidence", 0)))),
                            "reason": str(d.get("reason", ""))[:400]}
        return out if set(out) == set(R.SYMBOLS) else None
    except Exception:
        return None


def parse_veto(text: str, wanted: List[str]) -> Optional[Dict[str, Dict[str, str]]]:
    """Strict check. Returns {symbol: {verdict, reason}} for every proposed symbol, or None."""
    try:
        out = {}
        for v in json.loads(text)["verdicts"]:
            if v["symbol"] in wanted and v["verdict"] in VERDICTS:
                out[v["symbol"]] = {"verdict": v["verdict"], "reason": str(v.get("reason", ""))[:300]}
        return out if set(out) == set(wanted) else None
    except Exception:
        return None


def picker_schema(must_pick: Optional[List[str]], open_coins: List[str]) -> Dict[str, Any]:
    """When every coin must be picked (nothing open, nothing blocked), the answer format itself only allows LONG or
    SHORT, so the model cannot drift back to WAIT. Otherwise the full format, and the runner checks the rest."""
    if must_pick and set(must_pick) == set(R.SYMBOLS) and not open_coins:
        s = json.loads(json.dumps(SCHEMA))
        s["properties"]["decisions"]["items"]["properties"]["action"]["enum"] = ["LONG", "SHORT"]
        return s
    return SCHEMA


def _picker_question(snapshots, positions, track_record, must_pick=None, can_open=None) -> Tuple[str, str]:
    payload: Dict[str, Any] = {"market": snapshots, "your_open_positions": positions,
                               "must_pick": list(must_pick or []), "you_can_open": can_open or {}}
    if track_record is not None:
        payload["your_track_record"] = track_record
    return SYSTEM + (JOURNAL_NOTE if track_record is not None else ""), json.dumps(payload, ensure_ascii=False)


def decide(snapshots: List[Dict[str, Any]], positions: Dict[str, Any], base_url: str = BASE_URL,
           track_record: Optional[Dict[str, Any]] = None, model: Optional[str] = None, think: bool = False,
           ask: Optional[Ask] = None, sample: int = 0, must_pick: Optional[List[str]] = None,
           can_open: Optional[Dict[str, List[str]]] = None) -> Tuple[Optional[Dict], Dict[str, Any]]:
    """Returns (decisions or None, info with timing and any error). track_record given = the journal version.
    must_pick: coins where the model has to choose LONG or SHORT (no open trade, not blocked by a limit)."""
    if must_pick is None:
        must_pick = [s for s in R.SYMBOLS if s not in positions]
    system, user = _picker_question(snapshots, positions, track_record, must_pick, can_open)
    schema = picker_schema(must_pick, list(positions))
    if ask is None:
        content, info = ask_ollama(system, user, schema, model or R.MODEL, think, sample, base_url)
    else:
        content, info = ask(system, user, schema, model or R.MODEL, think, sample)
    if content is None:
        return None, info
    got = parse(content)
    if got is None:
        info["error"] = "answer was not valid JSON with a decision for every coin"
        info["raw"] = content[:300]
    return got, info


def decide_vote(snapshots: List[Dict[str, Any]], positions: Dict[str, Any], votes: int = R.VETO_VOTES, need: int = R.VETO_NEED,
                track_record: Optional[Dict[str, Any]] = None, model: Optional[str] = None, think: bool = False,
                ask: Optional[Ask] = None, base_url: str = BASE_URL) -> Tuple[Optional[Dict], Dict[str, Any]]:
    """Replay arm: the picker asked several times. An action is used only if `need` answers agree; otherwise WAIT."""
    answers, seconds = [], 0.0
    for i in range(votes):
        got, info = decide(snapshots, positions, base_url, track_record, model, think, ask, sample=i)
        seconds += info.get("seconds") or 0.0
        if got:
            answers.append(got)
    if not answers:
        return None, {"seconds": round(seconds, 2), "error": "no valid answer in any vote"}
    out = {}
    for sym in R.SYMBOLS:
        counts: Dict[str, int] = {}
        for a in answers:
            counts[a[sym]["action"]] = counts.get(a[sym]["action"], 0) + 1
        best, n = max(counts.items(), key=lambda kv: kv[1])
        if n >= need:
            first = next(a[sym] for a in answers if a[sym]["action"] == best)
            out[sym] = dict(first, confidence=round(n / votes, 2))
        else:
            out[sym] = {"action": "WAIT", "play": "NONE", "confidence": round(n / votes, 2),
                        "reason": f"the votes did not agree ({counts})"}
    return out, {"seconds": round(seconds, 2), "votes": votes, "valid": len(answers)}


def veto(cards: List[Dict[str, Any]], base_url: str = BASE_URL, votes: int = R.VETO_VOTES, need: int = R.VETO_NEED,
         budget_s: float = R.VETO_BUDGET_S, model: Optional[str] = None, think: bool = False,
         ask: Optional[Ask] = None) -> Tuple[Optional[Dict[str, Dict[str, Any]]], Dict[str, Any]]:
    """The trend rule proposes; Qwen answers TAKE or SKIP, `votes` times. A trade is taken only with `need` TAKEs.

    cards: [{"symbol", "side", "facts"}]. Returns ({symbol: {take, votes_take, votes_skip, reason}}, info), or
    (None, info) when not one vote produced a usable answer (that counts as a missed decision, and nothing is opened).
    A vote that fails or arrives after the time budget counts as SKIP: silence never opens a trade."""
    wanted = [c["symbol"] for c in cards]
    if not wanted:
        return {}, {"seconds": 0.0, "asked": 0, "valid": 0}
    user = json.dumps({"proposed_trades": cards}, ensure_ascii=False)
    use_model = model or R.MODEL
    takes = {s: 0 for s in wanted}
    skips = {s: 0 for s in wanted}
    why_take: Dict[str, str] = {}
    why_skip: Dict[str, str] = {}
    asked = valid = 0
    seconds, t0, last_error = 0.0, time.time(), None
    for i in range(votes):
        if time.time() - t0 > budget_s:
            last_error = last_error or "ran out of time"
            break
        if ask is None:
            # one slow answer must not run past the budget for all the votes together
            content, info = ask_ollama(VETO_SYSTEM, user, VETO_SCHEMA, use_model, think, i, base_url,
                                       timeout=max(2.0, budget_s - (time.time() - t0)))
        else:
            content, info = ask(VETO_SYSTEM, user, VETO_SCHEMA, use_model, think, i)
        asked += 1
        seconds += info.get("seconds") or 0.0
        got = parse_veto(content, wanted) if content is not None else None
        if got is None:
            last_error = info.get("error") or "answer was not valid JSON with a verdict for every proposed trade"
        else:
            valid += 1
            for s, v in got.items():
                if v["verdict"] == "TAKE":
                    takes[s] += 1
                    why_take.setdefault(s, v["reason"])
                else:
                    skips[s] += 1
                    why_skip.setdefault(s, v["reason"])
        left = votes - asked
        if all(takes[s] >= need or takes[s] + left < need for s in wanted):
            break                                   # every trade is already decided: no need to ask again
    info = {"seconds": round(seconds, 2), "asked": asked, "valid": valid, "votes": votes, "need": need}
    if valid == 0:
        info["error"] = last_error or "no valid answer"
        return None, info
    out = {}
    for s in wanted:
        take = takes[s] >= need
        out[s] = {"take": take, "votes_take": takes[s], "votes_skip": skips[s],
                  "reason": (why_take.get(s) if take else why_skip.get(s)) or
                            ("not enough TAKE votes" if not take else "")}
    return out, info
