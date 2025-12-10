# frontend/Dockerfile
FROM node:18-alpine

WORKDIR /app

# Copy package files
COPY package*.json ./

# Install dependencies
RUN npm install --silent

# Copy application code
COPY . .

# Expose port
EXPOSE 3000

# Set environment variable for hot reload
ENV CHOKIDAR_USEPOLLING=true

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost:3000 || exit 1

# Start development server
CMD ["npm", "start"]