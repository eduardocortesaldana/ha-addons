"""Memoria del servicio entre reinicios (en el volumen /data)."""
import json
import os
import tempfile

_SECCIONES = {"buzones": dict, "avisos": dict, "recordatorios": dict, "ilegibles": dict, "pendientes": list}


class Estado:
    def __init__(self, ruta):
        self.ruta = ruta
        try:
            with open(ruta, encoding="utf-8") as f:
                self.d = json.load(f)
        except FileNotFoundError:
            self.d = {}
        for k, tipo in _SECCIONES.items():
            if not isinstance(self.d.get(k), tipo):
                self.d[k] = tipo()

    def guardar(self):
        carpeta = os.path.dirname(self.ruta) or "."
        os.makedirs(carpeta, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=carpeta, prefix=".estado-")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(self.d, f, ensure_ascii=False, indent=1, sort_keys=True)
        os.replace(tmp, self.ruta)

    def podar(self, anio, mes, meses=4):
        """Olvida avisos y recordatorios de periodos de hace más de `meses` meses."""
        limite = anio * 12 + mes - meses
        for seccion in ("avisos", "recordatorios"):
            for clave in list(self.d[seccion]):
                try:
                    a, m = clave.split("|", 1)[1].split("-")
                    if int(a) * 12 + int(m) < limite:
                        del self.d[seccion][clave]
                except (IndexError, ValueError):
                    del self.d[seccion][clave]
