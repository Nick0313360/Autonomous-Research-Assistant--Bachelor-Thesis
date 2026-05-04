# ============================================================
# Stage 1: Dependencies (cacheable -- changes only when lockfile changes)
# ============================================================
FROM node:22-bookworm-slim AS deps
WORKDIR /app
COPY package.json pnpm-lock.yaml ./
RUN --mount=type=cache,target=/root/.local/share/pnpm/store \
    corepack enable && pnpm install --frozen-lockfile

# ============================================================
# Stage 2: Builder (rebuild only when source changes)
# ============================================================
FROM deps AS builder
COPY . .
RUN --mount=type=cache,target=/app/.next/cache \
    pnpm build

# ============================================================
# Stage 3: Asset compilation (if Tailwind, SASS, etc.)
# ============================================================
# Merge into builder stage when trivial, or split for parallel builds.

# ============================================================
# Stage 4a: Production
# ============================================================
FROM gcr.io/distroless/nodejs22-debian12 AS production
WORKDIR /app
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public
ENV NODE_ENV=production
USER nonroot:nonroot
EXPOSE 3000
CMD ["server.js"]

# ============================================================
# Stage 4b: Development
# ============================================================
FROM deps AS development
COPY . .
ENV NODE_ENV=development
EXPOSE 3000 9229
CMD ["pnpm", "dev"]

# ============================================================
# Stage 4c: Test
# ============================================================
FROM deps AS test
COPY . .
RUN pnpm install --frozen-lockfile  # includes devDependencies
CMD ["pnpm", "test", "--coverage"]
