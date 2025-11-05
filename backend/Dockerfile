# # Use the pre-built base image with all dependencies
# FROM onboarding-agent-base:latest

# WORKDIR /app

# # Copy application code
# COPY . .

# # Create necessary directories matching code expectations
# RUN mkdir -p backend/documents/id && \
#     mkdir -p backend/summary && \
#     chmod -R 777 backend/documents && \
#     chmod -R 777 backend/summary

# # Set Python path
# ENV PYTHONPATH=/app:${PYTHONPATH}

# # Expose port 8080
# EXPOSE 8080

# # Start the application
# CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]

# Use the pre-built base image with all dependencies
FROM onboarding-agent-base:latest

WORKDIR /app

# Copy application code
COPY . .

# ✅ CREATE DIRECTORY STRUCTURE TO MATCH CODE EXPECTATIONS
# Your code expects: project_root/backend/documents/id
# But we're at /app, so we need /app/backend/documents/id

RUN mkdir -p /app/backend/documents/id && \
    mkdir -p /app/backend/summary && \
    chmod -R 777 /app/backend/documents && \
    chmod -R 777 /app/backend/summary

# ✅ ALSO CREATE AT ROOT LEVEL (for project_root path)
RUN mkdir -p /backend/documents/id && \
    mkdir -p /backend/summary && \
    chmod -R 777 /backend/documents && \
    chmod -R 777 /backend/summary

# Set Python path
ENV PYTHONPATH=/app:${PYTHONPATH}

# Expose port 8080
EXPOSE 8080

# Start the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]