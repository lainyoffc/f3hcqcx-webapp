import os
import re
from datetime import datetime, timezone

from dotenv import load_dotenv
from reviews_store import init_db, upsert_channel_review

load_dotenv()
REVIEWS_CHANNEL = os.getenv("REVIEWS_CHANNEL", "@OtziviF3hcqcx1")
if not REVIEWS_CHANNEL.startswith("@"):
    REVIEWS_CHANNEL = "@" + REVIEWS_CHANNEL


def detect_rating(text: str) -> int:
    star_count = text.count("⭐") + text.count("🌟")
    if 1 <= star_count <= 5:
        return star_count
    match = re.search(r"(?<!\d)([1-5])\s*(?:/\s*5|из\s*5|⭐)", text, re.I)
    if match:
        return int(match.group(1))
    low = text.lower()
    for score, words in {
        5: ("отлично", "супер", "идеально", "прекрасно", "рекомендую", "лучший"),
        4: ("хорошо", "доволен", "спасибо", "неплохо"),
        3: ("норм", "средне", "так себе"),
        2: ("плохо", "не очень", "разочарован"),
        1: ("ужас", "кошмар", "отстой", "не рекомендую"),
    }.items():
        if any(word in low for word in words):
            return score
    return 5


def parse_product(text: str) -> str:
    numbers = re.findall(r"(?<!\d)(\d{2,6})(?!\d)", text)
    return f"Telegram Stars - {numbers[0]}" if numbers else "Telegram Stars"


def sync_channel_post(message):
    """Сохраняет новый пост из @OtziviF3hcqcx1 в PostgreSQL."""
    if not message.chat:
        return None
    expected = REVIEWS_CHANNEL.lower().lstrip("@")
    actual = (message.chat.username or "").lower()
    if actual and actual != expected:
        return None
    text = message.text or message.caption or ""
    if not text.strip():
        return None
    init_db()
    row = upsert_channel_review(
        chat_id=message.chat.id,
        message_id=message.message_id,
        text=text,
        rating=detect_rating(text),
        date=datetime.fromtimestamp(message.date, tz=timezone.utc),
        product=parse_product(text),
    )
    print(f"[reviews] synced @{expected} post #{message.message_id}: {row['rating']}/5")
    return row


def register_channel_handlers(bot):
    @bot.channel_post_handler(content_types=["text", "photo", "video", "document"])
    def channel_post(message):
        sync_channel_post(message)

    @bot.edited_channel_post_handler(content_types=["text", "photo", "video", "document"])
    def edited_channel_post(message):
        sync_channel_post(message)
