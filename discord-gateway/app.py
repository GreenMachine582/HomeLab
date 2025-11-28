from __future__ import annotations

import os
import json
import time
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
import nacl.signing
import nacl.exceptions
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse


# ─────────────────────────────
# Config
# ─────────────────────────────

DISCORD_PUBLIC_KEY = os.environ["DISCORD_PUBLIC_KEY"]  # from Discord dev portal

N8N_DOMAIN = os.environ.get("N8N_DOMAIN", "http://n8n:5678").rstrip("/")
DISCORD_WEBHOOK_PATH = os.environ.get("DISCORD_WEBHOOK_PATH", "discord/interactions").strip("/")

WEBHOOK_MAP_FILE_PATH = Path(os.environ.get("WEBHOOK_MAP_FILE", "data/webhook_map.json"))

N8N_WEBHOOK_SECRET = os.environ.get("N8N_WEBHOOK_SECRET")
if not N8N_WEBHOOK_SECRET:
    print(
        "❌ N8N_WEBHOOK_SECRET is not set. This gateway requires it to call n8n.",
        flush=True,
    )
    raise SystemExit(1)

HEADERS: Dict[str, str] = {
    "Content-Type": "application/json",
    "X-N8N-Webhook-Auth": N8N_WEBHOOK_SECRET,
}

verify_key = nacl.signing.VerifyKey(bytes.fromhex(DISCORD_PUBLIC_KEY))

app = FastAPI()


# ─────────────────────────────
# Logging helper
# ─────────────────────────────

_WEBHOOK_MAP_CACHE: Dict[str, Any] = {}
_WEBHOOK_MAP_MTIME: Optional[float] = None


def log(event: str, data: Optional[Dict[str, Any]] = None) -> None:
    """
    Lightweight structured logger.
    Output is JSON for easy consumption through Docker logs or external log collectors.
    """
    entry: Dict[str, Any] = {
        "ts": time.time(),
        "event": event,
    }
    if data:
        entry["data"] = data
    print(json.dumps(entry), flush=True)


def _load_webhook_map_if_needed() -> None:
    """Load or reload webhook_map.json if it changed on disk."""
    global _WEBHOOK_MAP_CACHE, _WEBHOOK_MAP_MTIME

    try:
        stat = WEBHOOK_MAP_FILE_PATH.stat()
    except FileNotFoundError:
        if _WEBHOOK_MAP_MTIME is not None:
            # It used to exist, now it's gone
            log("webhook_map_missing", {"path": str(WEBHOOK_MAP_FILE_PATH)})
        _WEBHOOK_MAP_CACHE = {}
        _WEBHOOK_MAP_MTIME = None
        return

    mtime = stat.st_mtime
    if _WEBHOOK_MAP_MTIME is not None and mtime == _WEBHOOK_MAP_MTIME:
        # No change
        return

    # (Re)load the file
    try:
        with WEBHOOK_MAP_FILE_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            raise ValueError("Root of webhook map JSON must be an object")

        _WEBHOOK_MAP_CACHE = data
        _WEBHOOK_MAP_MTIME = mtime
        log(
            "webhook_map_loaded",
            {
                "path": str(WEBHOOK_MAP_FILE_PATH),
                "entries": len(_WEBHOOK_MAP_CACHE),
            },
        )
    except Exception as e:
        log(
            "webhook_map_load_error",
            {"path": str(WEBHOOK_MAP_FILE_PATH), "error": str(e)},
        )
        # On error, keep previous cache (if any), do not blow it away


def get_webhook_map() -> Dict[str, Any]:
    _load_webhook_map_if_needed()
    return _WEBHOOK_MAP_CACHE


# ─────────────────────────────
# Helpers
# ─────────────────────────────

def verify_signature(signature: str, timestamp: str, body: bytes) -> bool:
    """Verify Discord's Ed25519 signature."""
    try:
        message = timestamp.encode() + body
        verify_key.verify(message, bytes.fromhex(signature))
        return True
    except (nacl.exceptions.BadSignatureError, ValueError):
        return False


def parse_custom_id(custom_id: str) -> Dict[str, str]:
    """
    Parse a metadata-style custom_id:
        "workflow:reference:action"
    Example:
        "deploy_project:approve_request:reject"
    Returns:
        {
            "workflow": "deploy_project",
            "reference": "approve_request",
            "action": "reject",
        }
    """
    meta: Dict[str, str] = {}

    if not custom_id:
        return meta

    parts = custom_id.split(":")
    if not parts:
        return meta

    meta["workflow"] = parts[0]
    if len(parts) >= 2:
        meta["reference"] = parts[1]
    if len(parts) >= 3:
        meta["action"] = parts[2]

    return meta


def resolve_webhook(meta: Dict[str, str]) -> str:
    """
    Resolve the target n8n webhook URL based on metadata and webhook_map.json.

    Try keys in order:
      1. workflow
      2. workflow:reference
      3. workflow:reference:action

    If found, value can be:
      - { "env": "PROD"/"TEST", "id": "<uuid>" }
      - "<uuid>" (string, assumes PROD)

    Builds:
      <N8N_DOMAIN>/webhook[/-test]/<DISCORD_WEBHOOK_PATH>/<id>
    """
    wf = meta.get("workflow")
    ref = meta.get("reference")
    act = meta.get("action")

    webhook_map = get_webhook_map()

    keys_to_try = []
    if wf:
        keys_to_try.append(wf)
    if wf and ref:
        keys_to_try.append(f"{wf}:{ref}")
    if wf and ref and act:
        keys_to_try.append(f"{wf}:{ref}:{act}")

    for key in keys_to_try:
        if key not in webhook_map:
            continue

        value = webhook_map[key]

        env = "PROD"
        webhook_id = None

        if isinstance(value, dict):
            env = str(value.get("env", "PROD")).upper()
            webhook_id = value.get("id") or value.get("uuid")
        else:
            # Backwards-compatible: treat as string id
            webhook_id = str(value)

        if not webhook_id:
            log(
                "webhook_map_invalid_entry",
                {"key": key, "value": value},
            )
            continue

        prefix = "webhook" if env == "PROD" else "webhook-test"
        return f"{N8N_DOMAIN}/{prefix}/{DISCORD_WEBHOOK_PATH}/{webhook_id}"

    # Fallback: default prod URL without specific ID
    log("webhook_not_resolved", {"meta": meta})
    return f"{N8N_DOMAIN}/webhook/{DISCORD_WEBHOOK_PATH}"


# ─────────────────────────────
# Routes
# ─────────────────────────────

@app.post(f"/webhook/{DISCORD_WEBHOOK_PATH}")
@app.post(f"/webhook/{DISCORD_WEBHOOK_PATH}/")
@app.post(f"/webhook-test/{DISCORD_WEBHOOK_PATH}")
@app.post(f"/webhook-test/{DISCORD_WEBHOOK_PATH}/")
async def discord_interactions(request: Request):
    # Extract signature headers
    sig = request.headers.get("X-Signature-Ed25519")
    ts = request.headers.get("X-Signature-Timestamp")
    if not sig or not ts:
        log("missing_signature_headers")
        raise HTTPException(status_code=401, detail="Missing signature headers")

    raw_body = await request.body()

    # Verify signature
    if not verify_signature(sig, ts, raw_body):
        log("invalid_signature", {"signature": sig, "timestamp": ts})
        raise HTTPException(status_code=401, detail="Invalid request signature")

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception as e:
        log("json_parse_error", {"error": str(e)})
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    # Logged inbound payload (without flooding)
    log("interaction_received", {
        "id": payload.get("id"),
        "type": payload.get("type"),
        "custom_id": (payload.get("data") or {}).get("custom_id"),
    })

    # Handle PING
    if payload.get("type") == 1:
        log("ping_received")
        return JSONResponse({"type": 1})

    # All other interactions
    data = payload.get("data") or {}
    custom_id = data.get("custom_id") or ""

    meta = parse_custom_id(custom_id)

    log("metadata_parsed", meta)

    target_webhook = resolve_webhook(meta)

    log("webhook_resolved", {
        "custom_id": custom_id,
        "meta": meta,
        "target_webhook": target_webhook,
    })

    forward_body = {
        "interaction": payload,
        "meta": meta,
    }

    # Forward to n8n webhook
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                target_webhook,
                json=forward_body,
                headers=HEADERS,
                timeout=5.0,
            )
        log("forward_success", {
            "target_webhook": target_webhook,
            "meta": meta,
        })
    except Exception as e:
        log("forward_error", {
            "error": str(e),
            "target_webhook": target_webhook,
            "meta": meta,
        })

    # Discord ACK
    log("discord_ack_sent")
    return JSONResponse({"type": 5})
