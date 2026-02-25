FROM python:3.12-slim

RUN pip install --no-cache-dir uv && \
    apt-get update && apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .

EXPOSE 8350

CMD ["uv", "run", "uvicorn", "ai_agent.server:app", "--host", "0.0.0.0", "--port", "8350"]
