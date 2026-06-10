# FaultAuditAI — single container serving the API + web UI.
# Runs in mock mode by default (no creds). For live mode pass USE_MOCKS=false,
# ATLAS_URI, GCP_PROJECT and mount a service-account key (see README).

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    USE_MOCKS=true \
    PORT=8080 \
    GOOGLE_GENAI_USE_VERTEXAI=TRUE

WORKDIR /app

# deps first for layer caching
COPY requirements.txt .
RUN pip install -r requirements.txt

# app code
COPY faultaudit ./faultaudit
COPY vector_index.json embed_and_load.py create_vector_index.py ./

EXPOSE 8080

# Cloud Run / Docker inject $PORT; default 8080
CMD ["sh", "-c", "uvicorn faultaudit.server.app:app --host 0.0.0.0 --port ${PORT}"]
