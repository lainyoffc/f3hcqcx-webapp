import os
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from reviews_store import init_db, list_reviews, stats

load_dotenv()
app = FastAPI(title="F3hcqcx Reviews API", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://lainyoffc.github.io"],
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["*"],
)

@app.on_event("startup")
def startup():
    init_db()

@app.get("/api/health")
def health():
    return {"ok": True, "service": "f3hcqcx-reviews"}

@app.get("/api/reviews")
def reviews(offset: int = 0, limit: int = 50, rating: int | None = None):
    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    items = list_reviews(limit, offset, rating)
    return {"reviews": items, "stats": stats(), "has_more": len(items) == limit}

@app.get("/api/reviews/stats")
def reviews_stats():
    return stats()

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
