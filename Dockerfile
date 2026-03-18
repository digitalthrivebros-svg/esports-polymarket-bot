FROM python:3.12-slim

WORKDIR /app

# Install system deps needed by some Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libffi-dev && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Persist the SQLite database outside the container
VOLUME ["/app/data"]
ENV DB_PATH=/app/data/bot.db

CMD ["python", "main.py"]
