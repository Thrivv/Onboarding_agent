# Use the pre-built base image with all dependencies
FROM thrivv-base:latest

WORKDIR /app

# Install frontend-specific dependencies if not in base
RUN pip install --no-cache-dir streamlit pandas plotly

# Copy frontend application code
COPY . .

# Expose port 3000
EXPOSE 3000

# Start Streamlit application on port 3000
CMD ["streamlit", "run", "streamlit_app.py", "--server.address", "0.0.0.0", "--server.port", "3000"]