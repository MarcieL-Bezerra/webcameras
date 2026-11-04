FROM python:3.11-slim

# Instala dependências mínimas do sistema para rodar OpenCV sem interface gráfica
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirementsdocker.txt .

# Instala a versão 'headless' do OpenCV para economizar espaço e evitar bugs de GUI
RUN pip install --no-cache-dir -r requirementsdocker.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]