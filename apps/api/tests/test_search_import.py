from fastapi.testclient import TestClient

from tests.conftest import login


def test_global_search_finds_seed_account(client: TestClient) -> None:
    headers = login(client)
    response = client.get("/api/v1/search", headers=headers, params={"q": "Meridian"})
    assert response.status_code == 200
    titles = [hit["title"] for hit in response.json()["data"]["hits"]]
    assert any("Meridian" in title for title in titles)


def test_import_preview_and_commit(client: TestClient) -> None:
    headers = login(client)
    csv_text = "name,industry\nAtlas Harbor,retail\n"
    preview = client.post(
        "/api/v1/imports/preview",
        headers=headers,
        json={"entity": "accounts", "csv_text": csv_text},
    )
    assert preview.status_code == 200
    assert preview.json()["data"]["count"] == 1
    commit = client.post(
        "/api/v1/imports/commit",
        headers=headers,
        json={"entity": "accounts", "rows": [{"name": "Atlas Harbor", "industry": "retail"}]},
    )
    assert commit.status_code == 200
    assert commit.json()["data"]["created"] == 1


def test_account_context_and_meeting_prep(client: TestClient) -> None:
    headers = login(client)
    accounts = client.get("/api/v1/accounts", headers=headers).json()["data"]
    account_id = accounts[0]["id"]
    context = client.get(f"/api/v1/accounts/{account_id}/context", headers=headers)
    assert context.status_code == 200
    assert context.json()["data"]["account"]["id"] == account_id
    prep = client.post(f"/api/v1/ai/meeting-prep/accounts/{account_id}", headers=headers)
    assert prep.status_code == 200
    assert prep.json()["data"]["brief"]


def test_command_overview(client: TestClient) -> None:
    headers = login(client)
    response = client.get("/api/v1/command-center/overview", headers=headers)
    assert response.status_code == 200
    body = response.json()["data"]
    assert "kpis" in body
    assert "pipeline_by_stage" in body
