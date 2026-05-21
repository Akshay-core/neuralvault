# FILE: docker/Dockerfile
FROM python:3.11-slim

WORKDIR /app

# system deps
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    git \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    && rm -rf /var/lib/apt/lists/*

# python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# create dirs
RUN mkdir -p data/raw_docs data/processed_docs data/embeddings \
    data/vector_index data/user_data logs models_cache

EXPOSE 8501

ENV OLLAMA_URL=http://ollama:11434
ENV PYTHONPATH=/app

CMD ["streamlit", "run", "app/ui/streamlit_app.py", \
     "--server.address=0.0.0.0", \
     "--server.port=8501", \
     "--server.headless=true", \
     "--browser.gatherUsageStats=false"]