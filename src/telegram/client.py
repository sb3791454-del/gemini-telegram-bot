"""Asynchronous Telegram Bot REST API Client compatible with Cloudflare Workers."""

import json
import logging
from src.telegram.formatting import chunk_message

logger = logging.getLogger("worker.telegram")

class TelegramClient:
    """Handles communication with the Telegram Bot API."""
    def __init__(self, bot_token: str, http_fetch_fn):
        self.bot_token = bot_token
        self.fetch_fn = http_fetch_fn
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
        self.file_base_url = f"https://api.telegram.org/file/bot{bot_token}"

    async def send_chat_action(self, chat_id: int, action: str = "typing"):
        """Sends a chat action (e.g. typing) to indicate processing."""
        url = f"{self.base_url}/sendChatAction"
        body = json.dumps({"chat_id": chat_id, "action": action})
        headers = {"Content-Type": "application/json"}
        try:
            await self.fetch_fn(url, method="POST", headers=headers, body=body)
        except Exception as e:
            logger.error(f"Error sending chat action: {e}")

    async def send_message(self, chat_id: int, text: str, parse_mode: str = "Markdown"):
        """Sends a message, automatically splitting if it exceeds safe length limits."""
        url = f"{self.base_url}/sendMessage"
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
            resp = await self.fetch_fn(url, method="POST", headers=headers, body=body)
            
            # If Markdown parsing fails (e.g. unclosed markdown tags in LLM output), fallback to plain text
            if hasattr(resp, "status") and resp.status != 200 and parse_mode:
                payload.pop("parse_mode", None)
                body = json.dumps(payload)
                await self.fetch_fn(url, method="POST", headers=headers, body=body)

    async def get_file_bytes(self, file_id: str) -> bytes:
        """Retrieves file metadata from Telegram and downloads the raw bytes."""
        get_file_url = f"{self.base_url}/getFile?file_id={file_id}"
        resp = await self.fetch_fn(get_file_url, method="GET")
        resp_text = await resp.text()
        data = json.loads(resp_text)
        
        if not data.get("ok"):
            raise RuntimeError(f"Failed to get file metadata from Telegram: {resp_text}")
            
        file_path = data["result"]["file_path"]
        download_url = f"{self.file_base_url}/{file_path}"
        
        file_resp = await self.fetch_fn(download_url, method="GET")
        arr_buf = await file_resp.arrayBuffer()
        return bytes(arr_buf.to_py())

    async def set_webhook(self, webhook_url: str, secret_token: str | None = None) -> dict:
        """Registers the Telegram webhook URL with optional secret token."""
        url = f"{self.base_url}/setWebhook"
        payload = {
            "url": webhook_url,
            "allowed_updates": ["message"]
        }
        if secret_token:
            payload["secret_token"] = secret_token
            
        headers = {"Content-Type": "application/json"}
        resp = await self.fetch_fn(url, method="POST", headers=headers, body=json.dumps(payload))
        resp_text = await resp.text()
        return json.loads(resp_text)
