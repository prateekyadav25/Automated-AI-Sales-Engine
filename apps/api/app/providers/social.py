import re
from dataclasses import dataclass
from urllib.parse import quote, urlsplit

import httpx

from app.core.config import Settings, get_settings
from app.providers.meta_growth import graph_base

LINKEDIN_POSTS_URL = "https://api.linkedin.com/rest/posts"
LINKEDIN_VERSION = "202609"
_FACEBOOK_ID = re.compile(r"^[0-9]+(?:_[0-9]+)?$")
_LINKEDIN_URN = re.compile(r"^urn:li:(?:share|ugcPost|activity):[0-9]+$")
_LINKEDIN_NUMERIC = re.compile(r"^[0-9]+$")
_INSTAGRAM_ID = re.compile(r"^[0-9_]+$")
_INSTAGRAM_CAPTION_LIMIT = 2200
_LOCAL_IMAGE_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def instagram_caption(body: str, link_url: str = "") -> str:
    link = link_url.strip()
    text = body.strip()
    if link and link not in text:
        text = f"{link}\n\n{text}" if text else link
    if len(text) <= _INSTAGRAM_CAPTION_LIMIT:
        return text
    if link and text.startswith(link):
        room = _INSTAGRAM_CAPTION_LIMIT - len(link) - 2
        rest = text[len(link) :].strip()
        if room <= 0:
            return link[:_INSTAGRAM_CAPTION_LIMIT]
        return f"{link}\n\n{rest[:room].rstrip()}"
    return text[:_INSTAGRAM_CAPTION_LIMIT]


def provider_can_fetch(url: str) -> bool:
    parsed = urlsplit(url.strip())
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme not in {"http", "https"} or not host:
        return False
    if host in _LOCAL_IMAGE_HOSTS or host.endswith(".local") or host.endswith(".localhost"):
        return False
    return True


def instagram_can_fetch(image_url: str) -> bool:
    return provider_can_fetch(image_url)


@dataclass
class SocialPublishResult:
    ok: bool
    provider: str
    is_mock: bool
    external_id: str = ""
    permalink: str = ""
    reason: str = ""


def _facebook_story_ids(external_id: str) -> tuple[str, str]:
    value = (external_id or "").strip()
    if "_" not in value or not _FACEBOOK_ID.fullmatch(value):
        return "", ""
    page_id, post_id = value.split("_", 1)
    return page_id, post_id


def facebook_permalink_php(external_id: str) -> str:
    page_id, post_id = _facebook_story_ids(external_id)
    if not page_id:
        return ""
    return f"https://www.facebook.com/permalink.php?story_fbid={post_id}&id={page_id}"


def _facebook_host_url(url: str) -> str:
    value = (url or "").strip()
    if value.startswith("https://facebook.com/"):
        value = "https://www.facebook.com/" + value[len("https://facebook.com/") :]
    return value.rstrip("/")


def naive_facebook_posts_url(external_id: str) -> str:
    page_id, post_id = _facebook_story_ids(external_id)
    if not page_id:
        return ""
    return f"https://www.facebook.com/{page_id}/posts/{post_id}"


def is_facebook_placeholder(url: str, external_id: str) -> bool:
    value = _facebook_host_url(url)
    if not value.startswith("https://www.facebook.com/"):
        return False
    guesses = {
        item.rstrip("/")
        for item in (facebook_permalink_php(external_id), naive_facebook_posts_url(external_id))
        if item
    }
    return value in guesses


def is_usable_facebook_permalink(url: str, external_id: str = "") -> bool:
    value = (url or "").strip()
    if not value.startswith("https://www.facebook.com/") and not value.startswith("https://facebook.com/"):
        return False
    return not is_facebook_placeholder(value, external_id)


def choose_facebook_permalink(external_id: str, graph_url: str) -> str:
    url = (graph_url or "").strip()
    if url.startswith("https://www.facebook.com/") or url.startswith("https://facebook.com/"):
        return url
    return facebook_permalink_php(external_id)


def public_post_url(channel: str, external_id: str, stored: str = "") -> str:
    kept = (stored or "").strip()
    name = (channel or "").strip().lower()
    value = (external_id or "").strip()
    if name == "facebook":
        if is_usable_facebook_permalink(kept, value):
            return kept
        return facebook_permalink_php(value)
    if kept.startswith("https://"):
        return kept
    if name == "linkedin":
        if _LINKEDIN_URN.fullmatch(value):
            return f"https://www.linkedin.com/feed/update/{value}"
        if _LINKEDIN_NUMERIC.fullmatch(value):
            return f"https://www.linkedin.com/feed/update/urn:li:share:{value}"
        return ""
    return ""


def fetch_instagram_permalink(token: str, media_id: str) -> str:
    if not token.strip() or not _INSTAGRAM_ID.fullmatch((media_id or "").strip()):
        return ""
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(
                f"{graph_base()}/{media_id.strip()}",
                params={"fields": "permalink", "access_token": token},
            )
        if response.status_code >= 400:
            return ""
        url = str((response.json() or {}).get("permalink") or "").strip()
    except (httpx.HTTPError, ValueError):
        return ""
    if url.startswith("https://www.instagram.com/"):
        return url
    return ""


def fetch_facebook_permalink(token: str, external_id: str) -> str:
    graph_url = ""
    if token.strip() and _FACEBOOK_ID.fullmatch((external_id or "").strip()):
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.get(
                    f"{graph_base()}/{external_id.strip()}",
                    params={"fields": "permalink_url", "access_token": token},
                )
            if response.status_code < 400:
                graph_url = str((response.json() or {}).get("permalink_url") or "").strip()
        except (httpx.HTTPError, ValueError):
            graph_url = ""
    return choose_facebook_permalink(external_id, graph_url)


def resolved_permalink(channel: str, external_id: str, stored: str = "", token: str = "") -> str:
    name = (channel or "").strip().lower()
    if name == "facebook":
        if is_usable_facebook_permalink(stored, external_id):
            return stored.strip()
        fetched = fetch_facebook_permalink(token, external_id)
        if fetched:
            return fetched
    if name == "instagram":
        built = public_post_url(channel, external_id, stored)
        if built:
            return built
        return fetch_instagram_permalink(token, external_id)
    return public_post_url(channel, external_id, stored)


def linkedin_author_urn(organization_id: str) -> str:
    value = organization_id.strip()
    if value.startswith("urn:li:"):
        return value
    return f"urn:li:organization:{value}"


class MockSocialPublisher:
    def __init__(self, channel: str) -> None:
        self._channel = channel

    def publish(self, *, body: str, link_url: str = "", image_url: str = "") -> SocialPublishResult:
        _ = (body, link_url, image_url)
        return SocialPublishResult(
            ok=True,
            provider=f"mock-{self._channel}",
            is_mock=True,
            external_id="",
            reason="Mock post was recorded and was not sent.",
        )


class NotConfiguredSocialPublisher:
    def __init__(self, channel: str, missing: list[str]) -> None:
        self._channel = channel
        self._missing = missing

    def publish(self, *, body: str, link_url: str = "", image_url: str = "") -> SocialPublishResult:
        _ = (body, link_url, image_url)
        needed = ", ".join(self._missing)
        return SocialPublishResult(
            ok=False,
            provider=self._channel,
            is_mock=False,
            reason=f"NOT_CONFIGURED. Set {needed}.",
        )


class LinkedInSocialPublisher:
    def __init__(self, *, token: str, organization_id: str, client: httpx.Client | None = None) -> None:
        self._token = token
        self._author = linkedin_author_urn(organization_id)
        self._client = client

    def publish(self, *, body: str, link_url: str = "", image_url: str = "") -> SocialPublishResult:
        _ = image_url
        payload: dict = {
            "author": self._author,
            "commentary": body,
            "visibility": "PUBLIC",
            "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [], "thirdPartyDistributionChannels": []},
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        }
        if link_url.strip():
            payload["content"] = {"article": {"source": link_url.strip(), "title": body[:200]}}
        owns = self._client is None
        client = self._client or httpx.Client(timeout=30.0)
        try:
            response = client.post(
                LINKEDIN_POSTS_URL,
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Linkedin-Version": LINKEDIN_VERSION,
                    "X-Restli-Protocol-Version": "2.0.0",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            if response.status_code >= 400:
                return SocialPublishResult(
                    ok=False,
                    provider="linkedin",
                    is_mock=False,
                    reason=f"LinkedIn refused the post ({response.status_code}).",
                )
            external_id = str(response.headers.get("x-restli-id") or "")
            return SocialPublishResult(
                ok=bool(external_id),
                provider="linkedin",
                is_mock=False,
                external_id=external_id,
                permalink=public_post_url("linkedin", external_id),
                reason="" if external_id else "LinkedIn returned no post id.",
            )
        except httpx.HTTPError:
            return SocialPublishResult(ok=False, provider="linkedin", is_mock=False, reason="LinkedIn network error.")
        finally:
            if owns:
                client.close()

    def update_commentary(self, *, external_id: str, body: str) -> SocialPublishResult:
        if not external_id.strip():
            return SocialPublishResult(ok=False, provider="linkedin", is_mock=False, reason="This post has no LinkedIn id.")
        owns = self._client is None
        client = self._client or httpx.Client(timeout=30.0)
        try:
            response = client.post(
                f"{LINKEDIN_POSTS_URL}/{quote(external_id.strip(), safe='')}",
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Linkedin-Version": LINKEDIN_VERSION,
                    "X-Restli-Protocol-Version": "2.0.0",
                    "X-RestLi-Method": "PARTIAL_UPDATE",
                    "Content-Type": "application/json",
                },
                json={"patch": {"$set": {"commentary": body}}},
            )
            if response.status_code >= 400:
                return SocialPublishResult(
                    ok=False,
                    provider="linkedin",
                    is_mock=False,
                    reason=f"LinkedIn refused the edit ({response.status_code}).",
                )
            return SocialPublishResult(ok=True, provider="linkedin", is_mock=False, external_id=external_id.strip())
        except httpx.HTTPError:
            return SocialPublishResult(ok=False, provider="linkedin", is_mock=False, reason="LinkedIn network error.")
        finally:
            if owns:
                client.close()


class MetaSocialPublisher:
    def __init__(self, *, page_id: str, page_token: str, instagram_id: str = "", client: httpx.Client | None = None) -> None:
        self._page_id = page_id
        self._token = page_token
        self._instagram_id = instagram_id
        self._client = client

    def publish(
        self,
        *,
        body: str,
        link_url: str = "",
        image_url: str = "",
        image_bytes: bytes = b"",
        instagram: bool = False,
    ) -> SocialPublishResult:
        if instagram:
            return self._publish_instagram(
                body=body,
                link_url=link_url,
                image_url=image_url,
                image_bytes=image_bytes,
            )
        if image_bytes:
            return self._publish_page_photo(body=body, image_bytes=image_bytes)
        return self._publish_page(body=body, link_url=link_url)

    def _publish_page(self, *, body: str, link_url: str) -> SocialPublishResult:
        data = {"message": body, "published": "true", "access_token": self._token}
        link = link_url.strip()
        if link and provider_can_fetch(link):
            data["link"] = link
        return self._post(f"{graph_base()}/{self._page_id}/feed", data, provider="facebook")

    def _publish_page_photo(self, *, body: str, image_bytes: bytes) -> SocialPublishResult:
        return self._upload_photo(image_bytes, published=True, message=body)

    def _publish_instagram(self, *, body: str, link_url: str, image_url: str, image_bytes: bytes = b"") -> SocialPublishResult:
        if not self._instagram_id:
            return SocialPublishResult(
                ok=False,
                provider="instagram",
                is_mock=False,
                reason="NOT_CONFIGURED. Set INSTAGRAM_BUSINESS_ACCOUNT_ID.",
            )
        usable = image_url.strip()
        if usable and not instagram_can_fetch(usable):
            if not image_bytes:
                return SocialPublishResult(
                    ok=False,
                    provider="instagram",
                    is_mock=False,
                    reason="Instagram cannot fetch an image hosted on this machine. Paste a public image URL, or publish from a public https address.",
                )
            usable = ""
        if not usable and image_bytes:
            hosted, problem = self._host_image(image_bytes)
            if problem:
                return SocialPublishResult(ok=False, provider="instagram", is_mock=False, reason=problem)
            usable = hosted
        if not usable:
            return SocialPublishResult(
                ok=False,
                provider="instagram",
                is_mock=False,
                reason="Instagram posts require a public image URL.",
            )
        if not instagram_can_fetch(usable):
            return SocialPublishResult(
                ok=False,
                provider="instagram",
                is_mock=False,
                reason="Instagram cannot fetch an image hosted on this machine. Paste a public image URL, or publish from a public https address.",
            )
        created = self._post(
            f"{graph_base()}/{self._instagram_id}/media",
            {"image_url": usable, "caption": instagram_caption(body, link_url), "access_token": self._token},
            provider="instagram",
        )
        if not created.ok:
            return created
        return self._post(
            f"{graph_base()}/{self._instagram_id}/media_publish",
            {"creation_id": created.external_id, "access_token": self._token},
            provider="instagram",
        )

    def _upload_photo(self, data: bytes, *, published: bool, message: str = "") -> SocialPublishResult:
        form = {"published": "true" if published else "false", "access_token": self._token}
        if published and message:
            form["message"] = message
        if not published:
            form["temporary"] = "true"
        owns = self._client is None
        client = self._client or httpx.Client(timeout=60.0)
        try:
            response = client.post(
                f"{graph_base()}/{self._page_id}/photos",
                data=form,
                files={"source": ("banner.png", data, "image/png")},
            )
            if response.status_code >= 400:
                return SocialPublishResult(
                    ok=False,
                    provider="facebook",
                    is_mock=False,
                    reason=_meta_refusal("Meta refused the image", response),
                )
            payload = response.json() if response.content else {}
            external_id = str(payload.get("post_id") or payload.get("id") or "")
            if not external_id:
                return SocialPublishResult(ok=False, provider="facebook", is_mock=False, reason="Meta returned no post id.")
            permalink = self._permalink(external_id=external_id, provider="facebook") if published else ""
            return SocialPublishResult(
                ok=True,
                provider="facebook",
                is_mock=False,
                external_id=external_id,
                permalink=permalink or public_post_url("facebook", external_id),
            )
        except httpx.HTTPError:
            return SocialPublishResult(ok=False, provider="facebook", is_mock=False, reason="Meta network error.")
        finally:
            if owns:
                client.close()

    def _host_image(self, data: bytes) -> tuple[str, str]:
        owns = self._client is None
        client = self._client or httpx.Client(timeout=60.0)
        try:
            response = client.post(
                f"{graph_base()}/{self._page_id}/photos",
                data={"published": "false", "temporary": "true", "access_token": self._token},
                files={"source": ("banner.png", data, "image/png")},
            )
            if response.status_code >= 400:
                return "", _meta_refusal("Meta refused the image", response)
            photo_id = str((response.json() if response.content else {}).get("id") or "")
            if not photo_id:
                return "", "Meta returned no image id."
            fetched = client.get(
                f"{graph_base()}/{photo_id}",
                params={"fields": "images", "access_token": self._token},
            )
            if fetched.status_code >= 400:
                return "", _meta_refusal("Meta refused the image", fetched)
            url = _largest_image_url(fetched.json() if fetched.content else {})
            if not url:
                return "", "Meta did not return a public image address."
            return url, ""
        except httpx.HTTPError:
            return "", "Meta network error."
        finally:
            if owns:
                client.close()

    def update_message(self, *, external_id: str, body: str) -> SocialPublishResult:
        if not external_id.strip():
            return SocialPublishResult(ok=False, provider="facebook", is_mock=False, reason="This post has no Facebook id.")
        owns = self._client is None
        client = self._client or httpx.Client(timeout=30.0)
        try:
            response = client.post(
                f"{graph_base()}/{external_id.strip()}",
                data={"message": body, "access_token": self._token},
            )
            if response.status_code >= 400:
                return SocialPublishResult(
                    ok=False,
                    provider="facebook",
                    is_mock=False,
                    reason=_meta_refusal("Facebook refused the edit", response),
                )
            return SocialPublishResult(ok=True, provider="facebook", is_mock=False, external_id=external_id.strip())
        except httpx.HTTPError:
            return SocialPublishResult(ok=False, provider="facebook", is_mock=False, reason="Meta network error.")
        finally:
            if owns:
                client.close()

    def _post(self, url: str, data: dict, *, provider: str) -> SocialPublishResult:
        owns = self._client is None
        client = self._client or httpx.Client(timeout=30.0)
        try:
            response = client.post(url, data=data)
            if response.status_code >= 400:
                return SocialPublishResult(ok=False, provider=provider, is_mock=False, reason=_meta_refusal("Meta refused the post", response))
            payload = response.json() if response.content else {}
            external_id = str(payload.get("id") or "")
            permalink = self._permalink(external_id=external_id, provider=provider) if external_id else ""
            return SocialPublishResult(
                ok=bool(external_id),
                provider=provider,
                is_mock=False,
                external_id=external_id,
                permalink=permalink or public_post_url(provider, external_id),
                reason="" if external_id else "Meta returned no post id.",
            )
        except httpx.HTTPError:
            return SocialPublishResult(ok=False, provider=provider, is_mock=False, reason="Meta network error.")
        finally:
            if owns:
                client.close()

    def _permalink(self, *, external_id: str, provider: str) -> str:
        field = "permalink" if provider == "instagram" else "permalink_url"
        getter = getattr(self._client, "get", None)
        owns = False
        client = self._client if getter is not None else None
        if client is None:
            client = httpx.Client(timeout=10.0)
            owns = True
            getter = client.get
        try:
            response = getter(
                f"{graph_base()}/{external_id}",
                params={"fields": field, "access_token": self._token},
            )
            if getattr(response, "status_code", 400) >= 400:
                return ""
            payload = response.json() if getattr(response, "content", None) or hasattr(response, "json") else {}
            url = str((payload or {}).get(field) or "").strip()
        except (httpx.HTTPError, ValueError, TypeError):
            return ""
        finally:
            if owns:
                client.close()
        allowed = "https://www.instagram.com/" if provider == "instagram" else "https://www.facebook.com/"
        return url if url.startswith(allowed) else ""


def posting_gaps(settings: Settings, channel: str) -> list[str]:
    if channel == "linkedin":
        missing: list[str] = []
        if not settings.linkedin_post_access_token:
            missing.append("LINKEDIN_POST_ACCESS_TOKEN")
        if not settings.linkedin_organization_id:
            missing.append("LINKEDIN_ORGANIZATION_ID")
        return missing
    if channel == "facebook":
        missing = []
        if not settings.meta_page_id:
            missing.append("META_PAGE_ID")
        if not settings.meta_page_access_token:
            missing.append("META_PAGE_ACCESS_TOKEN")
        return missing
    if channel == "instagram":
        missing = posting_gaps(settings, "facebook")
        if not settings.instagram_business_account_id:
            missing.append("INSTAGRAM_BUSINESS_ACCOUNT_ID")
        return missing
    if channel == "youtube":
        missing = []
        if not settings.youtube_api_key.strip():
            missing.append("YOUTUBE_API_KEY")
        if not settings.youtube_channel_id.strip():
            missing.append("YOUTUBE_CHANNEL_ID")
        return missing
    if channel == "x":
        missing = []
        if not settings.x_api_key.strip():
            missing.append("X_API_KEY")
        if not settings.x_access_token.strip():
            missing.append("X_ACCESS_TOKEN")
        return missing
    if channel == "whatsapp":
        missing = []
        if not settings.whatsapp_phone_number_id.strip():
            missing.append("WHATSAPP_PHONE_NUMBER_ID")
        if not settings.whatsapp_access_token.strip():
            missing.append("WHATSAPP_ACCESS_TOKEN")
        return missing
    return ["channel"]


def _largest_image_url(payload: dict) -> str:
    images = payload.get("images") or []
    if not isinstance(images, list):
        return ""
    best = ""
    best_width = -1
    for item in images:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source") or "")
        if not source.startswith("https://"):
            continue
        try:
            width = int(item.get("width") or 0)
        except (TypeError, ValueError):
            width = 0
        if width >= best_width:
            best = source
            best_width = width
    return best


def _meta_refusal(prefix: str, response: httpx.Response) -> str:
    message = ""
    try:
        error = (response.json() or {}).get("error") or {}
        if isinstance(error, dict):
            message = str(error.get("message") or "").replace("\n", " ").strip()
    except ValueError:
        message = ""
    detail = f"{prefix} ({response.status_code})."
    return f"{detail} {message[:180]}".strip()


def reaches_provider(mode: str) -> bool:
    return (mode or "").strip().lower() == "live"


def get_social_publisher(channel: str):
    settings = get_settings()
    normalized = channel.strip().lower()
    if normalized == "linkedin":
        mode = (settings.linkedin_posting_mode or "mock").strip().lower()
        if mode == "live":
            missing = posting_gaps(settings, "linkedin")
            if missing:
                return NotConfiguredSocialPublisher("linkedin", missing)
            return LinkedInSocialPublisher(
                token=settings.linkedin_post_access_token,
                organization_id=settings.linkedin_organization_id,
            )
        return MockSocialPublisher("linkedin")
    if normalized in {"facebook", "instagram"}:
        mode = (settings.meta_posting_mode or "mock").strip().lower()
        if reaches_provider(mode):
            missing = posting_gaps(settings, normalized)
            if missing:
                return NotConfiguredSocialPublisher(normalized, missing)
            return MetaSocialPublisher(
                page_id=settings.meta_page_id,
                page_token=settings.meta_page_access_token,
                instagram_id=settings.instagram_business_account_id,
            )
        return MockSocialPublisher(normalized)
    return NotConfiguredSocialPublisher(normalized or "social", ["channel"])
