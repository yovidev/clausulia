# 1) Build: pnpm vía corepack, con la versión fijada en package.json (packageManager)
FROM node:22-alpine AS build
WORKDIR /app
ENV COREPACK_ENABLE_DOWNLOAD_PROMPT=0
RUN corepack enable

# Solo dependencias: esta capa se reutiliza mientras no cambie el lockfile
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY . .
RUN pnpm build

# 2) Servir los estáticos con nginx, que además hace de proxy hacia la API
FROM nginx:alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
