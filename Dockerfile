FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DB_PATH=/data/bot.db

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot/ bot/

RUN useradd --uid 10001 --no-create-home app \
    && mkdir /data && chown app /data
USER 10001

VOLUME ["/data"]
CMD ["python", "-m", "bot"]
