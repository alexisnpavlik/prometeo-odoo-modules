"""Verificación de números: cada número de una respuesta tiene que salir de lo que se consultó."""
import re

IGNORE_RES = [
    re.compile(r"\b\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2})?)?\b"),       # 2026-11-04 10:00:00
    re.compile(r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b"),                         # 4/11, 4/11/2026
    re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b"),                             # 10:30
    re.compile(r"[A-Za-z][\w/.-]*\d[\w/.-]*"),                               # WH/IN/00012, S0042, gemini-3.8
]
NUMBER_RE = re.compile(r"(?<![\w.,])-?\d+(?:[.,]\d+)*")
SMALL_INT = 10
TOLERANCE = 0.005  # 0,5 %: cubre redondeos al mostrar


def _candidates(token):
    """Interpretaciones posibles de un número escrito (1.532,50 · 1,532.50 · 1.532 · 12,5)."""
    token = token.lstrip("-")
    if "." in token and "," in token:
        dec = "." if token.rfind(".") > token.rfind(",") else ","
        other = "," if dec == "." else "."
        return {float(token.replace(other, "").replace(dec, "."))}
    for sep in (".", ","):
        if sep in token:
            parts = token.split(sep)
            if len(parts) > 2:
                return {float("".join(parts))}
            if len(parts[1]) == 3:
                return {float("".join(parts)), float(parts[0] + "." + parts[1])}
            return {float(parts[0] + "." + parts[1])}
    return {float(token)}


def _extract(text):
    """Lista de (texto del número, candidatos), sin fechas, horas, códigos, años ni enteros chicos."""
    clean = text or ""
    for regex in IGNORE_RES:
        clean = regex.sub(" ", clean)
    found = []
    for match in NUMBER_RE.finditer(clean):
        token = match.group(0)
        cands = _candidates(token)
        plain = token.lstrip("-")
        if plain.isdigit() and (int(plain) <= SMALL_INT or (len(plain) == 4 and 1900 <= int(plain) <= 2100)):
            continue
        found.append((token, cands))
    return found


def numbers_in_text(text):
    """Candidatos de cada número relevante del texto."""
    return [cands for _token, cands in _extract(text)]


def source_numbers(value, out=None):
    """Todos los números de un resultado (JSON ya parseado), incluidos los que aparecen dentro de textos."""
    out = set() if out is None else out
    if isinstance(value, bool) or value is None:
        return out
    if isinstance(value, (int, float)):
        out.add(float(value))
    elif isinstance(value, str):
        for match in NUMBER_RE.finditer(value):
            out |= _candidates(match.group(0))
    elif isinstance(value, dict):
        for item in value.values():
            source_numbers(item, out)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            source_numbers(item, out)
    return out


def _matches(cands, sources):
    """Un número está respaldado si coincide (con redondeo) con alguna fuente, o es su porcentaje."""
    for c in cands:
        for s in sources:
            tol = max(0.005, abs(s) * TOLERANCE)
            if abs(c - s) <= tol or abs(c - s * 100) <= max(0.05, abs(s * 100) * TOLERANCE):
                return True
    return False


def unsupported(text, sources):
    """Números del texto que no salen de ninguna fuente (como están escritos)."""
    return [token for token, cands in _extract(text) if not _matches(cands, sources)]
