
FROM node:22-bookworm-slim

ENV NODE_ENV=production
ENV TZ=Europe/Oslo

RUN apt-get update && apt-get install -y \
    libnss3 \
    libdbus-1-3 \
    libatk1.0-0 \
    libgbm-dev \
    libasound2 \
    libxrandr2 \
    libxkbcommon-dev \
    libxfixes3 \
    libxcomposite1 \
    libxdamage1 \
    libatk-bridge2.0-0 \
    libpango-1.0-0 \
    libcairo2 \
    libcups2 \
    ffmpeg \
    fonts-noto \
    fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY package.json ./

RUN npm install --omit=dev

RUN npx remotion browser ensure

COPY src ./src
COPY public ./public

RUN mkdir -p /data/videos

EXPOSE 8100

CMD ["npm", "start"]
