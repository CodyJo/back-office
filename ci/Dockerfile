FROM node:18-slim

# Install Python, pip, git, curl, and Bunny CLI dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    git \
    curl \
    ca-certificates \
  && apt-get clean \
  && rm -rf /var/lib/apt/lists/*

# Install Python CI tools globally
RUN pip3 install --no-cache-dir --break-system-packages ruff pytest pyyaml

# Install dustbunny (Bunny.net CLI helper)
RUN npm install -g dustbunny 2>/dev/null || true

WORKDIR /app

# Install Node dependencies
COPY package.json package-lock.json* ./
RUN npm ci --omit=dev

# Copy server source
COPY server.mjs pipeline.mjs ./

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:3000/health || exit 1

CMD ["node", "server.mjs"]
