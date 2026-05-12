# Vedanta AI — frontend image.
#
# Three-stage build:
#   1. `deps`     — installs node_modules from package-lock.json
#                   (or package.json when no lockfile is present).
#   2. `builder`  — copies the source and runs `next build`. This
#                   needs `output: "standalone"` in next.config.mjs
#                   to emit the minimal server bundle.
#   3. `runtime`  — copies just the standalone server + .next/static
#                   + public assets, runs as a non-root user.
#
# `NEXT_PUBLIC_API_BASE_URL` is baked into the bundle at build time.
# Override it via the compose `args` block when targeting different
# environments.

FROM node:20-alpine AS deps

WORKDIR /app
COPY frontend/package.json frontend/package-lock.json* ./
RUN if [ -f package-lock.json ]; then \
        npm ci; \
    else \
        npm install; \
    fi


FROM node:20-alpine AS builder

ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL \
    NEXT_TELEMETRY_DISABLED=1

WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY frontend ./
RUN npm run build


FROM node:20-alpine AS runtime

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

RUN addgroup --system --gid 1001 nodejs \
    && adduser --system --uid 1001 nextjs

WORKDIR /app

# Standalone output ships its own minimal node_modules under
# .next/standalone, so we don't `npm install` again here.
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nodejs /app/public ./public

USER nextjs
EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD node -e "require('http').get('http://localhost:3000/', r => process.exit(r.statusCode < 500 ? 0 : 1)).on('error', () => process.exit(1))"

CMD ["node", "server.js"]
