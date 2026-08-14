"""Message chunking, splitting, and formatting utilities for Telegram."""

from src.config.settings import TELEGRAM_SAFE_CHUNK_LIMIT

def chunk_message(text: str, max_length: int = TELEGRAM_SAFE_CHUNK_LIMIT) -> list[str]:
    """Splits a long message into chunks respecting newline boundaries when possible."""
    if not text:
        return []
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
