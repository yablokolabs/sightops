# syntax=docker/dockerfile:1
#
# SightOps web client — the Vite/React build served by nginx.
#
# Two stages so the shipped image carries no Node runtime, no toolchain and no
# source: only the compiled bundle and nginx. nginx also proxies the API, which
# is why the client can use relative URLs and needs no build-time API host.

FROM node:22-alpine AS build

WORKDIR /app

# package-lock.json is copied with package.json so `npm ci` resolves the exact
# tree the frontend was verified against. NODE_ENV is deliberately left unset:
# `npm ci` installs devDependencies, and vite, TypeScript and Tailwind are all
# devDependencies that the build needs.
COPY package.json package-lock.json ./
RUN npm ci

# The context is not trimmed by a .dockerignore, so the build stage enumerates
# what it copies rather than using `COPY . .`. That keeps the host's
# node_modules — which holds platform-specific binaries — from being copied over
# the tree `npm ci` just installed.
COPY index.html tsconfig.json vite.config.ts tailwind.config.js postcss.config.js ./
COPY src ./src
COPY public ./public

# `npm run build` is `tsc --noEmit && vite build`, so the image build fails on a
# type error instead of shipping one.
RUN npm run build


FROM nginx:1.27-alpine AS runtime

# Replaces the default server block. It serves the bundle, falls back to
# index.html for client-side routes, and forwards /api and /health to the
# backend service.
COPY nginx.conf /etc/nginx/conf.d/default.conf

COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

# busybox wget is in the base image, so no extra package is needed to prove the
# static bundle is actually being served.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1/index.html || exit 1

CMD ["nginx", "-g", "daemon off;"]
