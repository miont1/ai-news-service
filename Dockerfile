FROM python:3.14-slim

# Install uv from official image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Configure uv to install into /opt/venv so bind-mounting /app doesn't overwrite it
ENV UV_COMPILE_BYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT="/opt/venv" \
    PATH="/opt/venv/bin:$PATH"

# Copy dependency definition
COPY pyproject.toml uv.lock ./

# Synchronize dependencies into /opt/venv
RUN uv sync --frozen --no-dev

# Copy source code
COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
