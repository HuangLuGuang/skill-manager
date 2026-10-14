FROM node:22-alpine AS build

WORKDIR /app/web

COPY web/package.json web/package-lock.json* ./
RUN npm install && npm audit --audit-level=low

COPY web/ ./
COPY client/desktop/src/event-records.js /app/client/desktop/src/event-records.js
RUN npm run test:i18n && npm run build

FROM nginx:1.27-alpine

COPY web/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/web/dist /usr/share/nginx/html

EXPOSE 80
