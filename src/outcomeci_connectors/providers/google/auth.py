"""Shared Google authentication declarations; no network or Vault dependency."""

from ...auth import JwtBearer, OAuth2, Token

TOKEN_URL = "https://oauth2.googleapis.com/token"


def authentication(
    scopes: tuple[str, ...], *, optional_scopes: tuple[str, ...] = ()
) -> tuple[OAuth2, JwtBearer, Token]:
    return (
        OAuth2(
            token_url=TOKEN_URL,
            authorization_url="https://accounts.google.com/o/oauth2/v2/auth",
            authorization_parameters={"access_type": "offline", "prompt": "consent"},
            grant_types=("refresh_token",),
            scopes=scopes,
            optional_scopes=optional_scopes,
            client_auth="body",
            description="A Google OAuth client and refresh token with access to this service.",
        ),
        JwtBearer(
            subject_required=False,
            token_url=TOKEN_URL,
            scopes=(*scopes, *optional_scopes),
            description="A Google service account email (issuer) and RSA private key.",
        ),
        # Google APIs accept OAuth access tokens. Managed connections provide
        # a short-lived bearer lease; refresh credentials remain in the API.
        # https://developers.google.com/identity/protocols/oauth2
        Token(description="A Google access token, including a managed connection lease."),
    )
