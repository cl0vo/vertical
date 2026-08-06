from __future__ import annotations

import hashlib
import secrets
import time
import urllib.parse
from typing import Any

from .oauth_local import OAuthCallback
from .publishing import Platform, _json_request
from .secure_store import update_platform_credentials


def connect_tiktok(client_key: str, client_secret: str) -> dict[str, Any]:
    client_key = client_key.strip()
    client_secret = client_secret.strip()
    if not client_key or not client_secret:
        raise RuntimeError("Укажи Client key и Client secret TikTok Developer App.")

    callback = OAuthCallback(host="127.0.0.1", port=0, path="/callback/")
    state = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(72)[:128]
    challenge = hashlib.sha256(verifier.encode("utf-8")).hexdigest()

    def build_url(redirect_uri: str) -> str:
        query = urllib.parse.urlencode(
            {
                "client_key": client_key,
                "response_type": "code",
                "scope": "user.info.basic,video.publish",
                "redirect_uri": redirect_uri,
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
        return "https://www.tiktok.com/v2/auth/authorize/?" + query

    params = callback.authorize(build_url)
    if params.get("state") != state:
        raise RuntimeError("TikTok вернул неверный OAuth state.")
    code = params.get("code") or ""
    if not code:
        raise RuntimeError("TikTok не вернул код авторизации.")

    token = _json_request(
        "https://open.tiktokapis.com/v2/oauth/token/",
        method="POST",
        form={
            "client_key": client_key,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": callback.redirect_uri,
            "code_verifier": verifier,
        },
    )
    if token.get("error") and not token.get("access_token"):
        raise RuntimeError(
            "TikTok OAuth: "
            + str(token.get("error_description") or token.get("error"))
        )
    access_token = str(token.get("access_token") or "")
    if not access_token:
        raise RuntimeError(f"TikTok не выдал access token: {token}")

    display_name = "TikTok"
    try:
        user = _json_request(
            "https://open.tiktokapis.com/v2/user/info/?fields=open_id,display_name,avatar_url",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        display_name = str(((user.get("data") or {}).get("user") or {}).get("display_name") or display_name)
    except Exception:
        pass

    result = {
        "access_token": access_token,
        "refresh_token": str(token.get("refresh_token") or ""),
        "client_key": client_key,
        "client_secret": client_secret,
        "expires_at": time.time() + int(token.get("expires_in") or 86400),
        "refresh_expires_at": time.time() + int(token.get("refresh_expires_in") or 365 * 86400),
        "open_id": str(token.get("open_id") or ""),
        "display_name": display_name,
        "privacy_level": "PUBLIC_TO_EVERYONE",
    }
    update_platform_credentials(Platform.TIKTOK.value, result)
    return result


def connect_instagram(
    app_id: str,
    app_secret: str,
    *,
    api_version: str = "v25.0",
    port: int = 8788,
) -> dict[str, Any]:
    app_id = app_id.strip()
    app_secret = app_secret.strip()
    if not app_id or not app_secret:
        raise RuntimeError("Укажи Instagram App ID и App Secret в Meta Developer.")

    callback = OAuthCallback(host="127.0.0.1", port=port, path="/callback/")
    state = secrets.token_urlsafe(24)

    def build_url(redirect_uri: str) -> str:
        query = urllib.parse.urlencode(
            {
                "client_id": app_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": "instagram_business_basic,instagram_business_content_publish",
                "state": state,
                "force_reauth": "true",
            }
        )
        return "https://www.instagram.com/oauth/authorize?" + query

    params = callback.authorize(build_url)
    if params.get("state") and params.get("state") != state:
        raise RuntimeError("Instagram вернул неверный OAuth state.")
    code = (params.get("code") or "").replace("#_", "")
    if not code:
        raise RuntimeError("Instagram не вернул код авторизации.")

    token = _json_request(
        "https://api.instagram.com/oauth/access_token",
        method="POST",
        form={
            "client_id": app_id,
            "client_secret": app_secret,
            "grant_type": "authorization_code",
            "redirect_uri": callback.redirect_uri,
            "code": code,
        },
    )
    short_token = str(token.get("access_token") or "")
    user_id = str(token.get("user_id") or "")
    if not short_token:
        raise RuntimeError(f"Instagram не выдал access token: {token}")

    access_token = short_token
    expires_in = int(token.get("expires_in") or 3600)
    try:
        long_lived = _json_request(
            "https://graph.instagram.com/access_token?"
            + urllib.parse.urlencode(
                {
                    "grant_type": "ig_exchange_token",
                    "client_secret": app_secret,
                    "access_token": short_token,
                }
            )
        )
        if long_lived.get("access_token"):
            access_token = str(long_lived["access_token"])
            expires_in = int(long_lived.get("expires_in") or 60 * 86400)
    except Exception:
        pass

    username = "Instagram"
    try:
        profile = _json_request(
            f"https://graph.instagram.com/{api_version}/me?"
            + urllib.parse.urlencode(
                {
                    "fields": "id,user_id,username,account_type",
                    "access_token": access_token,
                }
            )
        )
        user_id = str(profile.get("user_id") or profile.get("id") or user_id)
        username = str(profile.get("username") or username)
    except Exception:
        pass

    if not user_id:
        raise RuntimeError("Instagram подключён, но не удалось определить IG User ID.")

    result = {
        "access_token": access_token,
        "ig_user_id": user_id,
        "app_id": app_id,
        "app_secret": app_secret,
        "api_version": api_version,
        "graph_host": "graph.instagram.com",
        "expires_at": time.time() + expires_in,
        "username": username,
        "redirect_uri": callback.redirect_uri,
    }
    update_platform_credentials(Platform.INSTAGRAM.value, result)
    return result
