FROM python:3.11-slim

# Install Go, FFmpeg, MediaInfo, and basic tools
RUN apt-get update && \
    apt-get install -y golang ffmpeg mediainfo wget unzip git ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Install Bento4 (provides mp4decrypt, correctly mapping the extracted folder)
RUN wget https://www.bok.net/Bento4/binaries/Bento4-SDK-1-6-0-640.x86_64-unknown-linux.zip && \
    unzip Bento4-SDK-1-6-0-640.x86_64-unknown-linux.zip && \
    cp Bento4-SDK-1-6-0-640.x86_64-unknown-linux/bin/mp4decrypt /usr/local/bin/ && \
    chmod +x /usr/local/bin/mp4decrypt && \
    rm -rf Bento4-SDK-1-6-0-640.x86_64-unknown-linux*

# Match the BASE_DIR hardcoded in your bot/config.py
WORKDIR /root/amdl/downloader

# Copy the entire repository
COPY . .

# Install the required Python packages
RUN pip install --no-cache-dir \
    pyrogram \
    tgcrypto \
    mutagen \
    aiohttp \
    certifi \
    requests \
    html_telegraph_poster

# Download Go modules
RUN if [ -f "go.mod" ]; then go mod download; fi

# Execute the bot as a module from the root directory
CMD ["python", "-m", "bot.main"]
