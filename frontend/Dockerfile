# Production multi-stage build for the Astro SSR frontend.
#
# Build context: the REPO ROOT (not ./frontend). docker-compose.yml sets
# `build.context: .` so this Dockerfile can COPY both frontend/ and docs/
# — the docs/ tree has USER_GUIDE_{EN,ES}.md which src/pages/help.astro
# and ayuda.astro import and render.
#
# Runtime stage only ships the built output + node_modules, no source.

FROM node:22-alpine AS build

WORKDIR /app

# Install deps first for better layer cache.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

# Copy the frontend source tree and the docs/ tree it imports from.
# Any markdown under docs/ referenced by an .astro page must be present
# here or `npm run build` will fail with ENOENT.
COPY frontend/ ./
COPY docs/ ./docs/

RUN npm run build


FROM node:22-alpine AS runtime

WORKDIR /app

# Only the runtime artefacts — no source, no dev deps.
COPY --from=build /app/package.json ./package.json
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/dist ./dist

EXPOSE 3000
ENV HOST=0.0.0.0
ENV PORT=3000

CMD ["node", "./dist/server/entry.mjs"]
