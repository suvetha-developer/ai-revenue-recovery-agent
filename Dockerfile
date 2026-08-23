# RecoverAI Production Dockerfile
FROM python:3.11-slim

# Set working directory & environment variables
WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    DEMO_MODE=true \
    RAZORPAY_LIVE_INTEGRATION=false

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy dependencies list & install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code & data
COPY . .

# Expose FastAPI microservice port
EXPOSE 8000

# Run production ASGI server
CMD ["uvicorn", "src.api:app", "--host", "0.0.0.0", "--port", "8000"]
