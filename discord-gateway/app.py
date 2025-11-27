from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
import os
import httpx
import nacl.signing
import nacl.exceptions

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
    Parse a metadata-style custom_id, e.g.:

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
    if len(parts) == 2:
        meta["reference"] = parts[1]
    elif len(parts) == 3:
        meta["reference"] = parts[1]
        meta["action"] = parts[2]
    return meta


def resolve_webhook(meta: dict) -> str:
    """
    Choose n8n webhook based on metadata.

    - Look for wf= or workflow=
    - If mapped, return WEBHOOK_MAP[wf]
    - Otherwise use DEFAULT_N8N_WEBHOOK_URL
    """
    workflow, reference, action = meta.get("workflow"), meta.get("reference"), meta.get("action")
    if workflow and workflow in WEBHOOK_MAP:
        return WEBHOOK_MAP[workflow]
    elif (workflow and reference) and f"{workflow}:{reference}" in WEBHOOK_MAP:
            return WEBHOOK_MAP[f"{workflow}:{reference}"]
    elif (workflow and reference and action) and f"{workflow}:{reference}:{action}" in WEBHOOK_MAP:
            return WEBHOOK_MAP[f"{workflow}:{reference}:{action}"]
    return N8N_WEBHOOK_URL


# ─────────────────────────────
# Routes
# ─────────────────────────────

@app.post("/webhook/discord/interactions")
async def discord_interactions(request: Request):
    # 1) Verify Discord signature
    sig = request.headers.get("X-Signature-Ed25519")
    ts = request.headers.get("X-Signature-Timestamp")
    if not sig or not ts:
        raise HTTPException(status_code=401, detail="Missing signature headers")

    raw_body = await request.body()

    if not verify_signature(sig, ts, raw_body):
        raise HTTPException(status_code=401, detail="Invalid request signature")

    payload = await request.json()

    # 2) Handle PING (type 1)
    if payload.get("type") == 1:
        return JSONResponse({"type": 1})

    # 3) Any other interaction (components, slash commands, etc.)
    data = payload.get("data") or {}
    custom_id = data.get("custom_id") or ""

    meta = parse_custom_id(custom_id)
    target_webhook = resolve_webhook(meta)

    forward_body = {
        "interaction": payload,
        "meta": meta,
    }

    # Forward to n8n (fire-and-forget, minimal error handling)
    async with httpx.AsyncClient() as client:
        try:
            await client.post(
                target_webhook,
                json=forward_body,
                timeout=5.0,
            )
        except Exception as e:
            # Replace with proper logging if desired
            print(f"Error forwarding to n8n ({target_webhook}): {e}")

    # 4) Generic ACK to Discord so it doesn't timeout
    # Type 5 = deferred response (no immediate content required)
    return JSONResponse({"type": 5})
