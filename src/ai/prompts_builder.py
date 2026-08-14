"""Payload builders for Gemini API requests."""

import base64
from typing import Dict, Any

def build_text_payload(prompt: str) -> Dict[str, Any]:
    """Constructs a standard generateContent JSON payload for text."""
    return {
        "contents": [
            {
                "parts": [
                    {"text": prompt}
                ]
            }
        ]
    }

def build_vision_payload(image_bytes: bytes, caption: str, mime_type: str = "image/jpeg") -> Dict[str, Any]:
    """Constructs a multimodal generateContent JSON payload with base64 image data."""
    b64_image = base64.b64encode(image_bytes).decode("utf-8")
    return {
        "contents": [
            {
                "parts": [
                    {
                        "inline_data": {
                            "mime_type": mime_type,
                            "data": b64_image
                        }
                    },
                    {
                        "text": caption
                    }
                ]
            }
        ]
    }
