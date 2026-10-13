import hashlib
import hmac
import ipaddress
import secrets
import socket
from urllib.parse import urlparse

PREFIJO_KEY = "ntf_"


def generar_api_key() -> str:
    return PREFIJO_KEY + secrets.token_urlsafe(32)


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def prefijo_visible(key: str) -> str:
    # lo único de la key que se puede mostrar o loguear
    return key[:8]


def generar_secreto() -> str:
    return secrets.token_hex(32)


def firmar(cuerpo: bytes, secreto: str) -> str:
    return hmac.new(secreto.encode(), cuerpo, hashlib.sha256).hexdigest()


class UrlInvalida(ValueError):
    pass


def validar_url_callback(url: str) -> None:
    """Acepta solo https hacia un host público. Resuelve el host para mirar las IPs reales."""
    partes = urlparse(url)
    if partes.scheme != "https":
        raise UrlInvalida("La URL debe ser https")
    host = partes.hostname
    if not host:
        raise UrlInvalida("La URL no tiene host")
    if host.lower() == "localhost":
        raise UrlInvalida("No se permite localhost")
    try:
        infos = socket.getaddrinfo(host, partes.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise UrlInvalida("No se pudo resolver el host") from None
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if not ip.is_global:
            raise UrlInvalida("El host resuelve a una IP privada o local")
