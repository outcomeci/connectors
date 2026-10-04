"""Shared Google authentication declarations; no network or Vault dependency."""

from ...auth import JwtBearer, OAuth2

TOKEN_URL = "https://oauth2.googleapis.com/token"


def authentication(scopes: tuple[str, ...]) -> tuple[OAuth2, JwtBearer]:
    return (
        OAuth2(
            token_url=TOKEN_URL,
            authorization_url="https://accounts.google.com/o/oauth2/v2/auth",
            authorization_parameters={"access_type": "offline", "prompt": "consent"},
            grant_types=("refresh_token",),
            scopes=scopes,
            client_auth="body",
            description="A Google OAuth client and refresh token with access to this service.",
        ),
        JwtBearer(
            subject_required=False,
            token_url=TOKEN_URL,
            scopes=scopes,
            description="A Google service account email (issuer) and RSA private key.",
        ),
    )
