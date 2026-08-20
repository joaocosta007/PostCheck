FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-por \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p /app/static/uploads

EXPOSE 10000

CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT:-10000} --workers 1 --threads 4 --timeout 120 app:app"]
