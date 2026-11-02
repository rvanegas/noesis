FROM python:3.13-slim

# pandoc and XeTeX for `noesis pdf` (about 1 GB, used rarely); diff for `noesis diff`.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      pandoc texlive-xetex lmodern texlive-fonts-recommended diffutils \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml ./
COPY noesis/ noesis/
# The test extra so `pytest tests/` runs in the image (SERVER.md's smoke test).
RUN pip install --no-cache-dir ".[test]"
COPY tests/ tests/
# The tests of the scripts load them from here.
COPY scripts/ scripts/
COPY etc/config.toml /etc/noesis/config.toml

EXPOSE 8001
CMD ["noesis", "serve", "--host", "0.0.0.0", "--port", "8001"]
