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

# Fargate serves the public API on 8000; AgentCore Runtime sets PORT=8080 (its service contract).
# On AgentCore, opentelemetry-instrument (AWS Distro for OpenTelemetry) sends the agent's traces,
# spans and logs to CloudWatch for AgentCore Observability (decision 026).
ENV PORT=8000
EXPOSE 8000 8080
CMD ["sh", "-c", "if [ \"$RUNNING_ON\" = agentcore ]; then set -- opentelemetry-instrument; fi; exec \"$@\" uvicorn gs_agent.api:app --host 0.0.0.0 --port \"$PORT\" --workers 1"]
