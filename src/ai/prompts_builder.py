"""Payload builders and memory context formatters for Gemini API requests."""

import re
import base64
from typing import Dict, Any, List

# Common stop words in English and Roman/Urdu to filter out for keyword matching
STOP_WORDS = {
    "a", "an", "the", "in", "on", "at", "to", "for", "of", "with", "by", "from",
    "is", "are", "was", "were", "be", "been", "being", "have", "has", "had", "do",
    "does", "did", "and", "or", "but", "if", "so", "as", "it", "its", "i", "me",
    "my", "myself", "we", "our", "you", "your", "he", "him", "his", "she", "her",
    "they", "them", "their", "what", "which", "who", "whom", "this", "that", "these",
    "those", "am", "how", "why", "where", "when", "can", "could", "should", "would",
    "will", "shall", "may", "might", "must", "about", "into", "through", "after",
    "before", "above", "below", "up", "down", "out", "off", "over", "under", "again",
    "further", "then", "once", "here", "there", "all", "any", "both", "each", "few",
    "more", "most", "other", "some", "such", "no", "nor", "not", "only", "own",
    "same", "than", "too", "very", "s", "t", "just", "don", "shouldn", "now", "tell",
    "give", "please", "help", "show", "know", "think",
    # Common Urdu roman/script tokens
    "کیا", "ہے", "ہیں", "تھا", "تھی", "تھے", "کا", "کی", "کے", "کو", "سے", "میں",
    "پر", "اور", "یا", "کہ", "یہ", "وہ", "تو", "نہ", "نہیں", "اب", "جب", "ہم",
    "آپ", "تم", "میرا", "میری", "میرے", "مجھے", "بتاؤ", "کرو", "کریں"
}

def extract_keywords(text: str) -> set:
    """Extracts meaningful lowercase search tokens from text."""
    if not text:
        return set()
    words = re.findall(r'\b[\w\u0600-\u06FF]+\b', text.lower())
    return {w for w in words if len(w) > 2 and w not in STOP_WORDS}

def select_relevant_memories(
    query: str,
    memories: List[Dict[str, Any]],
    max_memories: int = 5
) -> List[Dict[str, Any]]:
    """
    Selects top relevant memories based on lightweight keyword token overlap.
    Runs entirely in pure Python with zero external API calls or vector databases.
    """
    if not query or not memories:
        return []

    query_tokens = extract_keywords(query)
    if not query_tokens:
        return []

    scored_memories = []
    for mem in memories:
        content = mem.get("content", "")
        mem_tokens = extract_keywords(content)
        overlap = query_tokens.intersection(mem_tokens)
        
        if not overlap:
            continue

        score = float(len(overlap))
        mtype = mem.get("memory_type", "fact").lower()
        if mtype in ("goal", "preference", "instruction"):
            score += 0.5  # Slight boost for intent-defining memories

        scored_memories.append((score, mem))

    # Sort by score descending, then by creation date/ID descending
    scored_memories.sort(key=lambda x: (x[0], x[1].get("id", 0)), reverse=True)
    return [item[1] for item in scored_memories[:max_memories]]

def format_prompt_with_memories(user_query: str, relevant_memories: List[Dict[str, Any]]) -> str:
    """
    Formats the prompt injecting relevant memories cleanly separated from the user's message.
    Memories are explicitly positioned as background context, never overriding system safety.
    """
    if not relevant_memories:
        return user_query

    memory_lines = []
    for mem in relevant_memories:
        mtype = mem.get("memory_type", "Fact").capitalize()
        content = mem.get("content", "").strip()
        memory_lines.append(f"- {mtype}: {content}")

    memory_block = "\n".join(memory_lines)
    return (
        f"[LONG-TERM MEMORY — USER PROVIDED CONTEXT]\n"
        f"{memory_block}\n\n"
        f"[CURRENT USER MESSAGE]\n"
        f"{user_query}"
    )

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
