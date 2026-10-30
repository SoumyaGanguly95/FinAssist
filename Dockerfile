# Containerizes the FastAPI service for Azure Container Apps.
# Note: builds the API service only. dashboard.py (Streamlit) is a
# separate concern — deploy it as its own Container App if hosted,
# pointing FINASSIST_API_URL at this service's URL.

FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py .

RUN mkdir -p /app/data/raw

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

# Secrets (AZURE_OPENAI_API_KEY etc.) are injected at runtime via Azure
# Key Vault + Managed Identity / Container Apps secrets — never baked
# into the image. DATABASE_URL likewise, pointed at Azure SQL in prod.
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]