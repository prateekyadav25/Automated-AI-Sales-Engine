"""The Meta clients share one configured Graph version. Nothing here calls Meta."""

from app.core.config import get_settings
from app.providers.meta_growth import DEFAULT_VERSION, MetaGrowthClient, graph_base, graph_version
from app.providers.meta_leads import LEAD_FIELDS, read_lead


class _Capture:
    def __init__(self) -> None:
        self.urls: list[str] = []

    def get(self, url: str, params: dict | None = None):
        self.urls.append(url)
        return _Response()

    def post(self, url: str, data: dict | None = None, files: dict | None = None):
        self.urls.append(url)
        return _Response()


class _Lead:
    def __init__(self) -> None:
        self.url = ""
        self.params: dict = {}

    def get(self, url: str, params: dict) -> object:
        self.url = url
        self.params = params
        return _Response(payload={"id": "lead-1", "field_data": []})


class _Response:
    def __init__(self, payload: dict | None = None) -> None:
        self.status_code = 200
        self.content = b"{}"
        self.headers: dict = {}
        self._payload = payload or {"id": "1"}

    def json(self) -> dict:
        return self._payload


def test_graph_clients_follow_the_configured_version(monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "meta_graph_api_version", "v26.0")
    monkeypatch.setattr(settings, "social_growth_publish_mode", "disabled")
    monkeypatch.setattr(settings, "social_growth_insights_mode", "disabled")
    monkeypatch.setattr(settings, "ga4_mode", "disabled")
    assert graph_version() == DEFAULT_VERSION == "v26.0"
    assert graph_base() == "https://graph.facebook.com/v26.0"
    assert settings.social_growth_publish_mode == "disabled"

    capture = _Capture()
    client = MetaGrowthClient(client=capture, access_token="fixture-token", app_secret="fixture-secret")
    client.post("1784/media", {"image_url": "https://media.example/a.jpg", "caption": "Hello"})
    client.get("1784/content_publishing_limit")
    assert capture.urls == [
        "https://graph.facebook.com/v26.0/1784/media",
        "https://graph.facebook.com/v26.0/1784/content_publishing_limit",
    ]

    lead = _Lead()
    result = read_lead(lead, "lead-1", "fixture-lead-token")
    assert result.kind == "ok"
    assert lead.url == "https://graph.facebook.com/v26.0/lead-1"
    assert lead.params["fields"] == LEAD_FIELDS
    assert "has_lead_access" not in lead.params["fields"]

    monkeypatch.setattr(settings, "meta_graph_api_version", "21.0")
    assert graph_base() == "https://graph.facebook.com/v21.0"
    later = MetaGrowthClient(client=_Capture(), access_token="fixture-token")
    assert later.version == "v21.0"
