FROM node:20-alpine

WORKDIR /app

# Install dependencies based on the preferred package manager
COPY package.json package-lock.json* ./
RUN npm ci

# Copy the rest of the application code
COPY . .

# Build the Next.js application
ARG NEXT_PUBLIC_API_URL=
ARG NEXT_PUBLIC_REMOTE_VM_IP=
ARG BACKEND_INTERNAL_ORIGIN=http://backend:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_REMOTE_VM_IP=$NEXT_PUBLIC_REMOTE_VM_IP
ENV BACKEND_INTERNAL_ORIGIN=$BACKEND_INTERNAL_ORIGIN
RUN npm run build

# Expose the listening port
EXPOSE 3000

# Start the application
CMD ["npm", "start"]
