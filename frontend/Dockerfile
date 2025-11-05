# Use the pre-built base image with all dependencies
FROM onboarding-agent-base:latest

WORKDIR /app

# Install frontend-specific dependencies if not in base
RUN pip install --no-cache-dir -r requirements.txt

# Copy frontend application code
COPY . .

# Expose port 3030
EXPOSE 3030

# Start Streamlit application on port 3030
CMD ["streamlit", "run", "streamlit_app.py", "--server.address", "0.0.0.0", "--server.port", "3030"]