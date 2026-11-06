"""Acceso a Nextcloud por WebDAV.

Con un certificado válido (por ejemplo de Let's Encrypt) el certificado se verifica como lo haría un
navegador, con las autoridades de confianza del sistema. Con un certificado propio (autofirmado) se
fija por su huella SHA-256: solo se acepta ese certificado exacto.
"""
import hashlib
import socket
import ssl
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from urllib.parse import quote, unquote, urlsplit

import requests
from requests.adapters import HTTPAdapter

from .config import ErrorConfig

DAV = "{DAV:}"
PROPFIND = ('<?xml version="1.0"?><d:propfind xmlns:d="DAV:"><d:prop>'
            "<d:resourcetype/><d:getlastmodified/><d:getetag/></d:prop></d:propfind>")


def huella_servidor(url):
    """Huella SHA-256 del certificado que presenta el servidor (para NC_CERT_SHA256)."""
    p = urlsplit(url)
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with socket.create_connection((p.hostname, p.port or 443), timeout=15) as sock:
        with ctx.wrap_socket(sock, server_hostname=p.hostname) as tls:
            der = tls.getpeercert(binary_form=True)
    h = hashlib.sha256(der).hexdigest().upper()
    return ":".join(h[i:i + 2] for i in range(0, len(h), 2))


class AdaptadorConHuella(HTTPAdapter):
    """Acepta el certificado autofirmado solo si su huella SHA-256 coincide con la fijada."""

    def __init__(self, huella, **kwargs):
        self._huella = huella  # antes de super(): HTTPAdapter llama a init_poolmanager en __init__
        super().__init__(**kwargs)

    def init_poolmanager(self, *args, **kwargs):
        kwargs["assert_fingerprint"] = self._huella
        super().init_poolmanager(*args, **kwargs)


class Nextcloud:
    def __init__(self, url, usuario, clave, huella=""):
        if not url.startswith(("https://", "http://")):
            raise ErrorConfig(f"NC_URL debe empezar con https:// o http://: {url}")
        self.raiz = f"{url}/remote.php/dav/files/{quote(usuario, safe='')}/"
        self.con_huella = bool(huella) and url.startswith("https://")
        self.s = requests.Session()
        self.s.auth = (usuario, clave)
        self.s.headers["User-Agent"] = "estados-cuenta"
        if self.con_huella:
            # Certificado propio: la cadena de confianza no sirve; en su lugar se exige la huella exacta.
            # trust_env=False evita que REQUESTS_CA_BUNDLE reactive la verificación por CA.
            self.s.verify = False
            self.s.trust_env = False
            self.s.mount("https://", AdaptadorConHuella(huella))
        # Sin huella, requests verifica el certificado con las autoridades de confianza del sistema
        # (certifi), como un navegador: sirve para Let's Encrypt y cualquier certificado válido.

    def _pedir(self, metodo, url, **kwargs):
        """Una petición a Nextcloud; si el certificado no pasa, explica qué hacer."""
        try:
            return self.s.request(metodo, url, **kwargs)
        except requests.exceptions.SSLError as e:
            host = urlsplit(url).hostname
            if self.con_huella:
                raise RuntimeError(
                    f"El certificado de Nextcloud ({host}) no coincide con la huella fijada en nc_huella_sha256. "
                    "Si el certificado cambió (renovación, certificado nuevo), saca la huella nueva con "
                    "modo = huella; si ahora es un certificado válido (por ejemplo de Let's Encrypt), "
                    f"deja nc_huella_sha256 vacía. Detalle: {e}") from e
            raise RuntimeError(
                f"No confío en el certificado de Nextcloud ({host}): no lo firma una autoridad conocida. "
                "Si es un certificado propio (autofirmado), saca su huella con modo = huella y ponla en "
                f"nc_huella_sha256. Detalle: {e}") from e

    # ------------------------------------------------------------------ rutas
    def url_carpeta(self, carpeta):
        partes = [p for p in carpeta.strip("/").split("/") if p]
        return self.raiz + "".join(quote(p, safe="") + "/" for p in partes)

    def url_archivo(self, carpeta, nombre):
        return self.url_carpeta(carpeta) + quote(nombre, safe="")

    # ------------------------------------------------------------------ operaciones
    @staticmethod
    def _verificar(r, que, permitidos=()):
        if r.ok or r.status_code in permitidos:
            return r
        texto = r.text[:300]
        if r.status_code == 401:
            raise RuntimeError(f"Nextcloud rechazó usuario o contraseña al {que} (401). "
                               "Revisa NC_USER y NC_APP_PASSWORD.")
        if r.status_code == 400 and "trusted" in texto.lower():
            raise RuntimeError(f"Nextcloud no acepta la dirección {urlsplit(r.url).hostname} (untrusted domain). "
                               "Agrégala a trusted_domains.")
        raise RuntimeError(f"Error {r.status_code} al {que}: {texto}")

    def listar(self, carpeta):
        """{nombre: {etag, modificado}} de los archivos de la carpeta, o None si la carpeta no existe."""
        r = self._pedir("PROPFIND", self.url_carpeta(carpeta), data=PROPFIND, timeout=60,
                           headers={"Depth": "1", "Content-Type": "application/xml; charset=utf-8"})
        if r.status_code == 404:
            return None
        self._verificar(r, f'listar "{carpeta}"')
        archivos = {}
        for resp in ET.fromstring(r.content).iter(f"{DAV}response"):
            prop = None
            for ps in resp.iter(f"{DAV}propstat"):
                if " 200 " in (ps.findtext(f"{DAV}status") or ""):
                    prop = ps.find(f"{DAV}prop")
                    break
            if prop is None or prop.find(f"{DAV}resourcetype/{DAV}collection") is not None:
                continue  # la carpeta misma o subcarpetas
            nombre = unquote(urlsplit(resp.findtext(f"{DAV}href") or "").path.rstrip("/").rsplit("/", 1)[-1])
            modificado = prop.findtext(f"{DAV}getlastmodified")
            archivos[nombre] = {
                "etag": prop.findtext(f"{DAV}getetag"),
                "modificado": parsedate_to_datetime(modificado).timestamp() if modificado else 0.0,
            }
        return archivos

    def asegurar_carpeta(self, carpeta):
        ruta = ""
        for parte in [p for p in carpeta.strip("/").split("/") if p]:
            ruta = f"{ruta}/{parte}" if ruta else parte
            r = self._pedir("MKCOL", self.url_carpeta(ruta), timeout=60)
            self._verificar(r, f'crear la carpeta "{ruta}"', permitidos=(405,))  # 405 = ya existe

    def descargar(self, carpeta, nombre):
        r = self._pedir("GET", self.url_archivo(carpeta, nombre), timeout=120)
        return self._verificar(r, f'descargar "{nombre}"').content

    def subir(self, carpeta, nombre, datos):
        r = self._pedir("PUT", self.url_archivo(carpeta, nombre), data=datos, timeout=120,
                       headers={"If-None-Match": "*", "Content-Type": "application/pdf"})
        if r.status_code == 412:
            raise RuntimeError(f'Ya existe "{nombre}" en "{carpeta}"; no lo sobrescribo.')
        self._verificar(r, f'subir "{nombre}"')

    def mover(self, carpeta, origen, destino):
        r = self._pedir("MOVE", self.url_archivo(carpeta, origen), timeout=60,
                           headers={"Destination": self.url_archivo(carpeta, destino), "Overwrite": "F"})
        self._verificar(r, f'renombrar "{origen}"')

    def borrar(self, carpeta, nombre):
        self._verificar(self._pedir("DELETE", self.url_archivo(carpeta, nombre), timeout=60), f'borrar "{nombre}"')
