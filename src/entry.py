"""
Cloudflare Python Worker - Gemini Telegram Bot
Webhook-based Telegram Bot running serverlessly on Cloudflare Workers Free Tier.
Powered by Google Gemini 3.1 Flash-Lite.
"""

import json
import base64
import logging
from urllib.parse import urlparse, parse_qs
from js import Response, Headers, fetch, Object
from pyodide.ffi import to_js

# Configure logging
logger = logging.getLogger("worker")
logger.setLevel(logging.INFO)

# Default Gemini model supported on current Google AI Studio free tier
DEFAULT_GEMINI_MODEL = "gemini-3.1-flash-lite"

# Constants & Prompts
WELCOME_TEXT = (
    "👋 *السلام علیکم! Welcome to Gemini AI Bot!*\n\n"
    "میں Google Gemini سے چلنے والا ایک تیز رفتار کلاؤڈ اسسٹنٹ ہوں۔\n\n"
    "✨ *خصوصیات (Features):*\n"
    "• *سوال و جواب (Q&A):* کسی بھی موضوع پر سوالات کے تفصیلی اور درست جوابات۔\n"
    "• *تصویر کا تجزیہ (Image Vision):* کوئی بھی تصویر بھیجیں اور اس کے بارے میں پوچھیں۔\n"
    "• *ترجمہ اور تحریر (Writing & Translation):* اردو، انگریزی اور دیگر زبانوں میں مضامین اور کوڈنگ۔\n\n"
    "📌 *کمانڈز (Commands):*\n"
    "/help - رہنمائی اور طریقہ کار\n"
    "/clear یا /reset - نئی گفتگو شروع کریں\n\n"
    "بس اپنا سوال یا تصویر یہاں بھیجیں!"
)

HELP_TEXT = (
    "📖 *بوٹ استعمال کرنے کا طریقہ (Help Guide):*\n\n"
    "1. *ٹیکسٹ میسج:* کوئی بھی سوال یا بات لکھ کر بھیجیں۔\n"
    "2. *تصویر:* تصویر بھیجیں اور ساتھ کیپشن لکھیں (مثلاً: 'اس تصویر کی وضاحت کریں')۔\n"
    "3. *نئی شروعات:* /clear لکھ کر نئی گفتگو کا آغاز کر سکتے ہیں۔\n"
)

RESET_TEXT = "🔄 *چیٹ ری سیٹ ہو گئی ہے۔* اب آپ نیا سوال پوچھ سکتے ہیں۔"

FALLBACK_ERROR_TEXT = "⚠️ معذرت، جواب تیار کرنے میں کوئی تکنیکی مسئلہ پیش آیا۔ براہ کرم دوبارہ کوشش کریں۔"
IMAGE_ERROR_TEXT = "⚠️ تصویر کا تجزیہ کرنے میں مسئلہ پیش آیا۔ براہ کرم دوبارہ کوشش کریں۔"

# Helper for constructing JSON HTTP Response
def json_response(data, status=200):
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

# Helper for text HTTP Response
def text_response(text, status=200):
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

# Async HTTP fetch wrapper using Cloudflare Workers JavaScript fetch API
async def async_http_request(url, method="GET", headers=None, body=None):
    opts = {"method": method}
    if headers:
        opts["headers"] = headers
    if body is not None:
        opts["body"] = body
    
    js_opts = to_js(opts, dict_converter=Object.fromEntries)
    resp = await fetch(url, js_opts)
    return resp

# Telegram API: send chat action (e.g. typing)
async def send_chat_action(bot_token: str, chat_id: int, action: str = "typing"):
    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendChatAction"
        body = json.dumps({"chat_id": chat_id, "action": action})
        headers = {"Content-Type": "application/json"}
        await async_http_request(url, method="POST", headers=headers, body=body)
    except Exception as e:
        logger.error(f"Error sending chat action: {e}")

# Telegram API: split text into Telegram-compliant chunks
def chunk_message(text: str, max_length: int = 4000):
    chunks = []
    while len(text) > max_length:
        split_at = text.rfind("\n", 0, max_length)
        if split_at == -1:
            split_at = max_length
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip()
    if text:
        chunks.append(text)
    return chunks

# Telegram API: send message
async def send_telegram_message(bot_token: str, chat_id: int, text: str, parse_mode: str = "Markdown"):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    chunks = chunk_message(text)
    
    for chunk in chunks:
        payload = {
            "chat_id": chat_id,
            "text": chunk,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
            
        headers = {"Content-Type": "application/json"}
        body = json.dumps(payload)
        resp = await async_http_request(url, method="POST", headers=headers, body=body)
        
        # If Markdown fails (e.g. malformed markdown formatting from LLM), fallback to plain text
        if resp.status != 200 and parse_mode:
            payload.pop("parse_mode", None)
            body = json.dumps(payload)
            await async_http_request(url, method="POST", headers=headers, body=body)

# Telegram API: get file details and download bytes
async def get_telegram_file_bytes(bot_token: str, file_id: str):
    # Step 1: getFile metadata
    get_file_url = f"https://api.telegram.org/bot{bot_token}/getFile?file_id={file_id}"
    resp = await async_http_request(get_file_url, method="GET")
    resp_text = await resp.text()
    data = json.loads(resp_text)
    
    if not data.get("ok"):
        raise Exception(f"Failed to get file metadata from Telegram: {resp_text}")
        
    file_path = data["result"]["file_path"]
    download_url = f"https://api.telegram.org/file/bot{bot_token}/{file_path}"
    
    # Step 2: Download raw file bytes
    file_resp = await async_http_request(download_url, method="GET")
    arr_buf = await file_resp.arrayBuffer()
    return bytes(arr_buf.to_py())

# Gemini REST API: Generate text response
async def call_gemini_text(gemini_api_key: str, prompt: str, model_name: str = DEFAULT_GEMINI_MODEL) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={gemini_api_key}"
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt}
                ]
            }
        ]
    }
    headers = {"Content-Type": "application/json"}
    body = json.dumps(payload)
    
    resp = await async_http_request(url, method="POST", headers=headers, body=body)
    resp_text = await resp.text()
    data = json.loads(resp_text)
    
    if "candidates" in data and len(data["candidates"]) > 0:
        candidate = data["candidates"][0]
        content = candidate.get("content", {})
        parts = content.get("parts", [])
        if parts and "text" in parts[0]:
            return parts[0]["text"]
            
    if "error" in data:
        err_msg = data["error"].get("message", "")
        logger.error(f"Gemini API error ({model_name}): {data['error']}")
        if err_msg:
            return f"⚠️ Gemini API Error: {err_msg}"
        
    return FALLBACK_ERROR_TEXT

# Gemini REST API: Multimodal Image Analysis
async def call_gemini_vision(gemini_api_key: str, image_bytes: bytes, caption: str, model_name: str = DEFAULT_GEMINI_MODEL) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={gemini_api_key}"
    b64_image = base64.b64encode(image_bytes).decode("utf-8")
    
    prompt = caption if caption else "اس تصویر کے بارے میں تفصیل سے بتائیں۔"
    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "inline_data": {
                            "mime_type": "image/jpeg",
                            "data": b64_image
                        }
                    },
                    {
                        "text": prompt
                    }
                ]
            }
        ]
    }
    headers = {"Content-Type": "application/json"}
    body = json.dumps(payload)
    
    resp = await async_http_request(url, method="POST", headers=headers, body=body)
    resp_text = await resp.text()
    data = json.loads(resp_text)
    
    if "candidates" in data and len(data["candidates"]) > 0:
        candidate = data["candidates"][0]
        content = candidate.get("content", {})
        parts = content.get("parts", [])
        if parts and "text" in parts[0]:
            return parts[0]["text"]
            
    if "error" in data:
        err_msg = data["error"].get("message", "")
        logger.error(f"Gemini Vision API error ({model_name}): {data['error']}")
        if err_msg:
            return f"⚠️ Gemini API Vision Error: {err_msg}"
        
    return IMAGE_ERROR_TEXT

# Telegram Webhook Handler
async def handle_telegram_update(update: dict, bot_token: str, gemini_api_key: str, model_name: str = DEFAULT_GEMINI_MODEL):
    message = update.get("message")
    if not message:
        return
        
    chat_id = message.get("chat", {}).get("id")
    if not chat_id:
        return
        
    text = message.get("text", "").strip()
    photo = message.get("photo")
    caption = message.get("caption", "").strip()
    
    # Handle Commands
    if text.startswith("/start"):
        await send_telegram_message(bot_token, chat_id, WELCOME_TEXT, parse_mode="Markdown")
        return
        
    if text.startswith("/help"):
        await send_telegram_message(bot_token, chat_id, HELP_TEXT, parse_mode="Markdown")
        return
        
    if text.startswith("/clear") or text.startswith("/reset"):
        await send_telegram_message(bot_token, chat_id, RESET_TEXT, parse_mode="Markdown")
        return
        
    # Handle Photos
    if photo:
        await send_chat_action(bot_token, chat_id, "typing")
        try:
            # Pick highest resolution photo
            highest_res_photo = photo[-1]
            file_id = highest_res_photo.get("file_id")
            image_bytes = await get_telegram_file_bytes(bot_token, file_id)
            reply = await call_gemini_vision(gemini_api_key, image_bytes, caption, model_name=model_name)
            await send_telegram_message(bot_token, chat_id, reply, parse_mode="")
        except Exception as e:
            logger.error(f"Error handling photo: {e}")
            await send_telegram_message(bot_token, chat_id, IMAGE_ERROR_TEXT, parse_mode="")
        return
        
    # Handle Text Messages
    if text:
        await send_chat_action(bot_token, chat_id, "typing")
        try:
            reply = await call_gemini_text(gemini_api_key, text, model_name=model_name)
            await send_telegram_message(bot_token, chat_id, reply, parse_mode="")
        except Exception as e:
            logger.error(f"Error handling text: {e}")
            await send_telegram_message(bot_token, chat_id, FALLBACK_ERROR_TEXT, parse_mode="")
        return

# Cloudflare Python Worker Entrypoint
async def on_fetch(request, env):
    method = request.method
    parsed_url = urlparse(request.url)
    path = parsed_url.path.rstrip("/")
    if not path:
        path = "/"
        
    query_params = parse_qs(parsed_url.query)
    
    # Extract secrets & settings from env
    bot_token = getattr(env, "TELEGRAM_BOT_TOKEN", None)
    gemini_api_key = getattr(env, "GEMINI_API_KEY", None)
    webhook_secret = getattr(env, "WEBHOOK_SECRET", None)
    setup_secret = getattr(env, "SETUP_SECRET", None)
    gemini_model = getattr(env, "GEMINI_MODEL", None) or DEFAULT_GEMINI_MODEL
    
    # 1. Health check endpoint: GET /health
    if path == "/health" and method == "GET":
        return json_response({
            "status": "ok",
            "service": "gemini-telegram-bot",
            "runtime": "cloudflare-python-worker",
            "model": gemini_model,
            "env_configured": {
                "TELEGRAM_BOT_TOKEN": bool(bot_token),
                "GEMINI_API_KEY": bool(gemini_api_key),
                "WEBHOOK_SECRET": bool(webhook_secret),
                "SETUP_SECRET": bool(setup_secret),
                "GEMINI_MODEL": gemini_model,
            }
        })
        
    # 2. Root endpoint: GET /
    if path == "/" and method == "GET":
        return text_response(
            f"🤖 Gemini Telegram Bot is active on Cloudflare Python Workers!\n"
            f"Active Model: {gemini_model}\n\n"
            "Endpoints:\n"
            "- GET /health       : Check worker and environment health\n"
            "- GET /set_webhook  : Register the Telegram webhook\n"
            "- POST /webhook     : Incoming Telegram updates endpoint"
        )
        
    # 3. Secure Webhook Setup endpoint: GET or POST /set_webhook
    if path == "/set_webhook":
        if not bot_token:
            return json_response({"ok": False, "error": "TELEGRAM_BOT_TOKEN secret is not configured in Worker."}, status=500)
            
        # If SETUP_SECRET is configured in env, require it in ?secret= parameter
        if setup_secret:
            req_secret = query_params.get("secret", [""])[0]
            if req_secret != setup_secret:
                return json_response({"ok": False, "error": "Unauthorized: Invalid or missing secret parameter."}, status=401)
                
        # Determine Webhook URL (default to current origin + /webhook)
        custom_url = query_params.get("url", [""])[0]
        if custom_url:
            webhook_target = custom_url
        else:
            origin = f"{parsed_url.scheme}://{parsed_url.netloc}"
            webhook_target = f"{origin}/webhook"
            
        # Call Telegram setWebhook API
        tg_url = f"https://api.telegram.org/bot{bot_token}/setWebhook"
        tg_payload = {
            "url": webhook_target,
            "allowed_updates": ["message"]
        }
        if webhook_secret:
            tg_payload["secret_token"] = webhook_secret
            
        headers = {"Content-Type": "application/json"}
        resp = await async_http_request(tg_url, method="POST", headers=headers, body=json.dumps(tg_payload))
        tg_res_text = await resp.text()
        try:
            tg_data = json.loads(tg_res_text)
            return json_response({
                "setup_status": "completed",
                "webhook_url": webhook_target,
                "secret_token_used": bool(webhook_secret),
                "telegram_response": tg_data
            })
        except Exception:
            return text_response(tg_res_text, status=resp.status)

    # 4. Telegram Webhook Endpoint: POST /webhook (or POST /)
    if (path == "/webhook" or path == "/") and method == "POST":
        if not bot_token or not gemini_api_key:
            return json_response({"ok": False, "error": "Bot token or Gemini API key is not configured."}, status=500)
            
        # Validate Telegram Secret Token if WEBHOOK_SECRET is set
        if webhook_secret:
            header_secret = request.headers.get("x-telegram-bot-api-secret-token")
            if header_secret != webhook_secret:
                return json_response({"ok": False, "error": "Forbidden: Secret token mismatch."}, status=403)
                
        try:
            body_str = await request.text()
            if not body_str:
                return json_response({"ok": True, "note": "Empty body"})
            update = json.loads(body_str)
            await handle_telegram_update(update, bot_token, gemini_api_key, model_name=gemini_model)
            return json_response({"ok": True})
        except Exception as e:
            logger.error(f"Error in webhook handler: {e}")
            return json_response({"ok": False, "error": str(e)}, status=500)
            
    return json_response({"error": "Not Found", "path": path}, status=404)
