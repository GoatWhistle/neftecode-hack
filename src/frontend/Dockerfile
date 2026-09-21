FROM node:24-alpine AS build
WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci --silent
COPY . ./
RUN npm run build

FROM nginx:1.29-alpine AS runtime
RUN apk add --no-cache curl
COPY --from=build /build/dist/ /usr/share/nginx/html/
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=5 \
  CMD curl -fsS http://127.0.0.1/ -o /dev/null || exit 1
