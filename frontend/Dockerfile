# --- build ---------------------------------------------------------------
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
ARG VITE_API_BASE_URL=""
ARG VITE_MAP_STYLE_LIGHT=""
ARG VITE_MAP_STYLE_DARK=""
# Public by design: map keys are sent by the browser. Restrict it by domain in the CARTO dashboard if offered.
ARG VITE_CARTO_API_KEY=""
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL VITE_MAP_STYLE_LIGHT=$VITE_MAP_STYLE_LIGHT \
    VITE_MAP_STYLE_DARK=$VITE_MAP_STYLE_DARK VITE_CARTO_API_KEY=$VITE_CARTO_API_KEY
RUN npm run build

# --- serve ---------------------------------------------------------------
FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
