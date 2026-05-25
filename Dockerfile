# =============================================================================
# AI Face Attendance System — Dockerfile
# =============================================================================
# Multi-stage build:
#   Stage 1 (builder): compile dlib and face_recognition with all build deps.
#   Stage 2 (runtime): copy compiled wheels into a slim image.
#
# Why multi-stage?
#   dlib requires cmake, boost, and a C++ compiler (~1.5 GB of build tools).
#   The runtime image needs none of these — dropping build tools reduces the
#   final image from ~3 GB to ~900 MB and eliminates unnecessary attack surface.
#
# Build:
#   docker build -t attendance-system:latest .
#
# Run (FastAPI only):
#   docker run -p 8000:8000 --env-file .env attendance-system:latest
#
# Run (full stack via docker-compose):
#   docker-compose up
# =============================================================================

# ---- Stage 1: builder -------------------------------------------------------
FROM python:3.11-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        cmake \
        libopenblas-dev \
        liblapack-dev \
        libx11-dev \
        libatlas-base-dev \
        libgtk-3-dev \
        pkg-config \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

COPY requirements.txt .

# Build wheels into a local directory so the runtime stage can install them
# without re-downloading or re-compiling.
RUN pip install --upgrade pip && \
    pip wheel --no-cache-dir --wheel-dir=/wheels -r requirements.txt


# ---- Stage 2: runtime -------------------------------------------------------
FROM python:3.11-slim AS runtime

LABEL maintainer="Mohamad Ali Sayed Ahmad <moeysayedahmad760@gmail.com>" \
      description="AI Face Recognition Attendance System" \
      version="1.0.0"

# Runtime shared libraries needed by OpenCV and dlib
RUN apt-get update && apt-get install -y --no-install-recommends \
        libopenblas0 \
        liblapack3 \
        libgl1 \
        libglib2.0-0 \
        libsm6 \
        libxext6 \
        libxrender1 \
    && rm -rf /var/lib/apt/lists/*

# Non-root user for security
RUN useradd --create-home --shell /bin/bash attendance
WORKDIR /app

# Install from pre-built wheels (no compiler needed).
# Uses opencv-python-headless (no display server in container).
# Test-only deps (pytest, httpx, etc.) are intentionally omitted.
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links=/wheels \
        fastapi uvicorn pydantic PyJWT cryptography slowapi \
        numpy face-recognition opencv-python-headless \
        pandas openpyxl Pillow streamlit requests flask ttkbootstrap \
    && rm -rf /wheels

# Copy application source (respect .dockerignore)
COPY --chown=attendance:attendance . .

USER attendance

# FastAPI runs on 8000; Streamlit on 8501
EXPOSE 8000 8501

# Health check — probes the /health endpoint which runs a DB connectivity check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" \
    || exit 1

# Default command: FastAPI via uvicorn
# Override in docker-compose for the Streamlit container.
CMD ["python", "-m", "uvicorn", "api.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--log-level", "info"]
