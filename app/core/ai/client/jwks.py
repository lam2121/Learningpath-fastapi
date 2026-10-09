"""JWKS-based token verification for CareerPath Resource Server."""
 
from __future__ import annotations
 
import logging
from pathlib import Path
from typing import Any, Dict, Optional
 
import httpx
from jose import JWTError, jwk, jwt
 
from app.core.infra.config import app_config
 
logger = logging.getLogger(__name__)
 
_cached_public_key_pem: Optional[str] = None
_jwks_fetch_failed: bool = False
 
 
def get_auth_public_key_pem() -> Optional[str]:
    """Fetch and cache the RS256 public key from JWKS or local file fallback."""
    global _cached_public_key_pem, _jwks_fetch_failed
    if _cached_public_key_pem:
        return _cached_public_key_pem
 
    # 1. Try fetching from JWKS endpoint (if not already failed)
    if not _jwks_fetch_failed and app_config.AUTH_JWKS_URL:
        try:
            verify_ssl = not app_config.DISABLE_SSL_VERIFY
            resp = httpx.get(
                app_config.AUTH_JWKS_URL,
                timeout=app_config.AUTH_JWKS_TIMEOUT_SECONDS,
                verify=verify_ssl,
            )
            if resp.status_code == 200:
                jwks_data = resp.json()
                if "keys" in jwks_data and len(jwks_data["keys"]) > 0:
                    key = jwk.construct(jwks_data["keys"][0])
                    _cached_public_key_pem = key.to_pem().decode()
                    logger.info("Loaded RS256 public key from JWKS endpoint")
                    return _cached_public_key_pem
            else:
                # Endpoint returned 404/500 - don't retry on every single request
                _jwks_fetch_failed = True
                logger.debug(f"JWKS endpoint returned HTTP {resp.status_code}")
        except Exception as e:
            _jwks_fetch_failed = True
            logger.warning(f"Could not fetch JWKS from {app_config.AUTH_JWKS_URL}: {e}")
 
    # 2. Local file fallback
    try:
        key_path = Path(app_config.AUTH_PUBLIC_KEY_PATH)
        if not key_path.is_absolute():
            key_path = (app_config.PROJECT_ROOT / app_config.AUTH_PUBLIC_KEY_PATH).resolve()
        if key_path.exists():
            _cached_public_key_pem = key_path.read_text()
            logger.info(f"Loaded RS256 public key from file {key_path}")
            return _cached_public_key_pem
    except Exception as e:
        logger.warning(f"Could not load public key from file: {e}")
 
    return None
 
 
def decode_auth_token(token: str) -> Optional[Dict[str, Any]]:
    """Decode and verify token issued by Central Auth Service (HS256 or RS256).

    Strictly validates issuer and audience across both verification paths.
    """
    decode_kwargs: Dict[str, Any] = {}
    if app_config.JWT_ISSUER:
        decode_kwargs["issuer"] = app_config.JWT_ISSUER
    if app_config.JWT_AUDIENCE:
        decode_kwargs["audience"] = app_config.JWT_AUDIENCE

    def _validate_claims(claims: Dict[str, Any]) -> bool:
        if app_config.JWT_ISSUER and claims.get("iss") != app_config.JWT_ISSUER:
            return False
        if app_config.JWT_AUDIENCE and claims.get("aud") != app_config.JWT_AUDIENCE:
            return False
        return True

    # 1. Primary: Verify with shared SECRET_KEY / AUTH_SHARED_SECRET (HS256)
    secrets_to_try = []
    for s in [app_config.AUTH_SHARED_SECRET, app_config.SECRET_KEY]:
        if s and s not in secrets_to_try:
            secrets_to_try.append(s)

    for secret in secrets_to_try:
        try:
            payload = jwt.decode(
                token,
                secret,
                algorithms=["HS256"],
                issuer=app_config.JWT_ISSUER,
                audience=app_config.JWT_AUDIENCE,
            )
            if (
                payload.get("iss") != app_config.JWT_ISSUER
                or payload.get("aud") != app_config.JWT_AUDIENCE
            ):
                raise JWTError("Invalid issuer or audience")
            return payload
        except JWTError as e:
            logger.debug(f"HS256 verification failed with secret: {e}")

    # 2. Secondary: RS256 verification (if JWKS is used)
    pub_key_pem = get_auth_public_key_pem()
    if pub_key_pem:
        try:
            payload = jwt.decode(
                token,
                pub_key_pem,
                algorithms=["RS256"],
                issuer=app_config.JWT_ISSUER,
                audience=app_config.JWT_AUDIENCE,
            )
            if _validate_claims(payload):
                return payload
            logger.debug("RS256 token rejected due to mismatched issuer or audience claims")
        except JWTError as e:
            logger.debug(f"RS256 verification failed: {e}")

    return None
