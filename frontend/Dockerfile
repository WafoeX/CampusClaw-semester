FROM node:22-alpine AS builder
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY index.html vite.config.ts tsconfig*.json eslint.config.js ./
COPY src ./src
RUN npm run build

FROM nginx:1.29-alpine AS runtime
RUN addgroup -S campusclaw \
    && adduser -S -G campusclaw campusclaw \
    && rm -f /etc/nginx/conf.d/default.conf \
    && mkdir -p /var/cache/nginx /var/log/nginx /var/lib/nginx /tmp/nginx \
    && chown -R campusclaw:campusclaw /var/cache/nginx /var/log/nginx /var/lib/nginx /tmp/nginx
COPY nginx.conf /etc/nginx/nginx.conf
COPY --from=builder /app/dist /usr/share/nginx/html
RUN chown -R campusclaw:campusclaw /usr/share/nginx/html /etc/nginx/nginx.conf
USER campusclaw
EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
