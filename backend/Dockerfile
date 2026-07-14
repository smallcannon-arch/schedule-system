FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN useradd --create-home --uid 10001 appuser
COPY --chown=appuser:appuser . .
USER appuser
CMD exec uvicorn app:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1 --limit-concurrency 8
