FROM python:3.11-slim

# Create a non-root user — agent never runs as root
RUN useradd -m -u 1000 agentuser

WORKDIR /app/agent

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Ensure the non-root user owns the app files
RUN chown -R agentuser:agentuser /app

USER agentuser

CMD ["python", "main.py"]
