FROM python:3.12-slim

# Prevent interactive prompts during installation
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PORT=10000 \
    APP_ENV=production \
    HOSTED_CODE_EXECUTION_ENABLED=true \
    LOCAL_CODE_EXECUTION_ENABLED=true \
    AUTOGRADER_CONTAINER_SANDBOX=1

# Install system dependencies:
# - gcc, libc6-dev: C compilation
# - valgrind: memory safety diagnostics
# - util-linux: prlimit for CPU, memory, output, and process limits
# - bubblewrap: fallback namespace utility
# - ca-certificates: SSL/TLS validation for cloud database and AI APIs
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libc6-dev \
    valgrind \
    util-linux \
    bubblewrap \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Create unprivileged runner user for isolating student code execution
RUN useradd -m -s /bin/false -u 10001 runner_user

WORKDIR /app

# Install Python dependencies first for build caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application codebase
COPY . .

# Ensure permissions
RUN chmod +x scripts/*.py 2>/dev/null || true

EXPOSE 10000

CMD ["sh", "-c", "uvicorn app.web:app --host 0.0.0.0 --port ${PORT:-10000}"]
