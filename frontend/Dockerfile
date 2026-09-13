FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund

FROM node:22-alpine AS build
WORKDIR /app
ARG NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
COPY --from=deps /app/node_modules ./node_modules
COPY package.json package-lock.json ./
COPY . .
RUN npm run build

FROM node:22-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production \
    HOSTNAME=0.0.0.0

RUN addgroup -S -g 10001 rcaa \
    && adduser -S -D -u 10001 -G rcaa rcaa

COPY --from=build --chown=rcaa:rcaa /app/.next/standalone ./
COPY --from=build --chown=rcaa:rcaa /app/.next/static ./.next/static
COPY --from=build --chown=rcaa:rcaa /app/public ./public

USER rcaa
EXPOSE 3000
CMD ["node", "server.js"]
