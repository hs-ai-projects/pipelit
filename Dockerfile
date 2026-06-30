FROM docker.m.daocloud.io/library/python:3.11-slim

RUN apt-get update && apt-get install -y git curl \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN npm install -g @anthropic-ai/claude-code@1.0.56

ENV CI=true \
    NO_UPDATE_NOTIFIER=1

RUN mkdir -p /root/.claude && \
    echo '{"hasCompletedOnboarding":true,"hasTrustDialogAccepted":true,"autoUpdates":false,"permissions":{"allow":["Bash(*)","Read(*)","Write(*)","Edit(*)","Glob(*)","Grep(*)","LS(*)"],"additionalDirectories":["/app","/tmp","/root"]}}' \
    > /root/.claude/settings.json

RUN pip install --no-cache-dir lark-oapi

RUN useradd -m -u 1000 bot && \
    mkdir -p /home/bot/.claude && \
    echo '{"hasCompletedOnboarding":true,"hasTrustDialogAccepted":true,"autoUpdates":false,"permissions":{"allow":["Bash(*)","Read(*)","Write(*)","Edit(*)","Glob(*)","Grep(*)","LS(*)"],"additionalDirectories":["/app","/tmp","/home/bot"]}}' \
    > /home/bot/.claude/settings.json && \
    chown -R bot:bot /home/bot && \
    apt-get update && apt-get install -y sudo && \
    echo 'bot ALL=(ALL) NOPASSWD: ALL' >> /etc/sudoers.d/bot

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

WORKDIR /app

CMD ["/entrypoint.sh"]
