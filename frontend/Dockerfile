# Сборка статики фронтенда и раздача через nginx. Версии закреплены.
FROM node:24.18.1-alpine AS build
WORKDIR /app
# Кэш слоя зависимостей, пока не менялся lock-файл.
COPY package.json package-lock.json* ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.28.0-alpine AS runtime
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
