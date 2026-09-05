# syntax=docker/dockerfile:1

# ---- Build stage: install deps + build the Nuxt app with Bun ----
FROM oven/bun:1 AS build
WORKDIR /app

# The base image ships with no CA bundle at all, so any HTTPS call made by a
# native binary (e.g. sentry-cli, invoked below for source map upload) fails
# TLS verification ("unable to get local issuer certificate"). Bun/Node's own
# fetch calls are unaffected (they bundle their own root store), which is why
# this only ever broke sentry-cli, not the rest of the build.
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies first so this layer is cached unless the manifest changes.
COPY package.json bun.lock ./
RUN --mount=type=cache,target=/root/.bun/install/cache \
    bun install --frozen-lockfile

# Build the app. The Nitro `node-server` preset emits a self-contained
# server bundle into .output/ (run with `node .output/server/index.mjs`).
COPY . .

# Sentry source map upload (build-time only, see nuxt.config.ts `sentry` key).
# org/project aren't secret; the auth token is passed as a BuildKit secret
# (not a regular ARG/ENV) so it never ends up in an image layer or build cache.
ARG SENTRY_ORG
ARG SENTRY_PROJECT
ENV SENTRY_ORG=$SENTRY_ORG \
    SENTRY_PROJECT=$SENTRY_PROJECT

RUN --mount=type=secret,id=sentry_auth_token,env=SENTRY_AUTH_TOKEN \
    bun run build

# ---- Runtime stage: just Node + the built server output ----
FROM node:24-slim AS runtime
WORKDIR /app

ENV NODE_ENV=production \
    HOST=0.0.0.0 \
    PORT=3000

# Only the build output is needed at runtime (no node_modules, no source).
COPY --chown=node:node --from=build /app/.output ./.output

USER node

EXPOSE 3000

# Node 24 ships a global fetch, so we can health-check without curl/wget.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD node -e "fetch('http://localhost:3000/').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

CMD ["node", ".output/server/index.mjs"]
