"""Lee bancos.yml (las fichas de cada banco) y los secretos del .env."""
import os
import re
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import yaml

MESES = ["", "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


class ErrorConfig(Exception):
    pass


@dataclass
class Buzon:
    id: str
    servidor: str
    puerto: int
    usuario: str
    clave: str
    carpeta: str


@dataclass
class ReglaCorreo:
    buzon: str
    remitente: str
    asunto: re.Pattern | None   # el asunto debe cumplirlo; puede traer (?P<anio>) y (?P<mes>)
    texto: str | None           # texto que debe aparecer en el asunto o en el cuerpo
    guardar_adjunto: bool       # si el correo trae el PDF, guardarlo en Nextcloud


@dataclass
class Recordatorio:
    desde_dia: int
    cada_dias: int


@dataclass
class Banco:
    id: str
    nombre: str
    carpeta: str
    archivo: str                # plantilla del nombre final, con {anio} y {mes}
    patron_listo: re.Pattern    # reconoce los archivos que ya tienen el nombre final
    pdf_periodo: re.Pattern | None
    pdf_contiene: str | None
    pdf_clave: str | None       # contraseña de los PDF del banco (de .env)
    pdf_clave_env: str | None   # nombre de la variable de .env, para avisar si falta
    correo: ReglaCorreo | None
    recordatorio: Recordatorio | None

    def nombre_para(self, anio, mes):
        return self.archivo.format(anio=f"{int(anio):04d}", mes=f"{int(mes):02d}")


@dataclass
class Avisos:
    tipo: str                   # home_assistant | telegram | registro
    url: str = ""
    servicio: str = ""
    token: str = ""
    chat_id: str = ""


@dataclass
class Config:
    zona: ZoneInfo
    revisar_cada_min: float
    horas_recordatorio: tuple
    nextcloud: dict
    avisos: Avisos
    buzones: dict
    bancos: list


def etiqueta_mes(anio, mes):
    return f"{MESES[int(mes)]} {anio}"


def mes_anterior(anio, mes):
    return (anio - 1, 12) if mes == 1 else (anio, mes - 1)


def patron_de_plantilla(plantilla):
    """'{anio}-{mes} BBVA.pdf' -> regex que reconoce '2026-10 BBVA.pdf' y '2026-10 BBVA (2).pdf'."""
    if not plantilla.lower().endswith(".pdf"):
        raise ErrorConfig(f'"archivo" debe terminar en .pdf: {plantilla}')
    for campo in ("{anio}", "{mes}"):
        if plantilla.count(campo) != 1:
            raise ErrorConfig(f'"archivo" debe llevar {campo} exactamente una vez: {plantilla}')
    rx = ""
    for parte in re.split(r"(\{anio\}|\{mes\})", plantilla[:-4]):
        if parte == "{anio}":
            rx += r"(?P<anio>\d{4})"
        elif parte == "{mes}":
            rx += r"(?P<mes>\d{2})"
        else:
            rx += re.escape(parte)
    return re.compile("^" + rx + r"(?: \(\d+\))?\.pdf$", re.IGNORECASE)


def _regex(texto, donde, requiere_periodo=False):
    if not texto:
        return None
    try:
        rx = re.compile(texto, re.IGNORECASE)
    except re.error as e:
        raise ErrorConfig(f"Expresión inválida en {donde}: {e}") from e
    grupos = set(rx.groupindex)
    if requiere_periodo and not {"anio", "mes"} <= grupos:
        raise ErrorConfig(f"{donde} debe tener los grupos (?P<anio>...) y (?P<mes>...)")
    if grupos & {"anio", "mes"} and not {"anio", "mes"} <= grupos:
        raise ErrorConfig(f"{donde}: si usas (?P<anio>) o (?P<mes>), pon los dos")
    return rx


def _env(nombre, requerido=True):
    valor = os.environ.get(nombre, "").strip()
    if requerido and not valor:
        raise ErrorConfig(f"Falta {nombre} en .env")
    return valor


def cargar(ruta=None):
    ruta = ruta or os.environ.get("CONFIG", "/app/bancos.yml")
    try:
        with open(ruta, encoding="utf-8") as f:
            datos = yaml.safe_load(f) or {}
    except FileNotFoundError as e:
        raise ErrorConfig(f"No encontré {ruta}") from e
    except yaml.YAMLError as e:
        raise ErrorConfig(f"{ruta} tiene un error de formato: {e}") from e

    zona = ZoneInfo(datos.get("zona_horaria", "America/Mexico_City"))
    horas = datos.get("recordatorios_entre", [10, 21])
    nextcloud = {
        "url": _env("NC_URL").rstrip("/"),
        "usuario": _env("NC_USER"),
        "clave": _env("NC_APP_PASSWORD"),
        "huella": _env("NC_CERT_SHA256", requerido=False).replace(":", "").lower(),
    }

    # Avisos
    a = datos.get("avisos") or {}
    tipo = a.get("tipo", "home_assistant")
    if tipo == "home_assistant":
        avisos = Avisos(tipo, url=str(a.get("url", "")).rstrip("/"),
                        servicio=a.get("servicio", "notify.telegram"), token=_env("HA_TOKEN", False))
        if not avisos.url or "." not in avisos.servicio:
            raise ErrorConfig('avisos: falta "url" o "servicio" (ej. notify.telegram)')
    elif tipo == "telegram":
        avisos = Avisos(tipo, url=a.get("url", "https://api.telegram.org").rstrip("/"),
                        token=_env("TELEGRAM_TOKEN", False), chat_id=_env("TELEGRAM_CHAT_ID", False))
    elif tipo == "registro":
        avisos = Avisos(tipo)
    else:
        raise ErrorConfig(f"avisos.tipo desconocido: {tipo} (usa home_assistant o telegram)")

    # Bancos activos
    bancos = []
    buzones_usados = set()
    for id_, b in (datos.get("bancos") or {}).items():
        b = b or {}
        if not b.get("activo", True):
            continue
        donde = f"bancos.{id_}"
        for campo in ("nombre", "carpeta", "archivo"):
            if not b.get(campo):
                raise ErrorConfig(f'{donde}: falta "{campo}"')
        pdf = b.get("pdf") or {}
        regla = None
        c = b.get("correo")
        if c:
            if not c.get("buzon") or not c.get("remitente"):
                raise ErrorConfig(f'{donde}.correo: faltan "buzon" o "remitente"')
            regla = ReglaCorreo(buzon=c["buzon"], remitente=str(c["remitente"]).strip(),
                                asunto=_regex(c.get("asunto"), f"{donde}.correo.asunto"),
                                texto=(c.get("texto") or None),
                                guardar_adjunto=bool(c.get("guardar_adjunto", False)))
            buzones_usados.add(regla.buzon)
        r = b.get("recordatorio")
        bancos.append(Banco(
            id=id_, nombre=b["nombre"], carpeta=str(b["carpeta"]).strip("/"), archivo=b["archivo"],
            patron_listo=patron_de_plantilla(b["archivo"]),
            pdf_periodo=_regex(pdf.get("periodo"), f"{donde}.pdf.periodo", requiere_periodo=True),
            pdf_contiene=pdf.get("contiene") or None,
            pdf_clave=(_env(pdf["clave_env"], requerido=False) or None) if pdf.get("clave_env") else None,
            pdf_clave_env=pdf.get("clave_env") or None,
            correo=regla,
            recordatorio=Recordatorio(int(r.get("desde_dia", 5)), max(1, int(r.get("cada_dias", 2)))) if r else None,
        ))

    # Buzones: solo exigimos la contraseña de los que usa algún banco activo
    buzones = {}
    for id_, z in (datos.get("buzones") or {}).items():
        if id_ not in buzones_usados:
            continue
        for campo in ("servidor", "usuario", "clave_env"):
            if not z.get(campo):
                raise ErrorConfig(f'buzones.{id_}: falta "{campo}"')
        buzones[id_] = Buzon(id=id_, servidor=z["servidor"], puerto=int(z.get("puerto", 993)),
                             usuario=z["usuario"], clave=_env(z["clave_env"]),
                             carpeta=z.get("carpeta", "INBOX"))
    for faltante in buzones_usados - set(buzones):
        raise ErrorConfig(f'Un banco usa el buzón "{faltante}", pero no está en "buzones"')

    return Config(zona=zona, revisar_cada_min=float(datos.get("revisar_cada_min", 10)),
                  horas_recordatorio=(int(horas[0]), int(horas[1])), nextcloud=nextcloud,
                  avisos=avisos, buzones=buzones, bancos=bancos)
