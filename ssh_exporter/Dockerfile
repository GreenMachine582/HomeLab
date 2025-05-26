FROM alpine:latest

WORKDIR /app

RUN apk add --no-cache curl && \
    curl -L -o ssh_exporter.tar.gz https://github.com/schnej7/ssh_exporter/releases/download/v1.0.1/ssh_exporter-1.0.1-linux-armv7.tar.gz && \
    tar xzf ssh_exporter.tar.gz && \
    mv ssh_exporter /usr/local/bin/ && \
    rm ssh_exporter.tar.gz

EXPOSE 9312

ENTRYPOINT ["/usr/local/bin/ssh_exporter"]
