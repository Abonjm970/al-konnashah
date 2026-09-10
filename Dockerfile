# Dockerfile — للاستضافة على Railway / Fly.io / Render / VPS
# (Vercel لا يحتاجه — يستخدم api/index.py تلقائياً)
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV MODE=webhook \
    PORT=8080

EXPOSE 8080

CMD ["python", "main.py"]
