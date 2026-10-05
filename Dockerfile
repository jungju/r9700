FROM node:24-bookworm-slim AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build && npm prune --omit=dev

FROM node:24-bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends python3 ca-certificates curl ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=build /app/dist ./dist
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/package.json ./package.json
COPY --from=build /app/ops ./ops
COPY --from=build /app/data ./data
COPY --from=build /app/sources.json ./sources.json
COPY deploy/entrypoint.sh ./deploy/entrypoint.sh
RUN mkdir -p /app/.local && chown -R node:node /app
USER node
ENV HOST=0.0.0.0 PORT=4321 PYTHON_BIN=python3 R9700_ROOT=/app SITE=https://r9700.jjgo.io
EXPOSE 4321
HEALTHCHECK --interval=60s --timeout=5s --start-period=30s --retries=3 CMD curl -fsS http://127.0.0.1:4321/api/health || exit 1
ENTRYPOINT ["bash", "/app/deploy/entrypoint.sh"]
