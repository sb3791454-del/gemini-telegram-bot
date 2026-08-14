"""Asynchronous Google Gemini REST API Client."""

import json
import logging
from ai.prompts_builder import build_text_payload, build_vision_payload
from config.prompts import FALLBACK_ERROR_TEXT, IMAGE_ERROR_TEXT, DEFAULT_VISION_PROMPT

logger = logging.getLogger("worker.ai")

class GeminiClient:
    """Handles communication with Google's Gemini API."""
    def __init__(self, api_key: str, default_model: str, http_fetch_fn):
        self.api_key = api_key
        self.default_model = default_model
        self.fetch_fn = http_fetch_fn
        self.base_url = "https://generativelanguage.googleapis.com/v1beta/models"

    async def generate_text(self, prompt: str, model_name: str | None = None) -> str:
        """Sends a text prompt to Gemini and returns the generated text response."""
        active_model = model_name or self.default_model
        url = f"{self.base_url}/{active_model}:generateContent?key={self.api_key}"
        payload = build_text_payload(prompt)
        headers = {"Content-Type": "application/json"}
        
        try:
            resp = await self.fetch_fn(url, method="POST", headers=headers, body=json.dumps(payload))
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
                logger.error(f"Gemini API error ({active_model}): {data['error']}")
                if err_msg:
                    return f"⚠️ Gemini API Error: {err_msg}"
                    
        except Exception as e:
            logger.error(f"Network or parsing error calling Gemini text: {e}")
            
        return FALLBACK_ERROR_TEXT

    async def generate_vision(self, image_bytes: bytes, caption: str | None = None, model_name: str | None = None) -> str:
        """Sends an image + caption to Gemini and returns the multimodal analysis."""
        active_model = model_name or self.default_model
        url = f"{self.base_url}/{active_model}:generateContent?key={self.api_key}"
        effective_caption = caption if caption else DEFAULT_VISION_PROMPT
        payload = build_vision_payload(image_bytes, effective_caption)
        headers = {"Content-Type": "application/json"}
        
        try:
            resp = await self.fetch_fn(url, method="POST", headers=headers, body=json.dumps(payload))
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
                logger.error(f"Gemini Vision API error ({active_model}): {data['error']}")
                if err_msg:
                    return f"⚠️ Gemini API Vision Error: {err_msg}"
                    
        except Exception as e:
            logger.error(f"Network or parsing error calling Gemini vision: {e}")
            
        return IMAGE_ERROR_TEXT
