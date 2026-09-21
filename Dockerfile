# Container image for the bot.
#
# The image holds code AND content (data/ and media/). Content ships with every
# deploy, so adding a letter means: edit YAML -> git push -> Railway rebuilds.
# Runtime state (bot.db) is NOT in the image — it lives on a mounted volume,
# because anything written inside the container is wiped on redeploy.

FROM python:3.12-slim

# PYTHONUNBUFFERED: print logs immediately. Without it Python buffers stdout
#   and Railway's log view lags or loses the last lines before a crash.
# PYTHONDONTWRITEBYTECODE: no .pyc clutter in the image.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first, in their own layer. Docker caches layers, so a push that
# only changes a letter reuses this layer and skips the pip install entirely.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY data ./data
COPY media ./media

# The container clock stays UTC on purpose. Every schedule in the code carries
# Asia/Singapore explicitly, so correct times here prove the code is right —
# rather than being right by accident because the server happens to be local.
#
# Runs as root: Railway mounts volumes owned by root, and a non-root user
# could not write bot.db there without extra configuration.
CMD ["python", "-m", "app.main"]
