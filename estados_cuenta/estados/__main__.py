"""Punto de entrada: python -m estados [opción]"""
import logging
import os
import sys
import time
from datetime import datetime

from . import config, nextcloud
from .avisos import Notificador
from .estado import Estado
from .servicio import Servicio

log = logging.getLogger("estados-cuenta")

AYUDA = """Uso: python -m estados [opción]
  (sin opción)          corre para siempre
  --una-vez             una sola vuelta
  --simular             una vuelta mostrando qué haría, sin cambiar nada ni mandar avisos
  --probar-avisos       manda un aviso de prueba
  --probar-correo [N]   muestra los correos de los bancos de los últimos N días (60 por omisión)
  --huella              muestra la huella SHA-256 del certificado de Nextcloud
  --desde-cero          olvida en qué correo iba cada buzón: avisa solo de lo que llegue desde ahora
  --releer              una vez: procesa todos los correos de la carpeta (lo que ya está en Nextcloud no se repite)
  --seguir              con --simular: no parar después de una vuelta
"""


def main(args=None):
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")
    args = sys.argv[1:] if args is None else list(args)
    if "-h" in args or "--help" in args:
        print(AYUDA)
        return

    if "--huella" in args:
        url = os.environ.get("NC_URL", "").strip()
        if not url.startswith("https://"):
            sys.exit("NC_URL debe empezar con https://")
        print(nextcloud.huella_servidor(url))
        return

    try:
        cfg = config.cargar()
        nc = nextcloud.Nextcloud(**cfg.nextcloud)
    except config.ErrorConfig as e:
        sys.exit(f"Error de configuración: {e}")

    simular = "--simular" in args
    est = Estado(os.environ.get("ESTADO", "/data/estado.json"))
    if "--desde-cero" in args and est.d["buzones"]:
        log.info("Olvido en qué correo iba cada buzón (%s): aviso solo de lo que llegue desde ahora.",
                 ", ".join(sorted(est.d["buzones"])))
        est.d["buzones"] = {}
        if not simular:
            est.guardar()
    av = Notificador(cfg.avisos, est, simular)
    ahora = None
    if os.environ.get("ESTADOS_AHORA"):  # solo para pruebas: fija la fecha y hora
        ahora = datetime.fromisoformat(os.environ["ESTADOS_AHORA"]).replace(tzinfo=cfg.zona)
    srv = Servicio(cfg, est, nc, av, simular=simular, ahora=ahora,
                   edad_min_seg=float(os.environ.get("EDAD_MIN_SEG", "120")), releer="--releer" in args)

    if "--probar-avisos" in args:
        try:
            av.probar("🔔 estados-cuenta: los avisos funcionan.")
        except Exception as e:  # noqa: BLE001
            sys.exit(f"No se pudo mandar el aviso: {e}")
        print("Aviso de prueba enviado.")
        return

    if "--probar-correo" in args:
        i = args.index("--probar-correo")
        dias = int(args[i + 1]) if i + 1 < len(args) and args[i + 1].isdigit() else 60
        try:
            srv.probar_correo(dias)
        except Exception as e:  # noqa: BLE001
            sys.exit(f"Error al revisar el correo: {e}")
        return

    if not cfg.bancos:
        log.warning("No hay bancos activos en bancos.yml.")
    for b in cfg.bancos:
        partes = [f'carpeta "{b.carpeta}"']
        if b.correo:
            partes.append(f"correo de {b.correo.remitente} en {cfg.buzones[b.correo.buzon].usuario}"
                          + (" (guarda el PDF)" if b.correo.guardar_adjunto else ""))
        if b.recordatorio:
            partes.append(f"recordatorio desde el día {b.recordatorio.desde_dia}, cada {b.recordatorio.cada_dias} días")
        if not b.pdf_periodo:
            partes.append("sin regla para leer el PDF")
        elif b.pdf_clave_env:
            partes.append("abre los PDF con contraseña" if b.pdf_clave
                          else f"falta {b.pdf_clave_env} en .env para abrir los PDF con contraseña")
        log.info("%s: %s", b.nombre, "; ".join(partes))
    log.info("Avisos por %s%s", cfg.avisos.tipo, " (simulación)" if simular else "")

    una_vez = "--una-vez" in args or (simular and "--seguir" not in args)
    while True:
        srv.ciclo()
        if una_vez:
            return
        time.sleep(cfg.revisar_cada_min * 60)


if __name__ == "__main__":
    main()
