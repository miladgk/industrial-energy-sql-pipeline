FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

CMD ["sh", "-c", "python scripts/bootstrap_render.py && uvicorn src.api:app --host 0.0.0.0 --port ${PORT:-8000}"]
