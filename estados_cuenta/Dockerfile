ARG BUILD_FROM=python:3.12-slim
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# pdftotext (poppler) para leer el periodo de los PDF; qpdf para abrir los que traen contraseña
RUN apt-get update && apt-get install -y --no-install-recommends poppler-utils qpdf \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir requests==2.34.2 urllib3==2.8.0 PyYAML==6.0.3 tzdata==2025.2

WORKDIR /app
COPY estados ./estados
COPY run.sh /run.sh

# El servicio corre como un usuario sin privilegios; run.sh solo ajusta permisos y le pasa el control
RUN chmod +x /run.sh && useradd --create-home --uid 10001 app

CMD ["/run.sh"]
