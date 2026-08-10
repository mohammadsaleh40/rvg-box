# rvg-box روی Railway — بیلد Dockerfile (نسخه‌ی pin شده sing-box، بدون xhttp)
FROM debian:bookworm-slim

ARG TARGETARCH

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && case "$TARGETARCH" in \
         amd64) A=amd64 ;; \
         arm64) A=arm64 ;; \
         arm)   A=armv7 ;; \
         *) echo "unsupported arch: $TARGETARCH" >&2; exit 1 ;; \
       esac \
    && curl -fsSLo /tmp/sing-box.tar.gz \
         "https://github.com/SagerNet/sing-box/releases/download/v1.13.18/sing-box-1.13.18-linux-${A}.tar.gz" \
    && tar -xzf /tmp/sing-box.tar.gz -C /usr/local/bin --strip-components=1 \
         "sing-box-1.13.18-linux-${A}/sing-box" \
    && chmod +x /usr/local/bin/sing-box \
    && rm -f /tmp/sing-box.tar.gz \
    && apt-get purge -y --auto-remove curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY rvgbox.py railway-entrypoint.sh ./
RUN chmod +x railway-entrypoint.sh

# Railway پورت واقعی را با $PORT تزریق می‌کند؛ این EXPOSE فقط برای شفافیت است
EXPOSE 8080

CMD ["./railway-entrypoint.sh"]