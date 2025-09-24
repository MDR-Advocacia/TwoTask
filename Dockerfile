# Stage 1: Build frontend assets
FROM node:18-alpine AS frontend-builder

WORKDIR /app

# Copy package files and install dependencies
COPY package.json package-lock.json ./
RUN npm install

# Copy frontend source files
COPY tailwind.config.js ./
COPY static/css/input.css ./static/css/input.css

# Build CSS for production
RUN npm run build:prod

# Stage 2: Build the final Python application
FROM python:3.10-slim

WORKDIR /app

# Set environment variables to prevent Python from writing .pyc files
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire application code
COPY . .

# Copy the built CSS from the frontend-builder stage
COPY --from=frontend-builder /app/static/css/output.css ./static/css/output.css

# Expose the port the app runs on
EXPOSE 8000

# Command to run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
