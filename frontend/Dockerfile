FROM node:22-bookworm-slim@sha256:48e4b67d85f87bd551df43704e24d252f56cc5f8e9718841aace50f19948f0f9

WORKDIR /workspace/frontend

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

ARG NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
ARG NEXT_PUBLIC_AUTH_MODE=capability
ARG NEXT_PUBLIC_SELF_REGISTRATION_ENABLED=false
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL} \
    NEXT_PUBLIC_AUTH_MODE=${NEXT_PUBLIC_AUTH_MODE} \
    NEXT_PUBLIC_SELF_REGISTRATION_ENABLED=${NEXT_PUBLIC_SELF_REGISTRATION_ENABLED} \
    NODE_ENV=production

RUN npm run build

RUN groupadd --gid 10001 licenceiq \
    && useradd --uid 10001 --gid licenceiq --create-home --shell /usr/sbin/nologin licenceiq \
    && chown -R licenceiq:licenceiq /workspace/frontend

EXPOSE 3000

USER licenceiq

CMD ["./node_modules/.bin/next", "start", "--hostname", "0.0.0.0", "--port", "3000"]
