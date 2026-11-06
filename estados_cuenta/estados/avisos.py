"""Avisos: por Home Assistant (p. ej. notify.telegram) o directo por Telegram. Si falla, reintenta."""
import logging

import requests

log = logging.getLogger("estados-cuenta")


class Notificador:
    def __init__(self, cfg, estado, simular=False):
        self.cfg = cfg
        self.estado = estado
        self.simular = simular
        self.activo = cfg.tipo != "registro" and bool(cfg.token) and (cfg.tipo != "telegram" or bool(cfg.chat_id))
        if cfg.tipo != "registro" and not self.activo:
            log.warning("Faltan los datos de avisos en .env (%s): los avisos solo se escriben en el log.",
                        "HA_TOKEN" if cfg.tipo == "home_assistant" else "TELEGRAM_TOKEN y TELEGRAM_CHAT_ID")

    def _enviar(self, texto):
        c = self.cfg
        if c.tipo == "home_assistant":
            dominio, servicio = c.servicio.split(".", 1)
            r = requests.post(f"{c.url}/api/services/{dominio}/{servicio}", timeout=20,
                              headers={"Authorization": f"Bearer {c.token}"}, json={"message": texto})
        else:
            r = requests.post(f"{c.url}/bot{c.token}/sendMessage", timeout=20,
                              json={"chat_id": c.chat_id, "text": texto, "disable_web_page_preview": True})
        if not r.ok:
            raise RuntimeError(f"respuesta {r.status_code}: {r.text[:200]}")

    def probar(self, texto):
        """Envía y deja que el error salga (para --probar-avisos)."""
        if not self.activo:
            raise RuntimeError("Los avisos no están configurados (revisa avisos en bancos.yml y el .env).")
        self._enviar(texto)

    def enviar(self, texto):
        if self.simular:
            log.info("[aviso, simulación] %s", texto)
            return True
        if not self.activo:
            log.info("[aviso] %s", texto)
            return True
        try:
            self._enviar(texto)
            log.info("Aviso enviado: %s", texto)
            return True
        except Exception as e:  # noqa: BLE001
            log.error("No pude enviar el aviso (%s); lo reintento en la próxima vuelta.", e)
            self.estado.d["pendientes"].append(texto)
            return False

    def reintentar(self):
        if self.simular or not self.activo or not self.estado.d["pendientes"]:
            return
        quedan = []
        for texto in self.estado.d["pendientes"]:
            try:
                self._enviar(texto)
                log.info("Aviso pendiente enviado: %s", texto)
            except Exception:  # noqa: BLE001
                quedan.append(texto)
        self.estado.d["pendientes"] = quedan
