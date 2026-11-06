from decimal import Decimal
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.db.session import get_session
from app.models.social import SocialPost
from app.providers.ads import get_ads_provider
from app.providers.social import (
    LinkedInSocialPublisher,
    MetaSocialPublisher,
    SocialPublishResult,
    choose_facebook_permalink,
    instagram_caption,
    public_post_url,
    resolved_permalink,
)
from tests.conftest import login


def test_public_post_url_builds_network_links() -> None:
    assert public_post_url("facebook", "111_222") == "https://www.facebook.com/permalink.php?story_fbid=222&id=111"
    assert public_post_url("linkedin", "urn:li:share:9") == "https://www.linkedin.com/feed/update/urn:li:share:9"
    assert public_post_url("instagram", "1789") == ""
    assert public_post_url("facebook", "111_222", "https://www.facebook.com/111/posts/222") == "https://www.facebook.com/permalink.php?story_fbid=222&id=111"
    assert (
        public_post_url("facebook", "111_222", "https://www.facebook.com/permalink.php?story_fbid=p&id=111")
        == "https://www.facebook.com/permalink.php?story_fbid=p&id=111"
    )
    graph = "https://www.facebook.com/122097522249494891/posts/122108961333494891"
    external = "1375611092307204_122108961333494891"
    assert public_post_url("facebook", external, graph) == graph
    assert choose_facebook_permalink(external, graph) == graph
    assert choose_facebook_permalink("111_222", "") == "https://www.facebook.com/permalink.php?story_fbid=222&id=111"
    placeholder = "https://www.facebook.com/permalink.php?story_fbid=122108961333494891&id=1375611092307204"
    assert resolved_permalink("facebook", external, graph) == graph
    assert resolved_permalink("facebook", external, placeholder, token="") == placeholder


def test_facebook_placeholder_is_replaced_with_the_graph_link(monkeypatch) -> None:
    graph = "https://www.facebook.com/122097522249494891/posts/122108961333494891"
    external = "1375611092307204_122108961333494891"
    placeholder = "https://www.facebook.com/permalink.php?story_fbid=122108961333494891&id=1375611092307204"
    monkeypatch.setattr("app.providers.social.fetch_facebook_permalink", lambda token, external_id: graph)
    assert resolved_permalink("facebook", external, placeholder, token="page-token") == graph


def test_mock_linkedin_post_is_not_sent(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("LINKEDIN_POSTING_MODE", "mock")
    get_settings.cache_clear()
    headers = login(client)
    try:
        created = client.post(
            "/api/v1/social/posts",
            headers=headers,
            json={"channel": "linkedin", "body": "Hello from the demo."},
        )
        assert created.status_code == 200
        row = created.json()["data"]
        assert row["is_mock"] is True
        assert row["status"] == "mock"
        assert row["provider"] == "mock-linkedin"
        assert row["external_id"] == ""
        listed = client.get("/api/v1/social/posts", headers=headers)
        assert listed.status_code == 200
        assert any(item["id"] == row["id"] for item in listed.json()["data"])
    finally:
        monkeypatch.delenv("LINKEDIN_POSTING_MODE", raising=False)
        get_settings.cache_clear()


def test_live_linkedin_without_token_is_not_a_silent_post(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("LINKEDIN_POSTING_MODE", "live")
    monkeypatch.setenv("LINKEDIN_POST_ACCESS_TOKEN", "")
    monkeypatch.setenv("LINKEDIN_ORGANIZATION_ID", "")
    get_settings.cache_clear()
    headers = login(client)
    try:
        created = client.post(
            "/api/v1/social/posts",
            headers=headers,
            json={"channel": "linkedin", "body": "This must not publish."},
        )
        assert created.status_code == 200
        row = created.json()["data"]
        assert row["is_mock"] is False
        assert row["status"] == "failed"
        assert "NOT_CONFIGURED" in row["error"]
        assert "LINKEDIN_POST_ACCESS_TOKEN" in row["error"]
    finally:
        monkeypatch.delenv("LINKEDIN_POSTING_MODE", raising=False)
        monkeypatch.delenv("LINKEDIN_POST_ACCESS_TOKEN", raising=False)
        monkeypatch.delenv("LINKEDIN_ORGANIZATION_ID", raising=False)
        get_settings.cache_clear()


def test_linkedin_publisher_posts_organization_feed(monkeypatch) -> None:
    monkeypatch.setenv("LINKEDIN_ORGANIZATION_ID", "143930363")
    get_settings.cache_clear()

    class _Response:
        status_code = 201
        headers = {"x-restli-id": "urn:li:share:1"}
        content = b""

    class _Client:
        def __init__(self) -> None:
            self.url = ""
            self.body: dict | None = None

        def post(self, url: str, headers: dict | None = None, json: dict | None = None) -> _Response:
            self.url = url
            self.body = json
            return _Response()

    client = _Client()
    try:
        result = LinkedInSocialPublisher(token="test-token", organization_id="143930363", client=client).publish(body="Ship the note.")  # type: ignore[arg-type]
        assert client.url == "https://api.linkedin.com/rest/posts"
        assert client.body is not None
        assert client.body["author"] == "urn:li:organization:143930363"
        assert client.body["commentary"] == "Ship the note."
        assert result.ok is True
        assert result.is_mock is False
        assert result.external_id == "urn:li:share:1"
        assert result.permalink == "https://www.linkedin.com/feed/update/urn:li:share:1"
    finally:
        monkeypatch.delenv("LINKEDIN_ORGANIZATION_ID", raising=False)
        get_settings.cache_clear()


def test_facebook_publisher_stores_permalink() -> None:
    class _Response:
        def __init__(self, payload: dict, status_code: int = 200) -> None:
            self.status_code = status_code
            self.content = b"{}"
            self._payload = payload

        def json(self) -> dict:
            return self._payload

    class _Client:
        def post(self, url: str, data: dict | None = None) -> _Response:
            _ = (url, data)
            return _Response({"id": "111_222"})

        def get(self, url: str, params: dict | None = None) -> _Response:
            _ = (url, params)
            return _Response({"permalink_url": "https://www.facebook.com/111/posts/222"})

    result = MetaSocialPublisher(page_id="111", page_token="token", client=_Client()).publish(body="Hello page.")  # type: ignore[arg-type]
    assert result.ok is True
    assert result.external_id == "111_222"
    assert result.permalink == "https://www.facebook.com/111/posts/222"


def test_facebook_leaves_off_a_link_meta_cannot_open() -> None:
    class _Response:
        def __init__(self, payload: dict) -> None:
            self.status_code = 200
            self.content = b"{}"
            self._payload = payload

        def json(self) -> dict:
            return self._payload

    class _Client:
        def __init__(self) -> None:
            self.data: dict = {}

        def post(self, url: str, data: dict | None = None, files: dict | None = None) -> _Response:
            _ = (url, files)
            self.data = data or {}
            return _Response({"id": "111_222"})

        def get(self, url: str, params: dict | None = None) -> _Response:
            _ = (url, params)
            return _Response({"permalink_url": "https://www.facebook.com/111/posts/222"})

    client = _Client()
    result = MetaSocialPublisher(page_id="111", page_token="token", client=client).publish(  # type: ignore[arg-type]
        body="Hello page.",
        link_url="http://localhost:3000/capture/demo",
    )
    assert result.ok is True
    assert "link" not in client.data


def test_instagram_hosts_a_local_banner_before_publishing() -> None:
    class _Response:
        def __init__(self, payload: dict) -> None:
            self.status_code = 200
            self.content = b"{}"
            self._payload = payload

        def json(self) -> dict:
            return self._payload

    class _Client:
        def __init__(self) -> None:
            self.image_url = ""

        def post(self, url: str, data: dict | None = None, files: dict | None = None) -> _Response:
            _ = url
            if files:
                return _Response({"id": "photo1"})
            payload = data or {}
            if "image_url" in payload:
                self.image_url = str(payload["image_url"])
                return _Response({"id": "creation1"})
            return _Response({"id": "media1"})

        def get(self, url: str, params: dict | None = None) -> _Response:
            _ = url
            if params and params.get("fields") == "images":
                return _Response({"images": [{"source": "https://cdn.example.test/hosted.jpg", "width": 1200}]})
            return _Response({"permalink": "https://www.instagram.com/p/abc/"})

    client = _Client()
    result = MetaSocialPublisher(page_id="1", page_token="token", instagram_id="9", client=client).publish(  # type: ignore[arg-type]
        body="See the offer.",
        image_url="http://localhost:8000/api/v1/public/media/abc",
        image_bytes=b"\x89PNG",
        instagram=True,
    )
    assert result.ok is True
    assert client.image_url == "https://cdn.example.test/hosted.jpg"
    assert result.permalink == "https://www.instagram.com/p/abc/"


def test_selected_form_is_attached_to_the_post(client: TestClient) -> None:
    headers = login(client)
    created_form = client.post("/api/v1/acquisition/form-keys", headers=headers, json={"name": "Demo request"})
    assert created_form.status_code == 200, created_form.text
    form = created_form.json()["data"]
    assert form["url"].endswith(f"/capture/{form['token']}")
    posted = client.post(
        "/api/v1/social/posts",
        headers=headers,
        json={"channel": "linkedin", "body": "Book a demo from this post.", "form_key_id": form["id"]},
    )
    assert posted.status_code == 200, posted.text
    row = posted.json()["data"]
    assert row["form_name"] == "Demo request"
    assert row["form_key_id"] == form["id"]
    assert row["link_url"].startswith(form["url"])
    assert "utm_medium=social" in row["link_url"]
    assert "utm_source=linkedin" in row["link_url"]
    listed = client.get("/api/v1/social/posts", headers=headers)
    assert any(item["id"] == row["id"] and item["form_name"] == "Demo request" for item in listed.json()["data"])
    duplicate = client.post("/api/v1/acquisition/form-keys", headers=headers, json={"name": "Demo request"})
    assert duplicate.status_code == 409
    missing = client.post(
        "/api/v1/social/posts",
        headers=headers,
        json={"channel": "linkedin", "body": "No such form.", "form_key_id": "00000000-0000-0000-0000-000000000099"},
    )
    assert missing.status_code == 404


def test_instagram_caption_puts_the_form_link_first() -> None:
    link = "https://example.test/capture/demo"
    caption = instagram_caption("See the offer.", link)
    assert caption.startswith(link)
    assert "See the offer." in caption

    class _Response:
        def __init__(self, payload: dict) -> None:
            self.status_code = 200
            self.content = b"{}"
            self._payload = payload

        def json(self) -> dict:
            return self._payload

    class _Client:
        def __init__(self) -> None:
            self.caption = ""

        def post(self, url: str, data: dict | None = None) -> _Response:
            if data and "caption" in data:
                self.caption = str(data["caption"])
            return _Response({"id": "1789"})

        def get(self, url: str, params: dict | None = None) -> _Response:
            _ = (url, params)
            return _Response({"permalink": "https://www.instagram.com/p/abc/"})

    client = _Client()
    result = MetaSocialPublisher(page_id="1", page_token="token", instagram_id="9", client=client).publish(  # type: ignore[arg-type]
        body="See the offer.",
        link_url=link,
        image_url="https://cdn.example.test/photo.jpg",
        instagram=True,
    )
    assert result.ok is True
    assert client.caption.startswith(link)
    local = MetaSocialPublisher(page_id="1", page_token="token", instagram_id="9", client=client).publish(  # type: ignore[arg-type]
        body="See the offer.",
        image_url="http://localhost:8000/api/v1/public/media/abc",
        instagram=True,
    )
    assert local.ok is False
    assert "cannot fetch" in local.reason


def test_uploaded_image_is_readable_without_a_login(client: TestClient, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("OBJECT_STORAGE_LOCAL_ROOT", str(tmp_path))
    get_settings.cache_clear()
    headers = login(client)
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    try:
        uploaded = client.post("/api/v1/social/images", headers=headers, files={"file": ("photo.png", png, "image/png")})
        assert uploaded.status_code == 200, uploaded.text
        url = uploaded.json()["data"]["url"]
        token = url.rsplit("/", 1)[-1]
        public = client.get(f"/api/v1/public/media/{token}")
        assert public.status_code == 200, public.text
        assert public.content == png
        assert public.headers["content-type"].startswith("image/png")
        assert public.headers["x-content-type-options"] == "nosniff"
        rejected = client.post(
            "/api/v1/social/images",
            headers=headers,
            files={"file": ("note.txt", b"not an image", "text/plain")},
        )
        assert rejected.status_code == 422
    finally:
        get_settings.cache_clear()


def test_saved_post_can_be_edited(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("LINKEDIN_POSTING_MODE", "mock")
    get_settings.cache_clear()
    headers = login(client)
    try:
        created = client.post(
            "/api/v1/social/posts",
            headers=headers,
            json={"channel": "linkedin", "body": "First wording."},
        )
        assert created.status_code == 200, created.text
        row = created.json()["data"]
        assert row["status"] == "mock"
        edited = client.patch(
            f"/api/v1/social/posts/{row['id']}",
            headers=headers,
            json={"body": "Revised wording."},
        )
        assert edited.status_code == 200, edited.text
        updated = edited.json()["data"]
        assert updated["id"] == row["id"]
        assert updated["body"] == "Revised wording."
        assert updated["status"] == "mock"
        listed = client.get("/api/v1/social/posts", headers=headers)
        matches = [item for item in listed.json()["data"] if item["id"] == row["id"]]
        assert len(matches) == 1
        assert matches[0]["body"] == "Revised wording."
    finally:
        monkeypatch.delenv("LINKEDIN_POSTING_MODE", raising=False)
        get_settings.cache_clear()


def test_published_instagram_post_cannot_be_edited(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("META_POSTING_MODE", "mock")
    get_settings.cache_clear()
    headers = login(client)
    try:
        created = client.post(
            "/api/v1/social/posts",
            headers=headers,
            json={"channel": "instagram", "body": "Live caption.", "image_url": "https://cdn.example.test/photo.jpg"},
        )
        assert created.status_code == 200, created.text
        row = created.json()["data"]
    finally:
        monkeypatch.delenv("META_POSTING_MODE", raising=False)
        get_settings.cache_clear()
    db = get_session()
    try:
        stored = db.get(SocialPost, UUID(row["id"]))
        assert stored is not None
        stored.status = "published"
        stored.is_mock = False
        stored.external_id = "1789"
        stored.permalink = "https://www.instagram.com/p/abc/"
        db.commit()
    finally:
        db.close()
    edited = client.patch(
        f"/api/v1/social/posts/{row['id']}",
        headers=headers,
        json={"body": "Changed caption."},
    )
    assert edited.status_code == 422
    assert "cannot be changed" in edited.json()["detail"]
    listed = client.get("/api/v1/social/posts", headers=headers)
    kept = next(item for item in listed.json()["data"] if item["id"] == row["id"])
    assert kept["body"] == "Live caption."


def test_facebook_page_post_message_can_be_updated() -> None:
    class _Response:
        status_code = 200
        content = b"{}"

        def json(self) -> dict:
            return {"success": True}

    class _Client:
        def __init__(self) -> None:
            self.url = ""
            self.data: dict | None = None

        def post(self, url: str, data: dict | None = None) -> _Response:
            self.url = url
            self.data = data
            return _Response()

    client = _Client()
    result = MetaSocialPublisher(page_id="111", page_token="token", client=client).update_message(  # type: ignore[arg-type]
        external_id="111_222",
        body="Updated caption.",
    )
    assert result.ok is True
    assert client.url.endswith("/111_222")
    assert client.data is not None
    assert client.data["message"] == "Updated caption."


def test_linkedin_commentary_can_be_updated() -> None:
    class _Response:
        status_code = 204
        content = b""

    class _Client:
        def __init__(self) -> None:
            self.url = ""
            self.body: dict | None = None
            self.headers: dict | None = None

        def post(self, url: str, headers: dict | None = None, json: dict | None = None) -> _Response:
            self.url = url
            self.headers = headers
            self.body = json
            return _Response()

    client = _Client()
    result = LinkedInSocialPublisher(token="test-token", organization_id="143930363", client=client).update_commentary(  # type: ignore[arg-type]
        external_id="urn:li:share:1",
        body="Updated commentary.",
    )
    assert result.ok is True
    assert client.url.endswith("urn%3Ali%3Ashare%3A1")
    assert client.headers is not None
    assert client.headers["X-RestLi-Method"] == "PARTIAL_UPDATE"
    assert client.body == {"patch": {"$set": {"commentary": "Updated commentary."}}}


def test_extra_links_stay_beside_the_form_and_are_written_into_the_text(client: TestClient, monkeypatch) -> None:
    captured: dict[str, str] = {}

    class _Publisher:
        def publish(self, *, body: str, link_url: str = "", image_url: str = "") -> SocialPublishResult:
            _ = image_url
            captured["body"] = body
            captured["link"] = link_url
            return SocialPublishResult(ok=True, provider="mock-linkedin", is_mock=True)

    monkeypatch.setattr("app.services.social.get_social_publisher", lambda channel: _Publisher())
    headers = login(client)
    created_form = client.post(
        "/api/v1/acquisition/form-keys",
        headers=headers,
        json={"name": f"Campus visit {uuid4().hex[:8]}"},
    )
    assert created_form.status_code == 200, created_form.text
    form = created_form.json()["data"]
    posted = client.post(
        "/api/v1/social/posts",
        headers=headers,
        json={
            "channel": "linkedin",
            "body": "Book a demo from this post.",
            "form_key_id": form["id"],
            "extra_links": [
                {"label": "Website", "url": "https://example.test"},
                {"label": "", "url": "https://example.test/brochure"},
                {"label": "Again", "url": "https://example.test"},
            ],
        },
    )
    assert posted.status_code == 200, posted.text
    row = posted.json()["data"]
    assert row["link_url"].startswith(form["url"])
    assert row["body"] == "Book a demo from this post."
    assert row["extra_links"] == [
        {"label": "Website", "url": "https://example.test"},
        {"label": "", "url": "https://example.test/brochure"},
    ]
    assert captured["body"].startswith("Book a demo from this post.")
    assert "Website: https://example.test" in captured["body"]
    assert "https://example.test/brochure" in captured["body"]
    assert captured["link"].startswith(form["url"])
    rejected = client.post(
        "/api/v1/social/posts",
        headers=headers,
        json={"channel": "linkedin", "body": "Bad link.", "extra_links": [{"label": "Website", "url": "javascript:alert(1)"}]},
    )
    assert rejected.status_code == 422
    assert "http://" in rejected.json()["detail"]


def test_prepared_channels_do_not_publish(client: TestClient) -> None:
    headers = login(client)
    for channel in ("youtube", "x", "whatsapp"):
        created = client.post(
            "/api/v1/social/posts",
            headers=headers,
            json={"channel": channel, "body": "This must not leave Sales Engine.", "link_url": "https://example.test/form"},
        )
        assert created.status_code == 200, created.text
        row = created.json()["data"]
        assert row["status"] == "not_configured"
        assert row["is_mock"] is False
        assert row["external_id"] == ""
        assert "NOT_CONFIGURED" in row["error"]
    ads = get_ads_provider("google_ads").create_campaign(name="Search", objective="leads", budget=Decimal("1"))
    assert ads.ok is False
    assert ads.is_mock is False
    assert "not configured" in ads.reason


def test_title_artwork_leaves_the_ranking_text_off_the_picture() -> None:
    from app.services.social_artwork import draw_banner_png, draw_title_clip

    png = draw_banner_png("Plant line")
    clip = draw_title_clip("Plant line")
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert clip.startswith(b"GIF89a")
    assert b"creative relevance" not in png
    assert b"creative relevance" not in clip


def test_saved_post_waits_until_approved(client: TestClient, monkeypatch) -> None:
    calls: list[str] = []

    def fake_send(db, tenant_id, normalized, body, link_url, image_url):
        _ = (db, tenant_id, body, link_url, image_url)
        calls.append(normalized)
        return (
            "published",
            SocialPublishResult(ok=True, provider="test", is_mock=False, external_id="ext-1", permalink="https://example.test/post"),
        )

    monkeypatch.setattr("app.services.social._send", fake_send)
    monkeypatch.setattr("app.services.dispatcher._channel_blocked", lambda *args, **kwargs: "")
    headers = login(client)
    created = client.post(
        "/api/v1/social/submissions",
        headers=headers,
        json={
            "headline": "Plant line in two weeks",
            "keyword": "governed ai",
            "ranking_parameter": "creative relevance",
            "snippet": "One line about a plant.",
            "context": "A short note for operators.",
            "body": "The line is ready for a walkthrough.",
            "channels": ["linkedin", "facebook"],
        },
    )
    assert created.status_code == 200, created.text
    data = created.json()["data"]
    assert calls == []
    assert {row["status"] for row in data["posts"]} == {"pending_approval"}
    assert all("governed ai" not in row["body"].lower() for row in data["posts"])
    assert all(row["external_id"] == "" for row in data["posts"])
    listed = client.get("/api/v1/ai/approvals", headers=headers)
    assert listed.status_code == 200, listed.text
    match = next(item for item in listed.json()["data"] if item["id"] == data["approval_id"])
    assert match["category"] == "MARKETING"
    assert match["status"] == "pending"
    assert match["who"] == "LinkedIn, Facebook"
    decided = client.post(
        f"/api/v1/ai/approvals/{data['approval_id']}/decide",
        headers=headers,
        json={"decision": "approve", "note": "Approved in test"},
    )
    assert decided.status_code == 200, decided.text
    assert calls == ["linkedin", "facebook"]
    again = client.get("/api/v1/social/posts", headers=headers)
    saved = [item for item in again.json()["data"] if item["id"] in {row["id"] for row in data["posts"]}]
    assert {item["status"] for item in saved} == {"published"}
    held = client.post(
        "/api/v1/social/submissions",
        headers=headers,
        json={
            "headline": "Hold this plant note",
            "keyword": "governed ai",
            "ranking_parameter": "creative relevance",
            "snippet": "One line about a plant.",
            "context": "A short note for operators.",
            "body": "This one should stay unpublished.",
            "channels": ["linkedin"],
        },
    )
    assert held.status_code == 200, held.text
    held_data = held.json()["data"]
    refused = client.post(
        f"/api/v1/ai/approvals/{held_data['approval_id']}/decide",
        headers=headers,
        json={"decision": "reject", "note": "Not this one"},
    )
    assert refused.status_code == 200, refused.text
    after = client.get("/api/v1/social/posts", headers=headers)
    refused_rows = [item for item in after.json()["data"] if item["id"] == held_data["posts"][0]["id"]]
    assert refused_rows[0]["status"] == "rejected"
    assert calls == ["linkedin", "facebook"]
