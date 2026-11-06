# Estados de cuenta

Revisa cada 10 minutos una carpeta de tu buzón (por IMAP, en solo lectura: no marca nada como leído ni mueve correos). Cuando llega el estado de cuenta de BBVA, abre el PDF con su contraseña, guarda en Nextcloud una copia sin contraseña con el nombre `AAAA-MM BBVA.pdf` y te avisa por Telegram a través de Home Assistant. También renombra los PDF que subas a mano a esa carpeta, y del día 5 en adelante te recuerda cada 2 días si falta el estado del mes anterior.

Los avisos son solo texto (banco, mes y nombre del archivo); el PDF nunca sale por Telegram.

## Antes de instalar

1. **Contraseña de aplicación del buzón.** En Titan: ajustes de seguridad de la cuenta, con la verificación en dos pasos activa, y «Enable Titan on other apps» en el engrane del correo web. En Gmail: Cuenta de Google → Seguridad → Contraseñas de aplicaciones.
2. **Usuario de Nextcloud para el servicio** (recomendado): crea un usuario aparte (por ejemplo `servicio`), compártele solo la carpeta de los estados de cuenta con permiso de editar, y genera una contraseña de aplicación para ese usuario (Ajustes personales → Seguridad). Así la llave del servicio no abre tus demás archivos. En el usuario que recibe la carpeta compartida, la carpeta aparece en su raíz con el mismo nombre: eso es lo que va en `nc_carpeta`.
3. **Contraseña de los PDF de BBVA**, la que te pide el PDF que llega por correo.

## Opciones

| Opción | Qué es |
|---|---|
| `modo` | `simular`: muestra qué haría, sin guardar ni avisar, y no recuerda nada entre reinicios. `normal`: trabaja de verdad. `probar-correo`, `probar-avisos` y `huella`: pruebas de un solo uso (ver abajo). |
| `imap_servidor`, `imap_puerto`, `imap_usuario`, `imap_clave` | El buzón. Puerto 993 con TLS. |
| `imap_carpeta` | La carpeta del buzón donde caen los estados. `INBOX` es la bandeja; las subcarpetas van con `/`, por ejemplo `Bancos/BBVA/Estados de Cuenta`. |
| `nc_url` | Nextcloud, por ejemplo `https://nube.midominio.com` o `https://192.168.0.183:8099`. |
| `nc_usuario`, `nc_clave` | El usuario del servicio y su contraseña de aplicación. |
| `nc_huella_sha256` | Solo si Nextcloud usa un **certificado propio (autofirmado)**: su huella SHA-256, que se saca con `modo = huella`. Si Nextcloud tiene un certificado válido (por ejemplo de Let's Encrypt), **déjala vacía**: el add-on lo verifica como un navegador y no hay que tocar nada cuando el certificado se renueve. |
| `nc_carpeta` | Carpeta de Nextcloud donde se guardan los estados, vista desde `nc_usuario`. |
| `bbva_nombre`, `bbva_archivo` | Cómo se llama el banco en los avisos y cómo se nombra cada archivo (`{anio}` y `{mes}` se sustituyen). |
| `bbva_pdf_clave` | Contraseña de los PDF que manda BBVA. |
| `bbva_remitente` | Dominio o dirección del banco (`bbva.mx` cubre cualquier `@bbva.mx`). |
| `avisos_servicio` | El servicio de Home Assistant que manda el aviso. Con la integración de Telegram actual es `telegram_bot.send_message`. |
| `avisos_entidad` | La entidad del chat de Telegram, por ejemplo `notify.casa_ha` (se ve en Ajustes → Dispositivos → Telegram). Vacío manda al chat por defecto del bot. |
| `avisos_tema` | Si el grupo tiene temas, el número del tema donde caen los avisos. `0` manda al general. |
| `recordatorio_desde_dia`, `recordatorio_cada_dias` | Desde qué día del mes recordar que falta el estado, y cada cuántos días. |
| `empezar_de_cero` | Un solo uso: olvida en qué correo iba y avisa solo de lo que llegue desde ahora. Se regresa a `false` sola. |
| `releer_todo` | Un solo uso: procesa todos los correos de la carpeta. Lo que ya está en Nextcloud no se repite ni se avisa. Se regresa a `false` sola. |

## Cómo ponerlo en marcha

1. Instala el add-on y llena las opciones. Si tu Nextcloud tiene un certificado válido (Let's Encrypt u otro), deja `nc_huella_sha256` vacía y pasa al punto 2. Si usa un certificado propio (autofirmado), déjalo en `modo = huella`, inícialo y abre su registro: muestra la huella del certificado. Cópiala en `nc_huella_sha256`. El add-on se detiene solo.
2. `modo = probar-correo` e inicia: el registro muestra los correos del banco de los últimos 60 días y qué haría con cada uno («guardaría el PDF» es la señal de que abre los PDF y reconoce el mes). Después sigue solo en simulación.
3. `modo = probar-avisos` y reinicia: debe llegar un mensaje de prueba por Telegram. Después sigue en simulación.
4. Déjalo en simulación un rato y revisa el registro: cada vuelta dice qué haría.
5. `modo = normal` y reinicia. El registro dice `Buzón "principal" (...) listo: aviso de los correos que lleguen desde ahora`. Desde ese momento trabaja de verdad.

Las pruebas de un solo uso regresan `modo` a `simular` por sí solas, para que un reinicio no las repita.

## Cosas a saber

- Cambiar `imap_carpeta` hace que el add-on empiece de cero en la carpeta nueva: avisa de lo que llegue desde ahí, no de lo viejo. (Titan pone el mismo identificador en todas sus carpetas, así que el add-on guarda también el nombre de la carpeta para notarlo.)
- `releer_todo` sirve para probar de punta a punta sin esperar al banco: mueve un estado fuera de la carpeta de Nextcloud, activa `releer_todo`, reinicia, y el add-on lo vuelve a guardar y avisa.
- Si Nextcloud o Home Assistant no responden en una vuelta, lo reintenta en la siguiente; los avisos pendientes se guardan.
- La memoria del add-on (`/data/estado.json`) y sus opciones entran en los respaldos de Home Assistant. El `bancos.yml` que genera queda en la carpeta de configuración del add-on, solo para consulta.
- El registro no muestra contraseñas.
- Si el registro dice «No confío en el certificado de Nextcloud», el certificado es propio: saca su huella con `modo = huella`. Si dice «no coincide con la huella fijada», el certificado cambió: saca la huella nueva, o deja `nc_huella_sha256` vacía si ya es un certificado válido.
