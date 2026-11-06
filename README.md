# Add-ons de Lalo para Home Assistant

Repositorio de add-ons para Home Assistant OS. Para usarlo: **Ajustes → Add-ons → Tienda de add-ons → ⋮ → Repositorios**, pegar `https://github.com/eduardocortesaldana/ha-addons` y agregar. Los add-ons aparecen al final de la tienda.

| Add-on | Qué hace |
|---|---|
| [Estados de cuenta](estados_cuenta/) | Lee el correo del banco en solo lectura, guarda cada estado de cuenta en Nextcloud (una copia sin contraseña, nombrada por mes) y avisa por Telegram a través de Home Assistant. Si el día 5 no está el estado del mes anterior, lo recuerda. |

Las imágenes se construyen en el propio equipo al instalar (solo `amd64`). Ninguna contraseña ni configuración personal vive en este repositorio: todo se captura en las opciones de cada add-on.
