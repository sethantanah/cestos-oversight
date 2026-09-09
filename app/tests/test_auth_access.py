from app.tests.conftest import login


async def test_access_requires_login_and_returns_scoped_permissions(client, identities):
    assert (await client.get("/api/v1/auth/access")).status_code == 401
    for key in ("admin", "denied", "other"):
        user = identities[key]
        tokens = await login(client, user)
        response = await client.get("/api/v1/auth/access", headers={"Authorization": "Bearer " + tokens["access_token"]})
        assert response.status_code == 200
        data = response.json()
        assert data["is_superuser"] is False
        if key == "denied":
            assert data["roles"] == [] and data["permissions"] == []
        else:
            expected = {p.code for r in user.roles for p in r.permissions}
            assert set(data["permissions"]) == expected
        assert "password" not in response.text and "token" not in data
