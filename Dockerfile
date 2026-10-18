FROM python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2
WORKDIR /app
COPY requirements-model-lock.txt requirements-runtime-lock.txt ./
RUN pip install --no-cache-dir -r requirements-model-lock.txt -r requirements-runtime-lock.txt
COPY pyproject.toml ./
COPY src/ ./src/
RUN pip install --no-cache-dir --no-deps . \
    && useradd --uid 10001 --create-home gridcast \
    && mkdir -p /app/data && chown -R gridcast:gridcast /app
USER 10001:10001
ENTRYPOINT ["python", "-m", "gridcast.jobs"]
CMD ["--help"]
