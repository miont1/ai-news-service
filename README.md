# AI News Telegram Automation Service (aibot)

An automated AI-driven service for managing Telegram news channels. The service aggregates news articles from active RSS feeds and public Telegram channels, filters and scores them using LLM-based AI ranking (OpenAI), generates concise and engaging Telegram posts, and publishes them on a schedule via Celery, RabbitMQ, and Telethon.

---

## 🛠 Technology Stack

- **Language:** Python 3.14
- **Package Manager:** `uv`
- **Web Framework:** FastAPI, Uvicorn
- **Database & ORM:** PostgreSQL 16, SQLAlchemy 2.0 (asyncio, asyncpg), Alembic
- **Task Queue & Broker:** Celery 5.4+, RabbitMQ 3 (Management)
- **Parsers:** Telethon (Telegram channels), Selectolax, Trafilatura (RSS feeds and websites)
- **AI Modules:** OpenAI API (`gpt-4o-mini` / `gpt-5-nano`)
- **Testing:** pytest, pytest-asyncio (147 tests, 100% pass)

---

## 🚀 Pipeline & Queue Architecture (Celery + RabbitMQ)

The service implements an asynchronous **Celery Chain** workflow coupled with delayed, staggered publications via `apply_async(countdown=...)`:

1. **Celery Beat (`run-news-pipeline-every-30-mins`)**:
   Runs every 30 minutes (`crontab(minute="*/30")`) and triggers the 3-step pipeline:
   - **`fetch_and_rank_news_task`**: Gathers fresh articles from active website RSS feeds and Telegram channels. Evaluates all incoming articles using `AINewsRanker` (scoring 1.0–10.0 and generating justifications) and saves **all** evaluated articles to the database (with `parsed_at`, `ai_score`, `ai_reason`). If fewer than 10 fresh articles are found, it supplements the candidate pool with up to 10 top-rated unposted articles from the database. Selects the top 3 items for publication and returns `[news_id, ...]`.
   - **`generate_ai_posts_task`**: Receives `news_ids`, invokes `PostGenerator` for each news item, and saves generated posts with status `GENERATED`. Returns `[post_id, ...]`.
   - **`schedule_posts_publication_task`**: Takes `post_ids` and schedules staggered publication tasks spaced 10 minutes apart:
     - Post 1: `countdown=0` (immediate)
     - Post 2: `countdown=600` (after 10 minutes)
     - Post 3: `countdown=1200` (after 20 minutes)

2. **Publishing Task (`publish_post_task(post_id)`):**
   - Calls `TelegramPublisher(session).publish_post(post_id)`.
   - Acquires an in-flight lock by setting intermediate status `PUBLISHING` to prevent race conditions and duplicate publications.
   - Publishes the post to the configured Telegram channel (`TG_TARGET_CHANNEL`) via Telethon.
   - Updates the final post status to `PUBLISHED` or `FAILED`.
   - **Retry Policy**: Handles Telegram rate limits (`FloodWaitError`) with automatic retries scheduled with `countdown=exc.seconds` (up to 3 retries), along with exponential backoff for transient network errors.

3. **Async Bridge (`app.utils.run_async`)**:
   - Manages a persistent thread-local event loop for Celery workers to ensure clean integration with async drivers (SQLAlchemy `asyncpg` connection pool and Telethon).

---

## ⚙️ Installation & Running

### Option 1: Full Stack via Docker Compose (Recommended)
Launch all 5 services (`PostgreSQL`, `RabbitMQ`, `FastAPI`, `Celery Worker`, `Celery Beat`) with a single command:

```bash
cp .env.example .env
# Configure your API keys in .env
docker compose up --build -d
```

- **Swagger UI Documentation:** [http://localhost:8000/docs](http://localhost:8000/docs)
- **RabbitMQ Management Dashboard:** [http://localhost:15672](http://localhost:15672) (credentials: `guest` / `guest`)
- **View Container Logs:** `docker compose logs -f`
- **Stop Services:** `docker compose down`

---

### Option 2: Local Development Setup

#### 1. Start Infrastructure (PostgreSQL + RabbitMQ)
```bash
docker compose up -d db rabbitmq
```

#### 2. Install Dependencies & Run Database Migrations
```bash
uv sync
uv run alembic upgrade head
```

#### 3. Start Application Services
In separate terminal windows:
- **FastAPI Web API:**
  ```bash
  uv run uvicorn app.main:app --reload --port 8000
  ```
- **Celery Worker:**
  ```bash
  uv run celery -A celery_worker.celery_app worker -l info -P solo
  ```
  *(Note: `-P solo` is recommended on Windows to support asyncio/Telethon in the worker process).*
- **Celery Beat (Scheduler):**
  ```bash
  uv run celery -A celery_worker.celery_app beat -l info
  ```

---

## 📡 REST API Endpoints

The API is fully documented via interactive Swagger UI at `/docs`:

- **News Management:**
  - `GET /api/news`: Retrieve parsed news ordered by `parsed_at` descending (supports `limit` and `offset`).
  - `POST /api/news/fetch`: Manually trigger news scraping from RSS sites.
  - `POST /api/news/fetch/telegram`: Manually trigger news scraping from Telegram channels.
- **AI Generation:**
  - `POST /api/generate`: Generate a Telegram post draft on demand for a custom article.
- **Post Management & Publishing:**
  - `GET /api/posts`: View generated post history with status filtering (`new`, `generated`, `publishing`, `published`, `failed`).
  - `POST /api/posts/{post_id}/publish`: Manually publish an individual post to Telegram.
- **Source Management:**
  - `GET /api/sources`: List configured news sources (sites and Telegram channels).
  - `POST /api/sources`: Add a new news source.
  - `PUT /api/sources/{source_id}`: Update or toggle source enabled state.
  - `DELETE /api/sources/{source_id}`: Remove a news source.
- **Keyword Filtering:**
  - `GET /api/keywords`: List active keyword filters.
  - `POST /api/keywords`: Add a keyword filter.
  - `DELETE /api/keywords/{keyword_id}`: Delete a keyword filter.

---

## 🧪 Testing

Run the automated test suite using `pytest`:
```bash
uv run pytest
```

All **147 unit and integration tests** run in an isolated environment using SQLite in-memory with full async support.
