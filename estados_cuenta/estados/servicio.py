"""Una vuelta del servicio: correo -> carpetas -> recordatorios."""
import hashlib
import logging
import time
from datetime import date, datetime, timedelta

from . import correo, pdf
from .config import etiqueta_mes, mes_anterior

log = logging.getLogger("estados-cuenta")


class Servicio:
    def __init__(self, cfg, estado, nc, avisos, simular=False, ahora=None, edad_min_seg=120, releer=False):
        self.cfg = cfg
        self.estado = estado
        self.nc = nc
        self.avisos = avisos
        self.simular = simular
        self._ahora_fijo = ahora          # solo para pruebas
        self.edad_min_seg = edad_min_seg  # no tocar archivos que se acaban de subir
        self.releer = releer              # una vez: procesar todos los correos de la carpeta, no solo los nuevos

    def ahora(self):
        return self._ahora_fijo or datetime.now(self.cfg.zona)

    def hoy(self):
        return self.ahora().date()

    # ------------------------------------------------------------------ vuelta completa
    def ciclo(self):
        self.avisos.reintentar()
        for nombre, paso in (("correo", self.revisar_correo), ("carpetas", self.revisar_carpetas),
                             ("recordatorios", self.revisar_recordatorios)):
            try:
                paso()
            except Exception as e:  # noqa: BLE001 - un paso que falla no debe frenar a los demás
                log.error("Al revisar %s: %s", nombre, e)
        h = self.hoy()
        self.estado.podar(h.year, h.month)
        if not self.simular:
            self.estado.guardar()

    # ------------------------------------------------------------------ utilidades
    def _por_buzon(self):
        grupos = {}
        for b in self.cfg.bancos:
            if b.correo:
                grupos.setdefault(b.correo.buzon, []).append(b)
        return grupos

    def _presente(self, b, anio, mes):
        for nombre in self.nc.listar(b.carpeta) or {}:
            m = b.patron_listo.match(nombre)
            if m and int(m.group("anio")) == anio and int(m.group("mes")) == mes:
                return True
        return False

    # ------------------------------------------------------------------ correo
    def revisar_correo(self):
        for buzon_id, bancos in self._por_buzon().items():
            buzon = self.cfg.buzones[buzon_id]
            with correo.Lector(buzon) as lec:
                st = self.estado.d["buzones"].get(buzon_id)
                # Se guarda también la carpeta: Titan pone el mismo UIDVALIDITY en todas sus carpetas,
                # así que un cambio de carpeta no se notaría solo por el número.
                nuevo = (not st or st.get("uidvalidity") != lec.uidvalidity
                         or st.get("carpeta", "INBOX") != buzon.carpeta)
                if self.releer:
                    st = {"uidvalidity": lec.uidvalidity, "ultimo_uid": 0, "carpeta": buzon.carpeta}
                    self.estado.d["buzones"][buzon_id] = st
                    log.info('Buzón "%s" (%s): releyendo todos los correos de la carpeta "%s" (lo que ya '
                             'está en Nextcloud no se repite).', buzon_id, buzon.usuario, buzon.carpeta)
                elif nuevo:
                    # Primera vez, cambio de carpeta o el servidor renumeró: no avisar de correos viejos
                    self.estado.d["buzones"][buzon_id] = {"uidvalidity": lec.uidvalidity,
                                                          "ultimo_uid": lec.ultimo_uid(),
                                                          "carpeta": buzon.carpeta}
                    log.info('Buzón "%s" (%s, carpeta "%s") listo: aviso de los correos que lleguen desde ahora.',
                             buzon_id, buzon.usuario, buzon.carpeta)
                    continue
                tope = lec.ultimo_uid()
                uids = sorted({u for b in bancos for u in lec.buscar(correo.termino_busqueda(b.correo.remitente),
                                                                     desde_uid=st["ultimo_uid"] + 1)})
                for uid in uids:
                    msg = lec.traer(uid)
                    if msg is not None:
                        for b in bancos:
                            self._procesar_correo(b, msg)
                    st["ultimo_uid"] = max(st["ultimo_uid"], uid)  # avanzar correo por correo
                st["ultimo_uid"] = max(st["ultimo_uid"], tope)
        self.releer = False

    def _decidir(self, b, msg):
        """Qué hacer con un correo, sin efectos. Devuelve (tipo, periodo, pdf_a_guardar, nota):
        tipo 'guardar' (trae el estado y se guarda), 'avisar' (salió el estado; descárgalo),
        'raro' (trae un PDF que parece estado pero no lo reconocí) o None (no es de esto)."""
        if not correo.remitente_coincide(b.correo.remitente, msg):
            return None, None, None, ""
        adjuntos = correo.pdfs(msg)
        # 1) Por el contenido del PDF: no depende del asunto ni del texto del correo
        if adjuntos and b.pdf_periodo:
            for _, crudo in adjuntos:
                abierto = pdf.abrir(crudo, b.pdf_clave)
                per = pdf.periodo(b, pdf.a_texto(abierto)) if abierto else None
                if per:
                    if b.correo.guardar_adjunto:
                        return "guardar", per, abierto, ""
                    return "avisar", per, None, ""
        # 2) Por asunto y texto del correo (por si el PDF no se pudo abrir o no viene)
        per = correo.coincide(b, msg, self.cfg.zona)
        if per:
            if adjuntos and b.correo.guardar_adjunto and not b.pdf_periodo:
                return "guardar", per, adjuntos[0][1], ""  # banco sin regla de PDF: se guarda tal cual
            nota = ""
            if adjuntos and b.pdf_periodo:
                nota = (" No pude abrir el PDF del correo con la contraseña de .env." if b.pdf_clave else
                        f" El PDF del correo trae contraseña; si la pones en .env ({b.pdf_clave_env or 'clave_env'}), "
                        "lo guardo solo.")
            return "avisar", per, None, nota
        # 3) Trae PDF y habla de estado de cuenta, pero nada coincidió: quizá el banco cambió el formato
        if adjuntos and "estado de cuenta" in f"{correo.asunto(msg)} {correo.texto(msg)}".lower():
            return "raro", None, None, ""
        return None, None, None, ""

    def _procesar_correo(self, b, msg):
        tipo, per, datos, nota = self._decidir(b, msg)
        if tipo in ("guardar", "avisar"):
            self._estado_recibido(b, *per, datos=datos, nota=nota)
        elif tipo == "raro":
            self.avisos.enviar(f"⚠️ {b.nombre}: llegó un correo con un PDF que no reconocí "
                               f"(«{correo.asunto(msg)[:60]}»). Si es tu estado de cuenta, súbelo a Nextcloud; "
                               "puede que el banco haya cambiado el formato o la contraseña.")

    def _estado_recibido(self, b, anio, mes, datos=None, nota=""):
        clave = f"{b.id}|{anio:04d}-{mes:02d}"
        etiqueta = etiqueta_mes(anio, mes)
        if self._presente(b, anio, mes):
            log.info("%s: llegó el correo del estado de %s, pero ya está en Nextcloud.", b.nombre, etiqueta)
            return
        if datos is not None:
            destino = b.nombre_para(anio, mes)
            if not self.simular:
                self.nc.asegurar_carpeta(b.carpeta)
                self.nc.subir(b.carpeta, destino, datos)
            self.avisos.enviar(f"✅ {b.nombre}: llegó por correo tu estado de {etiqueta} "
                               f"y lo guardé en Nextcloud como «{destino}».")
        else:
            self.avisos.enviar(f"📬 {b.nombre}: ya salió tu estado de cuenta de {etiqueta}. "
                               f"Descárgalo y súbelo a Nextcloud, en {b.carpeta}.{nota}")
        self.estado.d["avisos"][clave] = self.hoy().isoformat()

    def probar_correo(self, dias=60):
        desde = self.hoy() - timedelta(days=dias)
        if not self._por_buzon():
            print("Ningún banco activo tiene reglas de correo.")
        for buzon_id, bancos in self._por_buzon().items():
            buzon = self.cfg.buzones[buzon_id]
            print(f'\nBuzón "{buzon_id}" ({buzon.usuario}, carpeta {buzon.carpeta}):')
            with correo.Lector(buzon) as lec:
                for b in bancos:
                    uids = [u for u in lec.buscar(correo.termino_busqueda(b.correo.remitente), desde_fecha=desde)]
                    print(f"  {b.nombre}: {len(uids)} correo(s) de {b.correo.remitente} en los últimos {dias} días")
                    for uid in uids[-15:]:
                        msg = lec.traer(uid)
                        if msg is None:
                            continue
                        tipo, per, _, nota = self._decidir(b, msg)
                        if tipo == "guardar":
                            res = f"estado de {etiqueta_mes(*per)}: guardaría el PDF"
                        elif tipo == "avisar":
                            res = f"estado de {etiqueta_mes(*per)}: solo avisaría.{nota}"
                        elif tipo == "raro":
                            res = "trae un PDF que no reconocí: avisaría para que lo revises"
                        elif not correo.remitente_coincide(b.correo.remitente, msg):
                            res = f"otro remitente ({correo.remitente(msg)[:50]}): no cuenta"
                        else:
                            res = "no es estado de cuenta"
                        print(f"    {correo.fecha(msg, self.cfg.zona):%Y-%m-%d %H:%M}  "
                              f"«{correo.asunto(msg)[:60]}» -> {res}")

    # ------------------------------------------------------------------ carpetas
    def revisar_carpetas(self):
        for b in self.cfg.bancos:
            archivos = self.nc.listar(b.carpeta)
            if archivos is None:
                if self.simular:
                    log.info('[simulación] Crearía la carpeta "%s" para %s.', b.carpeta, b.nombre)
                else:
                    self.nc.asegurar_carpeta(b.carpeta)
                    log.info('Creé la carpeta "%s" para %s.', b.carpeta, b.nombre)
                continue
            self._renombrar(b, archivos)

    def _renombrar(self, b, archivos):
        ahora = time.time()
        for nombre in sorted(archivos):
            info = archivos.get(nombre)
            if info is None or not nombre.lower().endswith(".pdf") or b.patron_listo.match(nombre):
                continue
            clave = f"{b.carpeta}/{nombre}"
            if self.estado.d["ilegibles"].get(clave) == info["etag"]:
                continue  # ya avisamos que no se pudo leer y no ha cambiado
            if ahora - info["modificado"] < self.edad_min_seg:
                continue  # recién subido: lo tomamos en la siguiente vuelta

            datos = self.nc.descargar(b.carpeta, nombre)
            per = pdf.periodo(b, pdf.a_texto(pdf.abrir(datos, b.pdf_clave)))  # abre los que traen contraseña
            if not per:
                self.estado.d["ilegibles"][clave] = info["etag"]
                self.avisos.enviar(f"⚠️ {b.nombre}: no pude leer el periodo de «{nombre}» "
                                   f"en {b.carpeta}; lo dejé como está.")
                continue

            base = b.nombre_para(*per)[:-4]
            sha = hashlib.sha256(datos).digest()
            destino, n, duplicado_de = f"{base}.pdf", 2, None
            while destino in archivos:
                if hashlib.sha256(self.nc.descargar(b.carpeta, destino)).digest() == sha:
                    duplicado_de = destino
                    break
                destino, n = f"{base} ({n}).pdf", n + 1

            if duplicado_de:
                log.info('%s: "%s" es idéntico a "%s"; borro el duplicado.', b.nombre, nombre, duplicado_de)
                if not self.simular:
                    self.nc.borrar(b.carpeta, nombre)
                del archivos[nombre]
                continue
            log.info('%s: "%s" -> "%s"', b.nombre, nombre, destino)
            if not self.simular:
                self.nc.mover(b.carpeta, nombre, destino)
            archivos[destino] = archivos.pop(nombre)
            extra = " Ya había otro distinto de ese mes; revísalos." if destino != f"{base}.pdf" else ""
            self.avisos.enviar(f"✅ {b.nombre}: guardé «{destino}».{extra}")

    # ------------------------------------------------------------------ recordatorios
    def revisar_recordatorios(self):
        ahora = self.ahora()
        inicio, fin = self.cfg.horas_recordatorio
        if not inicio <= ahora.hour < fin:
            return
        hoy = ahora.date()
        anio, mes = mes_anterior(hoy.year, hoy.month)
        etiqueta = etiqueta_mes(anio, mes)
        for b in self.cfg.bancos:
            r = b.recordatorio
            if not r or hoy.day < r.desde_dia:
                continue
            clave = f"{b.id}|{anio:04d}-{mes:02d}"
            if self._presente(b, anio, mes):
                continue
            ultimo = self.estado.d["recordatorios"].get(clave)
            if ultimo and (hoy - date.fromisoformat(ultimo)).days < r.cada_dias:
                continue
            texto = f"⏰ {b.nombre}: todavía no está tu estado de {etiqueta} en Nextcloud ({b.carpeta})."
            if clave in self.estado.d["avisos"]:
                texto += " El banco ya avisó por correo que está listo."
            elif b.correo:
                texto += (" Tampoco he visto el correo del banco de este mes; si ya salió, "
                          "puede que haya cambiado el formato.")
            self.avisos.enviar(texto)
            self.estado.d["recordatorios"][clave] = hoy.isoformat()
