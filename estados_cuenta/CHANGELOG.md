# Cambios

## 1.0.4

- `nc_huella_sha256` ya es opcional: con un certificado válido (por ejemplo de Let's Encrypt) se deja vacía y el add-on verifica el certificado como un navegador, así que las renovaciones no lo detienen. La huella sigue sirviendo para certificados propios (autofirmados).
- Mensajes claros cuando el certificado no es de confianza o no coincide con la huella.

## 1.0.3

- Corrige 1.0.2: con `avisos.datos` se perdía la lista de bancos («No hay bancos activos»).

## 1.0.2

- Avisos con `telegram_bot.send_message` (el `notify.telegram` de antes ya no existe en Home Assistant 2026.11): opciones `avisos_entidad` y `avisos_tema`.

## 1.0.1

- `modo = huella` solo necesita `nc_url`: sirve antes de llenar las contraseñas.

## 1.0.0

- Primera versión como add-on. Mismo servicio que corría en el VPS, con las contraseñas como opciones del add-on, avisos por el proxy del Supervisor y modos de prueba (`huella`, `probar-correo`, `probar-avisos`, `simular`).
- Guarda la carpeta que lee cada buzón y empieza de cero si cambia (Titan pone el mismo UIDVALIDITY en todas sus carpetas).
- Opciones de un solo uso `empezar_de_cero` y `releer_todo`.
