FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies for Playwright
RUN apt-get update && apt-get install -y \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -u 1000 botuser

# Copy requirements first for caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers
RUN playwright install chromium --with-deps

# Copy source code
COPY src/ ./src/

# Change ownership
RUN chown -R botuser:botuser /app

# Switch to non-root user
USER botuser

# Healthcheck: check file created by bot on_ready
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD test -f /tmp/healthy || exit 1

# Run bot
CMD ["python", "src/main.py"]
