from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
import os
import httpx
import nacl.signing
import nacl.exceptions
import json
import time

# ─────────────────────────────
# Config
# ─────────────────────────────

DISCORD_PUBLIC_KEY = os.environ["DISCORD_PUBLIC_KEY"]  # from Discord dev portal

N8N_WEBHOOK_URL = os.environ.get("N8N_WEBHOOK_URL", "http://n8n:5678/webhook/discord/interactions/")

# Mapping between workflow tags and n8n webhooks
WEBHOOK_MAP = {
    "deploy_project:approve_request": N8N_WEBHOOK_URL + "3d0ded88-cde7-4a2a-8421-a0806d4ebc80",
}

verify_key = nacl.signing.VerifyKey(bytes.fromhex(DISCORD_PUBLIC_KEY))

app = FastAPI()


# ─────────────────────────────
# Logging helper
# ─────────────────────────────

def log(event: str, data: dict | None = None):
    """
    Lightweight structured logger.
    Output is JSON for easy consumption through Docker logs or external log collectors.
    """
    entry = {
        "ts": time.time(),
        "event": event,
    }
    if data:
        entry["data"] = data
    print(json.dumps(entry), flush=True)


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


def parse_custom_id(custom_id: str) -> dict:
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
    meta: dict[str, str] = {}

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


def resolve_webhook(meta: dict) -> str:
    """
    Resolve the target n8n webhook:
    1. workflow
    2. workflow:reference
    3. workflow:reference:action
    4. default fallback
    """
    wf = meta.get("workflow")
    ref = meta.get("reference")
    act = meta.get("action")

    # Match least → most specific
    keys_to_try = []
    if wf:
        keys_to_try.append(wf)
    if wf and ref:
        keys_to_try.append(f"{wf}:{ref}")
    if wf and ref and act:
        keys_to_try.append(f"{wf}:{ref}:{act}")

    for key in keys_to_try:
        if key in WEBHOOK_MAP:
            return WEBHOOK_MAP[key]

    return N8N_WEBHOOK_URL


# ─────────────────────────────
# Routes
# ─────────────────────────────

@app.post("/webhook/discord/interactions")
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

    payload = await request.json()

    # Logged inbound payload (without flooding)
    log("interaction_received", {
        "id": payload.get("id"),
        "type": payload.get("type"),
        "custom_id": payload.get("data", {}).get("custom_id"),
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
