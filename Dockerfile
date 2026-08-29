FROM python:3.11-slim

RUN apt-get update && \
    apt-get install -y golang ffmpeg mediainfo wget unzip git ca-certificates && \
    rm -rf /var/lib/apt/lists/*

RUN wget https://www.bok.net/Bento4/binaries/Bento4-SDK-1-6-0-640.x86_64-unknown-linux.zip && \
    unzip Bento4-SDK-1-6-0-640.x86_64-unknown-linux.zip && \
    cp Bento4-SDK-1-6-0-640.x86_64-unknown-linux/bin/mp4decrypt /usr/local/bin/ && \
    chmod +x /usr/local/bin/mp4decrypt && \
    rm -rf Bento4-SDK-1-6-0-640.x86_64-unknown-linux*

WORKDIR /root/amdl/downloader

COPY . .

ENV PYTHONPATH="/root/amdl/downloader"

RUN pip install --no-cache-dir \
    pyrogram \
    tgcrypto \
    mutagen \
    aiohttp \
    certifi \
    requests \
    html_telegraph_poster \
    python-telegram-bot

RUN if [ -f "go.mod" ]; then go mod download; fi

CMD ["python", "-m", "bot.main"]
