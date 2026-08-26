import os
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row

DATABASE_URL = os.getenv("DATABASE_URL", "")


def _conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is required")
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def init_db():
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS reviews (
                    id TEXT PRIMARY KEY,
                    source_chat_id BIGINT NOT NULL,
                    channel_message_id BIGINT NOT NULL,
                    user_name TEXT NOT NULL DEFAULT 'Клиент',
                    username TEXT,
                    rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
                    text TEXT NOT NULL,
                    product TEXT,
                    date TIMESTAMPTZ NOT NULL,
                    published BOOLEAN NOT NULL DEFAULT TRUE,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE(source_chat_id, channel_message_id)
                )
            """)
            cur.execute("DELETE FROM reviews WHERE id = 'channel-0-1787741758314'")
        conn.commit()


def upsert_channel_review(*, chat_id, message_id, text, rating, date, username=None, user_name="Клиент", product="Telegram Stars"):
    clean = " ".join(text.split()).strip()
    if not clean:
        return None
    now = datetime.now(timezone.utc)
    review_id = f"channel-{chat_id}-{message_id}"
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO reviews (id, source_chat_id, channel_message_id, user_name, username, rating, text, product, date, updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (source_chat_id, channel_message_id) DO UPDATE SET
                    user_name=EXCLUDED.user_name,
                    username=EXCLUDED.username,
                    rating=EXCLUDED.rating,
                    text=EXCLUDED.text,
                    product=EXCLUDED.product,
                    date=EXCLUDED.date,
                    updated_at=EXCLUDED.updated_at,
                    published=TRUE
                RETURNING *
            """, (review_id, chat_id, message_id, user_name, username, rating, clean, product, date, now))
            row = cur.fetchone()
        conn.commit()
    return row


def list_reviews(limit=50, offset=0, rating=None):
    init_db()
    where = ["published = TRUE"]
    params = []
    if rating in {1, 2, 3, 4, 5}:
        where.append("rating = %s")
        params.append(rating)
    params.extend([limit, offset])
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT id, user_name AS user, username, rating, text, date, product,
                       source_chat_id, channel_message_id
                FROM reviews
                WHERE {' AND '.join(where)}
                ORDER BY date DESC, channel_message_id DESC
                LIMIT %s OFFSET %s
            """, params)
            return cur.fetchall()


def stats():
    init_db()
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS total, COALESCE(ROUND(AVG(rating)::numeric, 1), 0) AS average FROM reviews WHERE published = TRUE")
            summary = cur.fetchone()
            cur.execute("SELECT rating, COUNT(*) AS count FROM reviews WHERE published = TRUE GROUP BY rating")
            rows = cur.fetchall()
    dist = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    for row in rows:
        dist[int(row["rating"])] = int(row["count"])
    return {"total": int(summary["total"]), "average": float(summary["average"]), "distribution": dist}
