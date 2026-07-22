FROM python:3.9.19-slim-bookworm

ARG SPIDERFOOT_URL=https://api.github.com/repos/smicallef/spiderfoot/tarball/v4.0
ARG SPIDERFOOT_SHA256=c430c039ae66ea2f86020a6e25d672f83fe498f312d00a25c7cca76a958090b9

ENV SPIDERFOOT_DATA=/var/lib/spiderfoot \
    SPIDERFOOT_LOGS=/var/lib/spiderfoot/log \
    SPIDERFOOT_CACHE=/var/lib/spiderfoot/cache \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /opt/spiderfoot

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        curl \
        libffi-dev \
        libjpeg62-turbo-dev \
        libssl-dev \
        libxml2-dev \
        libxslt1-dev \
        zlib1g-dev \
    && curl --fail --location --silent --show-error "$SPIDERFOOT_URL" --output /tmp/spiderfoot.tar.gz \
    && echo "$SPIDERFOOT_SHA256  /tmp/spiderfoot.tar.gz" | sha256sum --check --strict \
    && tar --extract --gzip --file /tmp/spiderfoot.tar.gz --strip-components=1 \
    && python -m pip install --no-cache-dir --upgrade pip==25.1.1 \
    && python -m pip install --no-cache-dir --requirement requirements.txt \
    && apt-get purge -y --auto-remove build-essential curl \
    && rm -rf /var/lib/apt/lists/* /tmp/spiderfoot.tar.gz \
    && useradd --create-home --shell /usr/sbin/nologin spiderfoot \
    && mkdir -p "$SPIDERFOOT_DATA" "$SPIDERFOOT_LOGS" "$SPIDERFOOT_CACHE" \
    && chown -R spiderfoot:spiderfoot /opt/spiderfoot "$SPIDERFOOT_DATA"

USER spiderfoot

EXPOSE 5001

CMD ["python", "sf.py", "-l", "0.0.0.0:5001"]
