FROM node:22-alpine
WORKDIR /repo
RUN corepack enable
COPY package.json pnpm-workspace.yaml ./
COPY apps/web ./apps/web
COPY packages ./packages
RUN pnpm install
WORKDIR /repo/apps/web
RUN pnpm build
EXPOSE 3000
CMD ["pnpm", "start"]
