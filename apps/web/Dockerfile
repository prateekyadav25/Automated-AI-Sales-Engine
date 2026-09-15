FROM node:22-alpine AS deps
WORKDIR /repo
RUN corepack enable
COPY package.json pnpm-workspace.yaml ./
COPY apps/web ./apps/web
COPY packages ./packages
RUN pnpm install --frozen-lockfile || pnpm install

FROM deps AS build
WORKDIR /repo/apps/web
RUN pnpm build

FROM node:22-alpine
WORKDIR /repo
RUN addgroup -S agrayian && adduser -S -G agrayian agrayian
RUN corepack enable
COPY --from=build /repo /repo
USER agrayian
WORKDIR /repo/apps/web
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD wget -qO- http://127.0.0.1:3000 >/dev/null || exit 1
CMD ["pnpm", "start"]
