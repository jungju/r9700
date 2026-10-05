# Build explicitly and pin the resulting image digest before enabling code validation.
FROM node:24-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends python3 ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /opt
COPY package*.json ./
RUN npm ci && node node_modules/playwright/cli.js install --with-deps chrome
RUN chmod -R a+rX /opt/node_modules && useradd --uid 10001 --create-home validator
USER 10001:10001
ENV PYTHON_BIN=python3
