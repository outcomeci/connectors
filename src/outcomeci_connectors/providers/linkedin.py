"""Bring-your-own-app LinkedIn OAuth; API operations will be added separately."""

from ..provider import OAuth2, Provider

# Available only when the user's app has the corresponding product approval:
# https://learn.microsoft.com/en-us/linkedin/marketing/increasing-access
SCOPES = (
    "r_member_postAnalytics",
    "r_organization_followers",
    "r_organization_social",
    "rw_organization_admin",
    "r_organization_social_feed",
    "w_member_social",
    "r_member_profileAnalytics",
    "w_organization_social",
    "r_basicprofile",
    "w_organization_social_feed",
    "w_member_social_feed",
    "r_1st_connections_size",
)

# Standard confidential-client web flow (not LinkedIn's native-PKCE endpoint):
# https://learn.microsoft.com/en-us/linkedin/shared/authentication/authorization-code-flow
# Unattended connections require approval for programmatic refresh tokens:
# https://learn.microsoft.com/en-us/linkedin/shared/authentication/programmatic-refresh-tokens
PROVIDER = Provider(
    name="linkedin",
    base_url="https://api.linkedin.com",
    auth=(
        OAuth2(
            authorization_url="https://www.linkedin.com/oauth/v2/authorization",
            token_url="https://www.linkedin.com/oauth/v2/accessToken",
            pkce=False,
            grant_types=("refresh_token",),
            optional_scopes=SCOPES,
            client_auth="body",
            rotates_refresh_token=False,
            description=(
                "Connect your own LinkedIn app with its approved scopes. "
                "Requires programmatic refresh-token access; reconnect when it expires."
            ),
        ),
    ),
    operations={},
)
