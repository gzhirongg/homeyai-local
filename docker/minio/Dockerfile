FROM golang:1.24-bookworm AS build
# Build the official archived source; its public Docker Hub/Quay images are unavailable.
ARG MINIO_COMMIT=7aac2a2c5b7c882e68c1ce017d8256be2feea27f
RUN CGO_ENABLED=0 GOBIN=/out go install github.com/minio/minio@${MINIO_COMMIT}

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl && rm -rf /var/lib/apt/lists/*
COPY --from=build /out/minio /usr/local/bin/minio
EXPOSE 9000 9001
ENTRYPOINT ["minio"]
