FROM node:20-alpine AS builder
WORKDIR /app
COPY dashboard/package*.json ./
RUN npm ci --silent
COPY dashboard/ ./
RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY dashboard/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 3000
CMD ["nginx", "-g", "daemon off;"]
