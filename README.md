# AI News Telegram Automation Service (aibot)

AI-сервіс для автоматизації Telegram-каналу новин. Сервіс збирає новини з активних RSS-стрічок та Telegram-каналів, проводить відбір за ключовими словами, виконує ШІ-ранжування новин за допомогою LLM (OpenAI), генерує готові пости для Telegram та публікує їх за розкладом через Celery, RabbitMQ та Telethon.

---

## 🛠 Стек технологій
- **Мова:** Python 3.14
- **Пакетний менеджер:** `uv`
- **Веб-фреймворк:** FastAPI, Uvicorn
- **База даних:** PostgreSQL 16, SQLAlchemy 2.0 (asyncio, asyncpg), Alembic
- **Брокер повідомлень та черги завдань:** Celery 5.4+, RabbitMQ 3 (Management)
- **Парсинг:** Telethon (Telegram-канали), Selectolax, Trafilatura (RSS та веб-сторінки)
- **ШІ-модулі:** OpenAI API (`gpt-4o-mini` / `gpt-5-nano`)
- **Тестування:** pytest, pytest-asyncio (147 тестів, 100% pass)

---

## 🚀 Архітектура черг (Celery + RabbitMQ)

Сервіс використовує **Celery Chain** та відкладену публікацію через `apply_async(countdown=...)`:

1. **Celery Beat (`run-news-pipeline-every-30-mins`)**:
   Запускається кожні 30 хвилин (`crontab(minute="*/30")`) та викликає ланцюжок завдань:
   - **`fetch_and_rank_news_task`**: Збирає свіжі статті з активних сайтів (RSS) та Telegram-каналів. Якщо нових статей знайдено менше ніж 10, автоматично добирає з бази даних до 10 неопублікованих статей із найвищим балом ШІ. Оцінює та зберігає **всі** знайдені статті в БД (з полями `parsed_at`, `ai_score`, `ai_reason`) та відбирає ТОП-3 найкращі для публікації. Повертає список `[news_id, ...]`.
   - **`generate_ai_posts_task`**: Отримує `news_ids`, викликає `PostGenerator` для кожної новини та створює пости в статусі `GENERATED`. Повертає список `[post_id, ...]`.
   - **`schedule_posts_publication_task`**: Отримує список `post_ids` та планує окремі відкладені таски публікації з кроком у 10 хвилин:
     - Пост 1: `countdown=0` (одразу)
     - Пост 2: `countdown=600` (через 10 хв)
     - Пост 3: `countdown=1200` (через 20 хв)

2. **Таска публікації (`publish_post_task(post_id)`):**
   - Викликає `TelegramPublisher(session).publish_post(post_id)`.
   - Встановлює проміжний статус `PUBLISHING` (in-flight lock для захисту від race conditions та повторних публікацій).
   - Публікує через Telethon у цільовий канал (`TG_TARGET_CHANNEL`).
   - Фіксує фінальний статус `PUBLISHED` або `FAILED`.
   - **Політика Retries**: автоматичний retry при `FloodWaitError` з інтервалом очікування `countdown=exc.seconds` (до 3 спроб) та експоненційний бекофф при тимчасових мережевих збоях.

3. **Асинхронний міст (`app.utils.run_async`)**:
   - Реалізує стабільний thread-local event loop для Celery-воркерів, гарантуючи ізоляцію та сумісність із пулом з'єднань SQLAlchemy `asyncpg` та клієнтом Telethon.

---

## ⚙️ Встановлення та запуск

### Варіант 1: Все в одному через Docker Compose (Рекомендовано)
Однією командою збирає і запускає всі 5 сервісів (`PostgreSQL`, `RabbitMQ`, `FastAPI`, `Celery Worker`, `Celery Beat`):
```bash
cp .env.example .env
# Заповніть ваші ключі в .env
docker compose up --build -d
```
- Документація Swagger UI: [http://localhost:8000/docs](http://localhost:8000/docs)
- RabbitMQ Management UI: [http://localhost:15672](http://localhost:15672) (гість: `guest` / `guest`)
- Перегляд логів: `docker compose logs -f`
- Зупинка: `docker compose down`

---

### Варіант 2: Локальний запуск для розробки

#### 1. Запуск інфраструктури (PostgreSQL + RabbitMQ)
```bash
docker compose up -d db rabbitmq
```

#### 2. Встановлення залежностей та міграції
```bash
uv sync
uv run alembic upgrade head
```

#### 3. Запуск сервісів у терміналах
- **Web API:**
  ```bash
  uv run uvicorn app.main:app --reload --port 8000
  ```
- **Celery Worker:**
  ```bash
  uv run celery -A celery_worker.celery_app worker -l info -P solo
  ```
- **Celery Beat:**
  ```bash
  uv run celery -A celery_worker.celery_app beat -l info
  ```

---

## 🧪 Запуск тестів

Для запуску всіх unit- та integration-тестів виконайте:
```bash
uv run pytest
```
Усі 147 тестів виконуються ізольовано у пам'яті через SQLite in-memory з повною підтримкою async.
