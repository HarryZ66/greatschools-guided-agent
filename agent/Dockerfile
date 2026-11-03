# Agent API image. Built for ARM64 (Graviton Fargate), the same architecture as Apple-silicon laptops.
FROM public.ecr.aws/docker/library/python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY gs_agent ./gs_agent

RUN useradd --create-home --uid 1000 app
USER app

EXPOSE 8000
CMD ["uvicorn", "gs_agent.api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
