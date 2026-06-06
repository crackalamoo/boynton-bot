FROM python:3.14-slim

RUN apt-get update && apt-get install -y \
    bash \
    curl \
    git \
    jq \
    nano \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /home
