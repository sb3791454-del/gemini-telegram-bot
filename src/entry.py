"""
Cloudflare Python Worker - Sultan Assistant Platform Entrypoint
Handles HTTP request routing, health checks, webhook setup, and update dispatching.
"""

import json
import logging
from urllib.parse import urlparse, parse_qs
from js import Response, Headers, fetch, Object
from pyodide.ffi import to_js

from config.settings import Settings
from telegram.client import TelegramClient
from ai.gemini_client import GeminiClient
from router.message_router import dispatch_telegram_update

# Configure root worker logger
logger = logging.getLogger("worker")
logger.setLevel(logging.INFO)

def json_response(data: dict, status: int = 200) -> Response:
    """Helper to construct JSON HTTP Response for Cloudflare Workers."""
    headers = to_js(
        {
            "Content-Type": "application/json; charset=utf-8",
            "Access-Control-Allow-Origin": "*",
        },
        dict_converter=Object.fromEntries,
    )
    options = to_js(
        {"status": status, "headers": headers},
        dict_converter=Object.fromEntries,
    )
    return Response.new(json.dumps(data, ensure_ascii=False), options)

def text_response(text: str, status: int = 200) -> Response:
    """Helper to construct plain text HTTP Response for Cloudflare Workers."""
    headers = to_js(
        {
            "Content-Type": "text/plain; charset=utf-8",
            "Access-Control-Allow-Origin": "*",
        },
        dict_converter=Object.fromEntries,
    )
    options = to_js(
        {"status": status, "headers": headers},
        dict_converter=Object.fromEntries,
    )
    return Response.new(text, options)

async def async_http_request(url: str, method: str = "GET", headers: dict | None = None, body: str | None = None):
    """Native asynchronous HTTP request wrapper using Cloudflare Workers JavaScript fetch."""
    opts = {"method": method}
    if headers:
        opts["headers"] = headers
    if body is not None:
        opts["body"] = body
    
    js_opts = to_js(opts, dict_converter=Object.fromEntries)
    resp = await fetch(url, js_opts)
    return resp

async def on_fetch(request, env):
    """Cloudflare Python Worker primary fetch handler."""
    method = request.method
    parsed_url = urlparse(request.url)
    path = parsed_url.path.rstrip("/")
    if not path:
        path = "/"
        
    query_params = parse_qs(parsed_url.query)
    settings = Settings(env)

    # 1. Diagnostic Health Endpoint: GET /health (Safe: exposes zero secrets or IDs)
    if path == "/health" and method == "GET":
        return json_response({
            "status": "ok",
            "service": "sultan-assistant",
            "runtime": "cloudflare-python-worker",
            "active_model": settings.gemini_model,
            "private_mode": settings.is_private_mode_enabled,
            "env_configured": {
                "TELEGRAM_BOT_TOKEN": bool(settings.telegram_bot_token),
                "GEMINI_API_KEY": bool(settings.gemini_api_key),
                "WEBHOOK_SECRET": bool(settings.webhook_secret),
                "SETUP_SECRET": bool(settings.setup_secret),
                "ALLOWED_USER_IDS": settings.is_private_mode_enabled,
                "GEMINI_MODEL": bool(getattr(env, "GEMINI_MODEL", None)),
            }
        })

    # 2. Root Overview Endpoint: GET /
    if path == "/" and method == "GET":
        return text_response(
            f"🤖 Sultan Assistant is active on Cloudflare Python Workers!\n"
            f"Active Model: {settings.gemini_model}\n"
            f"Access Mode: {'Enforcing Whitelist' if settings.is_private_mode_enabled else 'Locked (No Allowed Users Configured)'}\n\n"
            "Endpoints:\n"
            "- GET /health       : System and configuration status\n"
            "- GET /set_webhook  : Register Telegram webhook\n"
            "- POST /webhook     : Incoming Telegram updates endpoint"
        )

    # 3. Secure Webhook Setup Endpoint: GET or POST /set_webhook
    if path == "/set_webhook":
        if not settings.telegram_bot_token:
            return json_response({"ok": False, "error": "TELEGRAM_BOT_TOKEN is not configured."}, status=500)

        # Enforce SETUP_SECRET protection if configured
        if settings.setup_secret:
            req_secret = query_params.get("secret", [""])[0]
            if req_secret != settings.setup_secret:
                return json_response({"ok": False, "error": "Unauthorized: Invalid or missing secret parameter."}, status=401)

        custom_url = query_params.get("url", [""])[0]
        if custom_url:
            webhook_target = custom_url
        else:
            origin = f"{parsed_url.scheme}://{parsed_url.netloc}"
            webhook_target = f"{origin}/webhook"

        telegram_client = TelegramClient(settings.telegram_bot_token, async_http_request)
        try:
            tg_data = await telegram_client.set_webhook(webhook_target, secret_token=settings.webhook_secret)
            return json_response({
                "setup_status": "completed",
                "webhook_url": webhook_target,
                "secret_token_used": bool(settings.webhook_secret),
                "telegram_response": tg_data
            })
        except Exception as e:
            return json_response({"ok": False, "error": str(e)}, status=500)

    # 4. Telegram Webhook Updates Endpoint: POST /webhook (or POST /)
    if (path == "/webhook" or path == "/") and method == "POST":
        if not settings.telegram_bot_token or not settings.gemini_api_key:
            return json_response({"ok": False, "error": "Bot token or Gemini API key is not configured."}, status=500)

        # Validate Telegram Secret Token header if WEBHOOK_SECRET is set
        if settings.webhook_secret:
            header_secret = request.headers.get("x-telegram-bot-api-secret-token")
            if header_secret != settings.webhook_secret:
                return json_response({"ok": False, "error": "Forbidden: Secret token mismatch."}, status=403)

        try:
            body_str = await request.text()
            if not body_str:
                return json_response({"ok": True, "note": "Empty body"})
            update = json.loads(body_str)
            
            telegram_client = TelegramClient(settings.telegram_bot_token, async_http_request)
            gemini_client = GeminiClient(settings.gemini_api_key, settings.gemini_model, async_http_request)
            
            await dispatch_telegram_update(update, settings, telegram_client, gemini_client)
            return json_response({"ok": True})
        except Exception as e:
            logger.error(f"Error processing webhook update: {e}")
            return json_response({"ok": False, "error": str(e)}, status=500)

    return json_response({"error": "Not Found", "path": path}, status=404)
