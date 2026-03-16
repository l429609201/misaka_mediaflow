# Go 反代服务 Dockerfile — 多阶段构建 (独立部署时使用)
FROM golang:1.22-alpine AS builder

WORKDIR /build
COPY go.mod go.sum ./
RUN go mod download

COPY . .

ARG VERSION=dev
ARG TARGETARCH
RUN CGO_ENABLED=0 GOOS=linux GOARCH=${TARGETARCH} go build \
    -ldflags "-X main.Version=${VERSION} -s -w" \
    -o /build/proxy \
    ./cmd/proxy/

# 运行阶段
FROM alpine:3.20

RUN apk add --no-cache ca-certificates tzdata

COPY --from=builder /build/proxy /usr/local/bin/proxy

RUN mkdir -p /data/config

EXPOSE 9906

ENTRYPOINT ["proxy"]

