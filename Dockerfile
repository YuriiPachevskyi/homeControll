FROM python:3.11-slim

# Install system dependencies for I2C and hardware access
RUN apt-get update && apt-get install -y \
    libi2c-dev \
    i2c-tools \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
RUN pip install --no-cache-dir \
    smbus2 \
    paho-mqtt \
    ruamel.yaml \
    requests

# Copy source code from the src directory
COPY src/ .

# Start the main application
CMD ["python", "main.py"]