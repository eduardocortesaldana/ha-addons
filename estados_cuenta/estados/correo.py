"""Lectura de correo por IMAP, siempre en solo lectura: no marca nada como leído ni mueve correos."""
import email
import email.policy
import html
import imaplib
import re
import ssl
from email.utils import parseaddr, parsedate_to_datetime

from .config import mes_anterior

_MESES_IMAP = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _cadena_imap(s):
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


class Lector:
    """Uso: with Lector(buzon) as lec: lec.buscar(...)"""

    def __init__(self, buzon):
        self.buzon = buzon
        self.m = None
        self.uidvalidity = 0
        self.uidnext = 0

    def __enter__(self):
        b = self.buzon
        self.m = imaplib.IMAP4_SSL(b.servidor, b.puerto, ssl_context=ssl.create_default_context(), timeout=60)
        try:
            self.m.login(b.usuario, b.clave)
        except imaplib.IMAP4.error as e:
            raise RuntimeError(f'El buzón "{b.id}" ({b.usuario}) rechazó la contraseña: {e}') from e
        typ, _ = self.m.select(_cadena_imap(b.carpeta), readonly=True)
        if typ != "OK":
            raise RuntimeError(f'No pude abrir la carpeta "{b.carpeta}" del buzón "{b.id}"')
        self.uidvalidity = int((self.m.untagged_responses.get("UIDVALIDITY") or [b"0"])[0])
        self.uidnext = int((self.m.untagged_responses.get("UIDNEXT") or [b"0"])[0])
        return self

    def __exit__(self, *exc):
        try:
            self.m.logout()
        except Exception:  # noqa: BLE001
            pass

    def ultimo_uid(self):
        if self.uidnext:
            return self.uidnext - 1
        typ, data = self.m.uid("SEARCH", "ALL")
        uids = [int(x) for x in (data[0] or b"").split()]
        return max(uids, default=0)

    def buscar(self, remitente, desde_uid=None, desde_fecha=None):
        crit = []
        if desde_uid:
            crit += ["UID", f"{desde_uid}:*"]
        if desde_fecha:
            crit += ["SINCE", f"{desde_fecha.day:02d}-{_MESES_IMAP[desde_fecha.month - 1]}-{desde_fecha.year}"]
        crit += ["FROM", _cadena_imap(remitente)]
        typ, data = self.m.uid("SEARCH", *crit)
        if typ != "OK":
            raise RuntimeError(f"La búsqueda en el buzón falló: {data}")
        uids = [int(x) for x in (data[0] or b"").split()]
        # "UID n:*" siempre devuelve al menos el último correo aunque sea anterior a n
        return sorted(u for u in uids if not desde_uid or u >= desde_uid)

    def traer(self, uid):
        typ, data = self.m.uid("FETCH", str(uid), "(BODY.PEEK[])")  # PEEK: no lo marca como leído
        for item in data or []:
            if isinstance(item, tuple):
                return email.message_from_bytes(item[1], policy=email.policy.default)
        return None


# ---------------------------------------------------------------------- lectura de un correo

def remitente(msg):
    return str(msg.get("From") or "")


def remitente_coincide(regla, msg):
    """'clientes@bbva.mx' = esa dirección exacta. 'bbva.mx' o '@bbva.mx' = cualquier dirección de ese dominio
    (o sus subdominios), pero no 'algo@bbva.mx.otrodominio.com'."""
    direccion = parseaddr(remitente(msg))[1].lower()
    regla = regla.strip().lower()
    if "@" in regla.lstrip("@"):
        return direccion == regla
    dominio = regla.lstrip("@")
    return direccion.endswith("@" + dominio) or direccion.endswith("." + dominio)


def termino_busqueda(regla):
    """Lo que se le pide al servidor IMAP en FROM (búsqueda amplia; el filtro fino es remitente_coincide)."""
    return regla.strip().lstrip("@")


def asunto(msg):
    return str(msg.get("Subject") or "")


def texto(msg):
    """Texto de todas las versiones del cuerpo (texto y HTML): muchos bancos ponen lo importante solo en el HTML."""
    trozos = []
    for parte in msg.walk():
        if parte.is_multipart() or parte.get_content_disposition() == "attachment":
            continue
        tipo = parte.get_content_type()
        if tipo not in ("text/plain", "text/html"):
            continue
        try:
            contenido = parte.get_content()
        except (LookupError, KeyError):  # codificación rara
            contenido = (parte.get_payload(decode=True) or b"").decode("latin-1", "replace")
        if tipo == "text/html":
            contenido = re.sub(r"(?is)<(style|script)\b.*?</\1\s*>", " ", contenido)
            contenido = html.unescape(re.sub(r"<[^>]+>", " ", contenido))
        trozos.append(contenido)
    return re.sub(r"\s+", " ", " ".join(trozos))


def fecha(msg, zona):
    return parsedate_to_datetime(msg["Date"]).astimezone(zona)


def pdfs(msg):
    adjuntos = []
    for parte in msg.iter_attachments():
        nombre = parte.get_filename() or ""
        if parte.get_content_type() == "application/pdf" or nombre.lower().endswith(".pdf"):
            datos = parte.get_content()
            if isinstance(datos, bytes) and datos:
                adjuntos.append((nombre or "estado.pdf", datos))
    return adjuntos


def coincide(banco, msg, zona):
    """(anio, mes) si el correo es el aviso de estado de cuenta de este banco; si no, None."""
    regla = banco.correo
    if not regla or not remitente_coincide(regla.remitente, msg):
        return None
    asu = asunto(msg)
    m = None
    if regla.asunto:
        m = regla.asunto.search(asu)
        if not m:
            return None
    if regla.texto and regla.texto.lower() not in f"{asu} {texto(msg)}".lower():
        return None
    if m and m.groupdict().get("anio") and m.groupdict().get("mes"):
        anio, mes = int(m.group("anio")), int(m.group("mes"))
        return (anio, mes) if 1 <= mes <= 12 else None
    # Sin mes en el asunto: es el del mes anterior al correo (el corte es a fin de mes)
    f = fecha(msg, zona)
    return mes_anterior(f.year, f.month)
