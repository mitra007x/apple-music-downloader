ARG GOVERSION=1.23.1

FROM --platform=$BUILDPLATFORM golang:${GOVERSION}-alpine AS builder
ARG TARGETOS
ARG TARGETARCH
WORKDIR /app
COPY . .
RUN --mount=type=cache,target=/go/pkg/mod/ \
    go mod tidy && \
    CGO_ENABLED=0 GOOS=${TARGETOS} GOARCH=${TARGETARCH} go build -o /bin/apple-music-dl main.go

FROM python:3.11-slim
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg mediainfo && \
    rm -rf /var/lib/apt/lists/*

COPY --from=builder /bin/apple-music-dl /usr/local/bin/apple-music-dl

WORKDIR /app

COPY bot/requirements.txt bot/requirements.txt
RUN pip install --no-cache-dir -r bot/requirements.txt

COPY config.yaml.example config.yaml
RUN sed -i 's/^alac-save-folder:.*/alac-save-folder: "down"/' config.yaml \
    && sed -i 's/^atmos-save-folder:.*/atmos-save-folder: "down"/' config.yaml \
    && sed -i 's/^aac-save-folder:.*/aac-save-folder: "down"/' config.yaml \
    && sed -i 's/^mv-save-folder:.*/mv-save-folder: "down"/' config.yaml

COPY . .

CMD ["python3", "-m", "bot.main"]
