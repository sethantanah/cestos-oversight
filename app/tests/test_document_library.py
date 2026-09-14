import uuid

from sqlalchemy import select

from app.models import Employee, User
from app.models.document_library import LibraryDocument as D
from app.tests.conftest import login
from app.tests.test_operational import make_employee, superuser_headers


async def test_document_privacy_sources_search_and_super_private(
    client, identities, session_factory, monkeypatch
):
    from app.services import document_index

    monkeypatch.setattr(document_index, "search_vectors", lambda documents, query: {})
    admin = await superuser_headers(client, identities["admin"], session_factory)
    owner = {
        "Authorization": "Bearer " + (await login(client, identities["denied"]))["access_token"]
    }
    other = await superuser_headers(client, identities["other"], session_factory)
    response = await client.post(
        "/api/v1/documents",
        headers=owner,
        data={"title": "Quartz plan", "tags": "mining, planning", "category": "Operations"},
        files={"file": ("quartz.md", b"Quartz drilling schedule and progress.", "text/markdown")},
    )
    assert response.status_code == 201, response.text
    row = response.json()
    root = "/api/v1/documents/" + row["id"]
    assert row["visibility"] == "PRIVATE"
    assert (await client.get(root + "/download", headers=owner)).content.startswith(b"Quartz")
    assert (await client.get(root + "/download", headers=other)).status_code == 404
    assert (await client.get("/api/v1/documents?view=all&q=Quartz", headers=other)).json()[
        "total"
    ] == 0
    assert (await client.get("/api/v1/documents?view=for-you", headers=owner)).json()["total"] == 1
    assert (
        await client.patch(root, headers=owner, json={"visibility": "SUPER_PRIVATE"})
    ).status_code == 403
    assert (
        await client.patch(root, headers=owner, json={"visibility": "PUBLIC"})
    ).status_code == 200
    assert (
        await client.get("/api/v1/documents?view=all&q=Quartz&tag=mining", headers=admin)
    ).json()["total"] == 1
    assert (await client.get(root + "/download", headers=other)).status_code == 404
    assert (
        await client.patch(root, headers=admin, json={"visibility": "SUPER_PRIVATE"})
    ).status_code == 200
    assert (await client.get(root + "/download", headers=owner)).status_code == 404
    assert (await client.get(root + "/text", headers=owner)).status_code == 404
    assert (await client.post(root + "/reindex", headers=owner)).status_code == 404
    hidden = (await client.get("/api/v1/documents?view=all&q=Quartz", headers=owner)).json()
    assert hidden["total"] == 0 and "mining" not in hidden["tags"]
    assert (await client.get(root + "/download", headers=admin)).status_code == 200
    # A second superuser cannot bypass the administrator-specific lock.
    async with session_factory() as session:
        user = await session.get(User, identities["denied"].id)
        user.is_superuser = True
        await session.commit()
    assert (await client.get(root + "/download", headers=owner)).status_code == 404
    async with session_factory() as session:
        user = await session.get(User, identities["denied"].id)
        user.is_superuser = False
        await session.commit()
    employee = await make_employee(client, admin, first_name="Document owner")
    async with session_factory() as session:
        person = await session.get(Employee, uuid.UUID(employee["id"]))
        person.user_id = identities["denied"].id
        await session.commit()
    response = await client.post(
        "/api/v1/employees/" + employee["id"] + "/documents/upload",
        headers=admin,
        data={"title": "Training evidence", "document_type": "OTHER"},
        files={"file": ("training.txt", b"Completed drill safety training.", "text/plain")},
    )
    assert response.status_code == 201, response.text
    profile_doc = response.json()
    personal = (await client.get("/api/v1/documents?view=for-you", headers=owner)).json()["items"]
    mirrored = next(d for d in personal if d["source_id"] == profile_doc["id"])
    assert mirrored["owner_id"] == str(identities["admin"].id)
    assert (
        await client.get("/api/v1/documents/" + mirrored["id"] + "/download", headers=owner)
    ).status_code == 200
    assert (
        await client.patch(
            "/api/v1/documents/" + mirrored["id"],
            headers=admin,
            json={"visibility": "SUPER_PRIVATE"},
        )
    ).status_code == 200
    assert (
        await client.get("/api/v1/documents/" + mirrored["id"] + "/download", headers=owner)
    ).status_code == 404
    # Grant broad source permissions and ensure the original route is still protected.
    async with session_factory() as session:
        user = await session.get(User, identities["denied"].id)
        user.is_superuser = True
        await session.commit()
    original = (
        "/api/v1/employees/" + employee["id"] + "/documents/" + profile_doc["id"] + "/download"
    )
    assert (await client.get(original, headers=owner)).status_code == 404
    async with session_factory() as session:
        registered = (
            await session.scalars(select(D).where(D.source_id == uuid.UUID(profile_doc["id"])))
        ).all()
        assert len(registered) == 1


def test_real_faiss_persistence_and_extraction(tmp_path, monkeypatch):
    from types import SimpleNamespace

    import numpy as np

    from app.services import document_index as index

    monkeypatch.setattr(index, "INDEX_ROOT", tmp_path / "indexes")

    def embed(texts, query=False):
        return np.array(
            [[1.0, 0.0] if "drill" in text.lower() else [0.0, 1.0] for text in texts],
            dtype="float32",
        )

    monkeypatch.setattr(index, "embeddings", embed)
    path = tmp_path / "report.txt"
    path.write_text("Drilling reached 240 meters at the North site.")
    identifier = uuid.uuid4()
    result = index.build_index(path, path.name, identifier, uuid.uuid4())
    assert result["index_status"] == "READY"
    doc = SimpleNamespace(id=identifier, **result)
    hit = index.search_vectors([doc], "drilling meters")[identifier]
    assert hit[0] == 1.0 and "240 meters" in hit[1]["text"]
    # A query with no authorized documents cannot retrieve any vector or text.
    assert index.search_vectors([], "drilling") == {}
    binary = tmp_path / "archive.bin"
    binary.write_bytes(b"\x00\xff\x00\x01")
    unsupported = index.build_index(binary, binary.name, uuid.uuid4(), uuid.uuid4())
    assert unsupported["index_status"] == "UNSUPPORTED"
