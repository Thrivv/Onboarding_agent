# # Use the pre-built base image with all dependencies
# FROM onboarding-agent-base:latest

# WORKDIR /app

# # Install frontend-specific dependencies if not in base
# RUN pip install --no-cache-dir -r requirements.txt

# # Copy frontend application code
# COPY . .

# # Expose port 3030
# EXPOSE 3030

# # Start Streamlit application on port 3030
# CMD ["streamlit", "run", "streamlit_app.py", "--server.address", "0.0.0.0", "--server.port", "3030"]


# frontend/Dockerfile
FROM thrivv-base:latest

WORKDIR /app

# Copy and install frontend-specific requirements (if any)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create log directory
RUN mkdir -p /var/log/frontend && \
    chmod -R 777 /var/log/frontend

# Expose port
EXPOSE 3030

# Start Streamlit
CMD ["streamlit", "run", "streamlit_app.py", "--server.address", "0.0.0.0", "--server.port", "3030", "--server.headless", "true"]