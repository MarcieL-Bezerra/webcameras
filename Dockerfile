FROM python:3.11-slim

# Instala dependências mínimas do sistema para rodar OpenCV sem interface gráfica
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY requirementsdocker.txt ./
RUN pip install --no-cache-dir -r requirementsdocker.txt

COPY app.py screen_recorder.py ./
RUN mkdir -p /app/gravacoes

VOLUME ["/app/gravacoes"]

EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
