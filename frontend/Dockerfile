# Built from the project folder (see docker-compose.yml), because the help pages live outside frontend/.

# The help pages (docs/ -> static HTML).
FROM python:3.13-slim AS help
WORKDIR /src
COPY docs/requirements.txt docs/requirements.txt
RUN pip install --no-cache-dir -r docs/requirements.txt
COPY mkdocs.yml .
COPY docs docs
RUN mkdocs build --strict --site-dir /site

# The interface.
FROM node:22-alpine AS build
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build

FROM nginx:1.30-alpine
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /web/dist /usr/share/nginx/html
COPY --from=help /site /usr/share/nginx/html/help
EXPOSE 80
