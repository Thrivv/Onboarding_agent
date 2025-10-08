# Use the pre-built base image with all dependencies
FROM thrivv-base:latest

WORKDIR /app

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p backend/documents/id

# Expose port
EXPOSE 8000

# Start the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]