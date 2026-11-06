# Cambios

## 1.0.2

- Avisos con `telegram_bot.send_message` (el `notify.telegram` de antes ya no existe en Home Assistant 2026.11): opciones `avisos_entidad` y `avisos_tema`.

## 1.0.1

- `modo = huella` solo necesita `nc_url`: sirve antes de llenar las contraseñas.

## 1.0.0

- Primera versión como add-on. Mismo servicio que corría en el VPS, con las contraseñas como opciones del add-on, avisos por el proxy del Supervisor y modos de prueba (`huella`, `probar-correo`, `probar-avisos`, `simular`).
- Guarda la carpeta que lee cada buzón y empieza de cero si cambia (Titan pone el mismo UIDVALIDITY en todas sus carpetas).
- Opciones de un solo uso `empezar_de_cero` y `releer_todo`.
