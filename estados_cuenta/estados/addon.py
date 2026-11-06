"""Arranque como add-on de Home Assistant.

Lee las opciones del add-on (/data/options.json), arma con ellas el bancos.yml que usa el servicio,
pasa las contraseñas como variables de entorno y corre el servicio según la opción `modo`.
Las opciones de un solo uso (probar-correo, probar-avisos, huella, empezar_de_cero, releer_todo)
se regresan solas a su valor normal por la API del Supervisor, para que un reinicio no las repita.
"""
import json
import logging
import os
import sys
import urllib.request
from pathlib import Path

import yaml

from . import __main__ as principal
from . import nextcloud

log = logging.getLogger("estados-cuenta")

OPCIONES = Path(os.environ.get("ADDON_OPTIONS", "/data/options.json"))
CARPETA_CONFIG = Path(os.environ.get("ADDON_CONFIG_DIR", "/config"))
SUPERVISOR = os.environ.get("SUPERVISOR_URL", "http://supervisor").rstrip("/")

REGLA_PDF_BBVA = r"Periodo\s+DEL\s+\d{2}/\d{2}/\d{4}\s+AL\s+\d{2}/(?P<mes>\d{2})/(?P<anio>\d{4})"
OBLIGATORIAS = ("imap_servidor", "imap_usuario", "imap_clave", "nc_url", "nc_usuario", "nc_clave",
                "nc_carpeta", "imap_carpeta")


def leer_opciones():
    try:
        o = json.loads(OPCIONES.read_text(encoding="utf-8"))
    except FileNotFoundError:
        sys.exit(f"No encontré las opciones del add-on en {OPCIONES}.")
    faltan = [k for k in OBLIGATORIAS if not str(o.get(k, "") or "").strip()]
    if faltan:
        sys.exit("Faltan opciones: " + ", ".join(faltan)
                 + ". Llénalas en la pestaña Configuración del add-on y vuelve a iniciarlo.")
    return o


def armar_bancos_yml(o):
    """El bancos.yml del servicio, generado a partir de las opciones (sin contraseñas)."""
    return {
        "zona_horaria": o.get("zona_horaria") or "America/Mexico_City",
        "revisar_cada_min": int(o.get("revisar_cada_min") or 10),
        "recordatorios_entre": [10, 21],
        "avisos": {"tipo": "home_assistant", "url": f"{SUPERVISOR}/core",
                   "servicio": o.get("avisos_servicio") or "notify.telegram"},
        "buzones": {"principal": {"servidor": o["imap_servidor"], "puerto": int(o.get("imap_puerto") or 993),
                                  "usuario": o["imap_usuario"], "clave_env": "IMAP_CLAVE",
                                  "carpeta": o["imap_carpeta"]}},
        "bancos": {"bbva": {
            "activo": True,
            "nombre": o.get("bbva_nombre") or "BBVA",
            "carpeta": o["nc_carpeta"],
            "archivo": o.get("bbva_archivo") or "{anio}-{mes} BBVA.pdf",
            "pdf": {"contiene": "BBVA", "periodo": REGLA_PDF_BBVA, "clave_env": "BBVA_PDF_CLAVE"},
            "correo": {"buzon": "principal", "remitente": o.get("bbva_remitente") or "bbva.mx",
                       "asunto": r"Atenci[oó]n a Clientes BBVA", "texto": "te compartimos el estado de cuenta",
                       "guardar_adjunto": True},
            "recordatorio": {"desde_dia": int(o.get("recordatorio_desde_dia") or 5),
                             "cada_dias": int(o.get("recordatorio_cada_dias") or 2)},
        }},
    }


def preparar_entorno(o):
    CARPETA_CONFIG.mkdir(parents=True, exist_ok=True)
    ruta = CARPETA_CONFIG / "bancos.yml"
    texto = ("# Generado por el add-on a partir de sus opciones. Los cambios se hacen en la pestaña\n"
             "# Configuración del add-on; este archivo se vuelve a escribir en cada arranque.\n"
             + yaml.safe_dump(armar_bancos_yml(o), allow_unicode=True, sort_keys=False))
    ruta.write_text(texto, encoding="utf-8")
    os.environ.update({
        "CONFIG": str(ruta),
        "ESTADO": os.environ.get("ESTADO", "/data/estado.json"),
        "NC_URL": str(o["nc_url"]).strip(),
        "NC_USER": str(o["nc_usuario"]).strip(),
        "NC_APP_PASSWORD": str(o["nc_clave"]),
        "NC_CERT_SHA256": str(o.get("nc_huella_sha256") or "").strip(),
        "IMAP_CLAVE": str(o["imap_clave"]),
        "BBVA_PDF_CLAVE": str(o.get("bbva_pdf_clave") or ""),
        "HA_TOKEN": os.environ.get("SUPERVISOR_TOKEN", ""),
    })


def guardar_opciones(o):
    """Regresa a su valor normal las opciones de un solo uso, por la API del Supervisor."""
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        log.warning("Sin SUPERVISOR_TOKEN: no puedo regresar las opciones de un solo uso; cámbialas a mano.")
        return False
    req = urllib.request.Request(f"{SUPERVISOR}/addons/self/options", method="POST",
                                 data=json.dumps({"options": o}).encode("utf-8"),
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            r.read()
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("No pude regresar las opciones de un solo uso (%s). Cámbialas a mano en Configuración: "
                    "modo = simular o normal, empezar_de_cero = false, releer_todo = false.", e)
        return False


def correr_una_vez(args):
    """Corre una opción de prueba del servicio y no deja que un error tire el add-on."""
    try:
        principal.main(args)
    except SystemExit as e:
        if e.code not in (None, 0):
            log.error("%s", e.code)
    except Exception as e:  # noqa: BLE001
        log.error("Falló la prueba %s: %s", " ".join(args), e)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%Y-%m-%d %H:%M:%S")
    o = leer_opciones()
    preparar_entorno(o)
    modo = str(o.get("modo") or "simular")
    log.info("Add-on estados-cuenta. Modo: %s. Buzón: %s, carpeta «%s». Nextcloud: %s como %s, carpeta «%s».",
             modo, o["imap_usuario"], o["imap_carpeta"], o["nc_url"], o["nc_usuario"], o["nc_carpeta"])

    cambios = {}
    banderas = []
    if o.get("empezar_de_cero"):
        banderas.append("--desde-cero")
        cambios["empezar_de_cero"] = False
    if o.get("releer_todo"):
        banderas.append("--releer")
        cambios["releer_todo"] = False

    if modo == "huella":
        try:
            h = nextcloud.huella_servidor(os.environ["NC_URL"])
            log.info("Huella SHA-256 del certificado de Nextcloud: %s", h)
            log.info("Cópiala en la opción nc_huella_sha256 y vuelve a iniciar el add-on.")
        except Exception as e:  # noqa: BLE001
            log.error("No pude leer el certificado de %s: %s", os.environ["NC_URL"], e)
        cambios["modo"] = "simular"
        guardar_opciones({**o, **cambios})
        return
    if modo == "probar-avisos":
        correr_una_vez(["--probar-avisos"])
        cambios["modo"] = modo = "simular"
    elif modo == "probar-correo":
        correr_una_vez(["--probar-correo", "60"])
        cambios["modo"] = modo = "simular"

    if cambios:
        guardar_opciones({**o, **cambios})

    if modo == "simular":
        log.info("Simulación: muestra qué haría, sin guardar nada ni avisar, y no recuerda nada entre reinicios. "
                 "Para que trabaje de verdad, pon modo = normal y reinicia el add-on.")
        principal.main(banderas + ["--simular", "--seguir"])
    elif modo == "normal":
        principal.main(banderas)
    else:
        sys.exit(f"Modo desconocido: {modo}")


if __name__ == "__main__":
    main()
