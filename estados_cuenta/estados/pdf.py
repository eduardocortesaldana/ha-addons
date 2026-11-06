"""Lectura del periodo dentro del PDF (y apertura de PDF con contraseña)."""
import os
import subprocess
import tempfile


def abrir(datos, clave=None):
    """Bytes del PDF listos para leer.
    - Sin contraseña: los mismos bytes.
    - Con contraseña: una copia descifrada con `clave` (o sin clave, si solo tiene permisos de dueño).
    - None si tiene contraseña y no se pudo abrir."""
    with tempfile.TemporaryDirectory() as d:
        entrada, salida = os.path.join(d, "entrada.pdf"), os.path.join(d, "salida.pdf")
        with open(entrada, "wb") as f:
            f.write(datos)
        if subprocess.run(["qpdf", "--is-encrypted", entrada], capture_output=True).returncode != 0:
            return datos  # no está cifrado (o qpdf no lo entiende: que pdftotext decida)
        args = ["qpdf", "--decrypt"] + (["--password-file=-"] if clave else []) + [entrada, salida]
        r = subprocess.run(args, input=(clave + "\n").encode() if clave else None,
                           capture_output=True, timeout=120)  # la clave va por stdin, no en la línea de comandos
        if r.returncode in (0, 3) and os.path.exists(salida):  # 3 = advertencias, pero sí escribió
            with open(salida, "rb") as f:
                return f.read()
        return None


def a_texto(datos):
    """Texto del PDF con pdftotext -layout. Cadena vacía si no se pudo (p. ej. PDF con contraseña)."""
    if not datos:
        return ""
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(datos)
        f.flush()
        r = subprocess.run(["pdftotext", "-layout", f.name, "-"],
                           capture_output=True, text=True, timeout=120)
    return r.stdout if r.returncode == 0 else ""


def periodo(banco, texto):
    """(anio, mes) según la regla pdf.periodo del banco, o None si el PDF no es de ese banco."""
    if not banco.pdf_periodo or not texto:
        return None
    if banco.pdf_contiene and banco.pdf_contiene.upper() not in texto.upper():
        return None
    m = banco.pdf_periodo.search(texto)
    if not m:
        return None
    anio, mes = int(m.group("anio")), int(m.group("mes"))
    return (anio, mes) if 1 <= mes <= 12 else None
