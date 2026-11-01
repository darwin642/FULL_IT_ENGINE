"""TLS configuration for the CartmanClient TCP listener.

The private key is stored outside app/static and is never returned by an API.
The certificate fingerprint can be safely compared with a trusted local copy.
"""
import hashlib
import ipaddress
import os
import socket
import ssl
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


_TLS_DIR = Path(__file__).resolve().parent / "private_agent_tls"
_KEY_PATH = _TLS_DIR / "server-key.pem"
_CERT_PATH = _TLS_DIR / "server-cert.pem"


def _set_private_permissions(path, mode):
    if os.name != "nt":
        path.chmod(mode)


def _create_certificate():
    _TLS_DIR.mkdir(parents=True, exist_ok=True)
    _set_private_permissions(_TLS_DIR, 0o700)

    private_key = ec.generate_private_key(ec.SECP256R1())
    now = datetime.utcnow()
    subject = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "Cartman Agent Listener"),
    ])

    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=365))
        .add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName("localhost"),
                x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                x509.IPAddress(ipaddress.ip_address("::1")),
            ]),
            critical=False,
        )
        .add_extension(
            x509.BasicConstraints(ca=False, path_length=None),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(private_key, hashes.SHA256())
    )

    key_temp = _TLS_DIR / "server-key.pem.tmp"
    cert_temp = _TLS_DIR / "server-cert.pem.tmp"

    try:
        key_temp.write_bytes(
            private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
        cert_temp.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
        _set_private_permissions(key_temp, 0o600)
        _set_private_permissions(cert_temp, 0o644)
        os.replace(key_temp, _KEY_PATH)
        os.replace(cert_temp, _CERT_PATH)
    finally:
        for temp_path in (key_temp, cert_temp):
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass


def create_agent_tls_server_context():
    """Return a TLS 1.2+ context and its lowercase SHA-256 cert fingerprint."""
    _TLS_DIR.mkdir(parents=True, exist_ok=True)
    _set_private_permissions(_TLS_DIR, 0o700)

    key_exists = _KEY_PATH.exists()
    cert_exists = _CERT_PATH.exists()

    if key_exists != cert_exists:
        raise RuntimeError(
            "Only one TLS certificate file exists. Inspect the files in "
            "app/private_agent_tls before repairing them; automatic replacement "
            "could invalidate existing client pins."
        )

    if not key_exists:
        _create_certificate()

    if _KEY_PATH.is_symlink() or _CERT_PATH.is_symlink():
        raise RuntimeError("TLS certificate files must not be symbolic links.")

    _set_private_permissions(_KEY_PATH, 0o600)
    _set_private_permissions(_CERT_PATH, 0o644)

    certificate = x509.load_pem_x509_certificate(_CERT_PATH.read_bytes())
    now = datetime.now(timezone.utc)
    if now < certificate.not_valid_before_utc or now >= certificate.not_valid_after_utc:
        raise RuntimeError(
            "The stored CartmanClient TLS certificate is outside its validity "
            "period. Certificate rotation must be deliberate because clients pin it."
        )

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.options |= getattr(ssl, "OP_NO_COMPRESSION", 0)
    context.load_cert_chain(certfile=str(_CERT_PATH), keyfile=str(_KEY_PATH))

    fingerprint = hashlib.sha256(
        certificate.public_bytes(serialization.Encoding.DER)
    ).hexdigest()

    return context, fingerprint
