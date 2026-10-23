FROM python:3.13-slim@sha256:57b29a7c050c4e679e4bea572e14b3965cf4b5839de2da49d55e49ffc4024f39
ENV PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
COPY scorer/requirements.lock /tmp/requirements.lock
RUN pip install --require-hashes -r /tmp/requirements.lock
COPY pyproject.toml /src/pyproject.toml
COPY src /src/src
RUN pip install --no-deps /src && rm -rf /src
WORKDIR /work
