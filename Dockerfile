FROM docker.m.daocloud.io/library/python:3.11-slim

RUN apt-get update && apt-get install -y git curl \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN npm install -g @anthropic-ai/claude-code

RUN mkdir -p /root/.claude && \
    echo '{"hasCompletedOnboarding":true,"hasTrustDialogAccepted":true,"autoUpdates":false}' \
    > /root/.claude/settings.json

RUN pip install --no-cache-dir lark-oapi

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

WORKDIR /app

CMD ["/entrypoint.sh"]
