"""Versioned Meta Graph calls for the Social Growth Autopilot.

The Graph version comes from META_GRAPH_API_VERSION. Every call goes through an
httpx-shaped client that the caller supplies, so tests pass a scripted fake and
the services decide whether a live client may exist at all. Nothing in this
module checks grants, scopes, or the demonstration scope.

Contracts used (verified 2026-10-28 against Meta documentation):
- Instagram publishing: POST /{ig-id}/media, GET /{container}?fields=status_code,
  POST /{ig-id}/media_publish, GET /{ig-id}/content_publishing_limit.
- Facebook Page Reels: POST /{page-id}/video_reels (start, finish) and the bytes
  to rupload.facebook.com/video-upload/{version}/{video-id} with an OAuth header.
- Insights: Instagram `views` replaced `impressions`; Facebook `page_media_view`
  and `post_media_view` replaced the impression metrics on 2025-11-15.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.config import get_settings

GRAPH_HOST = "https://graph.facebook.com"
UPLOAD_HOST = "https://rupload.facebook.com"
DEFAULT_VERSION = "v26.0"

AUTH_CODES = {102, 190}
PERMISSION_CODES = {3, 10}
RATE_LIMIT_CODES = {4, 17, 32, 341, 613}
TRANSIENT_CODES = {1, 2}
IG_PUBLISH_LIMIT_SUBCODE = 2207042

INSTAGRAM_MEDIA_METRICS = {
    "FEED": ("views", "reach", "likes", "comments", "saved", "shares", "total_interactions", "follows", "profile_visits"),
    "REELS": ("views", "reach", "likes", "comments", "saved", "shares", "total_interactions", "ig_reels_avg_watch_time"),
}
INSTAGRAM_ACCOUNT_METRICS = ("views", "reach", "accounts_engaged", "total_interactions", "profile_links_taps")
INSTAGRAM_FOLLOWER_METRIC = "follower_count"
FACEBOOK_PAGE_METRICS = (
    "page_media_view",
    "page_total_media_view_unique",
    "page_post_engagements",
    "page_daily_follows_unique",
    "page_views_total",
    "page_total_actions",
)
FACEBOOK_POST_METRICS = ("post_media_view", "post_total_media_view_unique", "post_clicks")
FACEBOOK_VIDEO_METRICS = ("post_video_views",)


def graph_version() -> str:
    raw = (get_settings().meta_graph_api_version or DEFAULT_VERSION).strip()
    if not raw:
        return DEFAULT_VERSION
    return raw if raw.startswith("v") else f"v{raw}"


def appsecret_proof(access_token: str, app_secret: str) -> str:
    return hmac.new(app_secret.encode(), access_token.encode(), hashlib.sha256).hexdigest()


@dataclass
class GraphResult:
    ok: bool
    status_code: int
    data: dict = field(default_factory=dict)
    error_code: int | None = None
    error_subcode: int | None = None
    error_message: str = ""
    failure_class: str = ""
    retry_after_seconds: int | None = None

    @property
    def unknown_effect(self) -> bool:
        """A write whose outcome cannot be known from this response."""
        return self.failure_class in {"NETWORK", "TRANSIENT"}


def classify(status_code: int, code: int | None, subcode: int | None) -> str:
    if code in AUTH_CODES or status_code == 401:
        return "AUTH"
    if code == 9 and subcode == IG_PUBLISH_LIMIT_SUBCODE:
        return "PUBLISH_LIMIT"
    if code in RATE_LIMIT_CODES or status_code == 429 or (code is not None and 80000 <= code <= 80014):
        return "RATE_LIMIT"
    if code in PERMISSION_CODES or (code is not None and 200 <= code <= 299) or status_code == 403:
        return "PERMISSION"
    if code in TRANSIENT_CODES or status_code >= 500:
        return "TRANSIENT"
    if status_code >= 400:
        return "INVALID"
    return ""


def _retry_after(headers: Any) -> int | None:
    if headers is None:
        return None
    raw = ""
    getter = getattr(headers, "get", None)
    if callable(getter):
        raw = str(getter("x-business-use-case-usage") or getter("X-Business-Use-Case-Usage") or "")
        retry = getter("retry-after") or getter("Retry-After")
        if retry and str(retry).isdigit():
            return int(retry)
    if not raw:
        return None
    try:
        usage = json.loads(raw)
    except ValueError:
        return None
    minutes = 0
    if isinstance(usage, dict):
        for entries in usage.values():
            for entry in entries if isinstance(entries, list) else []:
                if isinstance(entry, dict):
                    try:
                        minutes = max(minutes, int(entry.get("estimated_time_to_regain_access") or 0))
                    except (TypeError, ValueError):
                        continue
    return minutes * 60 if minutes > 0 else None


def _result(response: Any) -> GraphResult:
    status_code = int(getattr(response, "status_code", 0) or 0)
    try:
        payload = response.json() if getattr(response, "content", b"") or hasattr(response, "json") else {}
    except (ValueError, TypeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {"data": payload}
    error = payload.get("error") if isinstance(payload.get("error"), dict) else None
    if status_code < 400 and error is None:
        return GraphResult(ok=True, status_code=status_code, data=payload)
    code = subcode = None
    message = ""
    if error is not None:
        try:
            code = int(error.get("code")) if error.get("code") is not None else None
        except (TypeError, ValueError):
            code = None
        try:
            subcode = int(error.get("error_subcode")) if error.get("error_subcode") is not None else None
        except (TypeError, ValueError):
            subcode = None
        message = str(error.get("error_user_msg") or error.get("message") or "").replace("\n", " ").strip()[:300]
    return GraphResult(
        ok=False,
        status_code=status_code,
        data=payload,
        error_code=code,
        error_subcode=subcode,
        error_message=message or f"Meta returned HTTP {status_code}.",
        failure_class=classify(status_code, code, subcode),
        retry_after_seconds=_retry_after(getattr(response, "headers", None)),
    )


class MetaGrowthClient:
    """Graph calls with one access token. `client` is httpx-shaped."""

    def __init__(self, *, client: Any, access_token: str, app_secret: str = "", version: str = "") -> None:
        self._client = client
        self._token = access_token
        self._proof = appsecret_proof(access_token, app_secret) if app_secret and access_token else ""
        self.version = version or graph_version()

    def close(self) -> None:
        closer = getattr(self._client, "close", None)
        if callable(closer):
            closer()

    def _url(self, path: str) -> str:
        return f"{GRAPH_HOST}/{self.version}/{path.lstrip('/')}"

    def _auth(self, params: dict | None) -> dict:
        merged = dict(params or {})
        merged["access_token"] = self._token
        if self._proof:
            merged["appsecret_proof"] = self._proof
        return merged

    def get(self, path: str, params: dict | None = None) -> GraphResult:
        try:
            response = self._client.get(self._url(path), params=self._auth(params))
        except (httpx.HTTPError, TimeoutError) as exc:
            return GraphResult(ok=False, status_code=0, error_message=f"Meta network error ({exc.__class__.__name__}).", failure_class="NETWORK")
        return _result(response)

    def post(self, path: str, data: dict | None = None, files: dict | None = None) -> GraphResult:
        try:
            if files:
                response = self._client.post(self._url(path), data=self._auth(data), files=files)
            else:
                response = self._client.post(self._url(path), data=self._auth(data))
        except (httpx.HTTPError, TimeoutError) as exc:
            return GraphResult(ok=False, status_code=0, error_message=f"Meta network error ({exc.__class__.__name__}).", failure_class="NETWORK")
        return _result(response)

    def upload_reel_bytes(self, video_id: str, data: bytes) -> GraphResult:
        url = f"{UPLOAD_HOST}/video-upload/{self.version}/{video_id}"
        headers = {
            "Authorization": f"OAuth {self._token}",
            "offset": "0",
            "file_size": str(len(data)),
            "Content-Type": "application/octet-stream",
        }
        try:
            response = self._client.post(url, headers=headers, content=data)
        except (httpx.HTTPError, TimeoutError) as exc:
            return GraphResult(ok=False, status_code=0, error_message=f"Meta upload network error ({exc.__class__.__name__}).", failure_class="NETWORK")
        return _result(response)

    # Identity and permissions

    def debug_token(self, *, app_id: str, app_secret: str, input_token: str) -> GraphResult:
        try:
            response = self._client.get(
                self._url("debug_token"),
                params={"input_token": input_token, "access_token": f"{app_id}|{app_secret}"},
            )
        except (httpx.HTTPError, TimeoutError) as exc:
            return GraphResult(ok=False, status_code=0, error_message=f"Meta network error ({exc.__class__.__name__}).", failure_class="NETWORK")
        return _result(response)

    def page(self, page_id: str) -> GraphResult:
        return self.get(page_id, {"fields": "id,name,username,followers_count,instagram_business_account{id,username}"})

    def instagram_account(self, ig_id: str) -> GraphResult:
        return self.get(ig_id, {"fields": "id,username,name,followers_count,media_count"})

    # History

    def instagram_media(self, ig_id: str, *, limit: int = 50, after: str = "") -> GraphResult:
        params = {"fields": "id,caption,media_type,media_product_type,permalink,timestamp", "limit": str(limit)}
        if after:
            params["after"] = after
        return self.get(f"{ig_id}/media", params)

    def page_posts(self, page_id: str, *, limit: int = 50, after: str = "") -> GraphResult:
        params = {"fields": "id,message,created_time,permalink_url", "limit": str(limit)}
        if after:
            params["after"] = after
        return self.get(f"{page_id}/published_posts", params)

    def media_details(self, media_id: str) -> GraphResult:
        return self.get(media_id, {"fields": "id,permalink,timestamp,media_type,media_product_type,caption"})

    def post_details(self, post_id: str) -> GraphResult:
        return self.get(post_id, {"fields": "id,permalink_url,created_time,message"})

    # Instagram publishing

    def ig_image_container(self, ig_id: str, *, image_url: str, caption: str = "", carousel_item: bool = False) -> GraphResult:
        data = {"image_url": image_url}
        if carousel_item:
            data["is_carousel_item"] = "true"
        else:
            data["caption"] = caption
        return self.post(f"{ig_id}/media", data)

    def ig_carousel_container(self, ig_id: str, *, children: list[str], caption: str) -> GraphResult:
        return self.post(f"{ig_id}/media", {"media_type": "CAROUSEL", "children": ",".join(children), "caption": caption})

    def ig_reel_container(self, ig_id: str, *, video_url: str, caption: str, cover_url: str = "") -> GraphResult:
        data = {"media_type": "REELS", "video_url": video_url, "caption": caption, "share_to_feed": "true"}
        if cover_url:
            data["cover_url"] = cover_url
        return self.post(f"{ig_id}/media", data)

    def ig_container_status(self, container_id: str) -> GraphResult:
        return self.get(container_id, {"fields": "status_code,status"})

    def ig_publish(self, ig_id: str, *, creation_id: str) -> GraphResult:
        return self.post(f"{ig_id}/media_publish", {"creation_id": creation_id})

    def ig_publishing_limit(self, ig_id: str) -> GraphResult:
        return self.get(f"{ig_id}/content_publishing_limit", {"fields": "quota_usage,config"})

    # Facebook Page publishing

    def fb_photo(self, page_id: str, *, image: bytes, caption: str, published: bool = True) -> GraphResult:
        data = {"published": "true" if published else "false"}
        if published and caption:
            data["message"] = caption
        return self.post(f"{page_id}/photos", data, files={"source": ("image.jpg", image, "image/jpeg")})

    def fb_feed(self, page_id: str, *, message: str, link: str = "", media_fbids: list[str] | None = None) -> GraphResult:
        data: dict = {"message": message}
        if link:
            data["link"] = link
        for index, media in enumerate(media_fbids or []):
            data[f"attached_media[{index}]"] = json.dumps({"media_fbid": media})
        return self.post(f"{page_id}/feed", data)

    def fb_reel_start(self, page_id: str) -> GraphResult:
        return self.post(f"{page_id}/video_reels", {"upload_phase": "start"})

    def fb_reel_finish(self, page_id: str, *, video_id: str, description: str, title: str = "") -> GraphResult:
        data = {"upload_phase": "finish", "video_id": video_id, "video_state": "PUBLISHED", "description": description}
        if title:
            data["title"] = title
        return self.post(f"{page_id}/video_reels", data)

    def fb_video_status(self, video_id: str) -> GraphResult:
        return self.get(video_id, {"fields": "status,permalink_url,post_id,created_time"})

    # Insights

    def ig_media_insights(self, media_id: str, metrics: tuple[str, ...]) -> GraphResult:
        return self.get(f"{media_id}/insights", {"metric": ",".join(metrics)})

    def ig_account_insights(self, ig_id: str, metrics: tuple[str, ...], *, period: str, since: int, until: int, total_value: bool) -> GraphResult:
        params = {"metric": ",".join(metrics), "period": period, "since": str(since), "until": str(until)}
        if total_value:
            params["metric_type"] = "total_value"
        return self.get(f"{ig_id}/insights", params)

    def fb_page_insights(self, page_id: str, metrics: tuple[str, ...], *, period: str, since: int, until: int) -> GraphResult:
        return self.get(f"{page_id}/insights", {"metric": ",".join(metrics), "period": period, "since": str(since), "until": str(until)})

    def fb_post_insights(self, post_id: str, metrics: tuple[str, ...]) -> GraphResult:
        return self.get(f"{post_id}/insights", {"metric": ",".join(metrics), "period": "lifetime"})

    def ig_business_discovery(self, ig_id: str, username: str) -> GraphResult:
        fields = (
            f"business_discovery.username({username})"
            "{username,followers_count,media_count,media.limit(25){timestamp,like_count,comments_count,media_type}}"
        )
        return self.get(ig_id, {"fields": fields})
