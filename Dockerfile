FROM python:3.11-slim

# Install Go, FFmpeg, MediaInfo, and basic tools
RUN apt-get update && \
    apt-get install -y golang ffmpeg mediainfo wget unzip git ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Install Bento4
RUN wget https://www.bok.net/Bento4/binaries/Bento4-SDK-1-6-0-640.x86_64-unknown-linux.zip && \
    unzip Bento4-SDK-1-6-0-640.x86_64-unknown-linux.zip && \
    cp Bento4-SDK-1-6-0-640.x86_64-unknown-linux/bin/mp4decrypt /usr/local/bin/ && \
    chmod +x /usr/local/bin/mp4decrypt && \
    rm -rf Bento4-SDK-1-6-0-640.x86_64-unknown-linux*

WORKDIR /root/amdl/downloader

# Copy the entire repository into the container
COPY . .

# Set Python path
ENV PYTHONPATH="/root/amdl/downloader"

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

# MAGIC FIX: Automatically create the __init__.py file inside the container so Git can't ignore it!
RUN mkdir -p bot && touch bot/__init__.py

# Start the bot, and if it fails, automatically print the directory structure for debugging!
CMD sh -c "python -m bot.main || (echo '\n\n❌ CRASH DETECTED. PRINTING DIRECTORY STRUCTURE FOR DEBUGGING:' && ls -la && echo '\n--- BOT FOLDER CONTENTS ---' && ls -la bot && exit 1)"
