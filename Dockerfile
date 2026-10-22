FROM node:22-bookworm-slim AS frontend
WORKDIR /src
COPY platform/next-ui/package*.json ./
RUN npm ci
COPY platform/next-ui/ ./
RUN npm run build

FROM eclipse-temurin:21-jdk-jammy AS template-build
WORKDIR /build
COPY vendor/java/ ./lib/
COPY platform/native-template/*.java ./
RUN mkdir classes && javac -proc:none -cp 'lib/*' -d classes NativeCredentialTemplate.java NativeCredentialCanonicalizer.java

FROM eclipse-temurin:21-jre-jammy AS java-runtime
FROM caddy:2 AS proxy

FROM python:3.12-slim-bookworm AS dependencies
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 JAVA_HOME=/opt/java/openjdk \
    PYTHONPATH=/app/platform:/app/deployment PATH=/opt/java/openjdk/bin:$PATH \
    KDBT_DEPLOYMENT_MODE=local XDG_DATA_HOME=/runtime
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libmagic1 libpq5 ca-certificates fonts-noto-core && rm -rf /var/lib/apt/lists/*
COPY requirements*.txt ./
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
FROM dependencies AS application
ENV SSL_CERT_FILE=/runtime/tls/combined-ca.crt REQUESTS_CA_BUNDLE=/runtime/tls/combined-ca.crt
COPY --from=java-runtime /opt/java/openjdk /opt/java/openjdk
COPY --from=proxy /usr/bin/caddy /usr/bin/caddy
COPY --from=template-build /build /app/template-runtime
COPY platform ./platform
COPY schemas ./schemas
COPY deployment ./deployment
COPY --from=frontend /src/out ./platform/next-ui/out
VOLUME /runtime
EXPOSE 8443-8469
CMD ["python", "deployment/supervisor.py"]
