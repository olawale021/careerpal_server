# Use an official Python runtime as a base image with explicit platform
FROM --platform=linux/amd64 python:3.9-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set the working directory in the container
WORKDIR /server

# Copy requirements.txt first to leverage Docker's caching mechanism
COPY requirements.txt .

# Install system dependencies and Python packages
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc \
    && pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir supabase \
    && apt-get purge -y --auto-remove gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy the entire project into the container
COPY . .

# Create a non-root user
RUN adduser --disabled-password --gecos '' appuser
USER appuser

# Expose the FastAPI port
EXPOSE 8000

# Start the FastAPI application using Uvicorn
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
