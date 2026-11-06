#!/usr/bin/env bash
# Arranque del add-on: /data (memoria y opciones) y /config (bancos.yml generado) los monta el Supervisor
# como root; se entregan al usuario sin privilegios y el servicio corre como él.
set -e
mkdir -p /data /config
chown -R app:app /data /config
exec setpriv --reuid=app --regid=app --init-groups -- python -m estados.addon
