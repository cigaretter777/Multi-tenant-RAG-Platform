from dataclasses import dataclass
import hashlib
import hmac
import secrets


@dataclass(frozen=True)
class ParsedApiKey:
    prefix: str
    secret: str


@dataclass(frozen=True)
class GeneratedApiKey:
    raw_key: str
    prefix: str
    digest: str


def _digest(prefix: str, secret: str, pepper: str) -> str:
    message = f"{prefix}:{secret}".encode()
    return hmac.new(pepper.encode(), message, hashlib.sha256).hexdigest()


def generate_api_key(pepper: str) -> GeneratedApiKey:
    prefix = secrets.token_hex(4)
    secret = secrets.token_urlsafe(32)
    raw_key = f"rag_{prefix}_{secret}"
    return GeneratedApiKey(raw_key, prefix, _digest(prefix, secret, pepper))


def parse_api_key(raw_key: str) -> ParsedApiKey:
    parts = raw_key.split("_", 2)
    if len(parts) != 3 or parts[0] != "rag" or len(parts[1]) != 8 or len(parts[2]) < 32:
        raise ValueError("invalid api key")
    int(parts[1], 16)
    return ParsedApiKey(prefix=parts[1], secret=parts[2])


def verify_api_key(raw_key: str, expected_digest: str, pepper: str) -> bool:
    try:
        parsed = parse_api_key(raw_key)
    except (TypeError, ValueError):
        return False
    return hmac.compare_digest(_digest(parsed.prefix, parsed.secret, pepper), expected_digest)
