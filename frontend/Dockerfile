# syntax=docker/dockerfile:1

# ---- Build stage: install deps + build the Nuxt app with Bun ----
FROM oven/bun:1 AS build
WORKDIR /app

# Install dependencies first so this layer is cached unless the manifest changes.
COPY package.json bun.lock ./
RUN bun install --frozen-lockfile

# Build the app. The Nitro `node-server` preset emits a self-contained
# server bundle into .output/ (run with `node .output/server/index.mjs`).
COPY . .
RUN bun run build

# ---- Runtime stage: just Node + the built server output ----
FROM node:24-slim AS runtime
WORKDIR /app

ENV NODE_ENV=production \
    HOST=0.0.0.0 \
    PORT=3000

# Only the build output is needed at runtime (no node_modules, no source).
COPY --from=build /app/.output ./.output

EXPOSE 3000

# Node 24 ships a global fetch, so we can health-check without curl/wget.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD node -e "fetch('http://localhost:3000/').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

CMD ["node", ".output/server/index.mjs"]
