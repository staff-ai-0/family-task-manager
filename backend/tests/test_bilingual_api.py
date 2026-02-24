import pytest
from httpx import AsyncClient
from unittest.mock import patch, AsyncMock
from app.models.user import User

@pytest.mark.asyncio
async def test_create_bilingual_template(client: AsyncClient, test_parent_user: User):
    """Test creating a task template with both English and Spanish content"""
    # Authenticate
    response = await client.post(
        "/api/auth/login",
        json={"email": test_parent_user.email, "password": "password123"},
    )
    assert response.status_code == 200
    token = response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Create template with Spanish content
    payload = {
        "title": "Clean Room",
        "description": "Clean your room",
        "title_es": "Limpiar Cuarto",
        "description_es": "Limpia tu cuarto",
        "points": 10,
        "interval_days": 1,
        "is_bonus": False
    }
    
    response = await client.post("/api/task-templates/", json=payload, headers=headers)
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Clean Room"
    assert data["title_es"] == "Limpiar Cuarto"
    assert data["description_es"] == "Limpia tu cuarto"

@pytest.mark.asyncio
async def test_translate_endpoint(client: AsyncClient, test_parent_user: User):
    """Test the translation endpoint with mocked service"""
    # Authenticate
    response = await client.post(
        "/api/auth/login",
        json={"email": test_parent_user.email, "password": "password123"},
    )
    token = response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Create template without Spanish
    payload = {
        "title": "Wash Dishes",
        "description": "Wash the dishes",
        "points": 10,
        "interval_days": 1,
        "is_bonus": False
    }
    create_res = await client.post("/api/task-templates/", json=payload, headers=headers)
    assert create_res.status_code == 201
    tmpl_id = create_res.json()["id"]

    # Mock translation service
    mock_return = {
        "title": "Lavar Platos",
        "description": "Lava los platos"
    }
    
    # We patch the method where it is IMPORTED in the route handler module, or the class itself
    # The route handler uses TranslationService.translate_template_fields
    with patch("app.services.translation_service.TranslationService.translate_template_fields", new_callable=AsyncMock) as mock_translate:
        mock_translate.return_value = mock_return
        
        # Call translate endpoint with empty JSON body to satisfy Pydantic
        res = await client.post(f"/api/task-templates/{tmpl_id}/translate", json={}, headers=headers)
        
        assert res.status_code == 200
        data = res.json()
        assert data["title"] == "Lavar Platos"
        assert data["description"] == "Lava los platos"
        
        # Verify the template was NOT updated in DB yet
        get_res = await client.get(f"/api/task-templates/{tmpl_id}", headers=headers)
        assert get_res.status_code == 200
        tmpl = get_res.json()
        assert tmpl["title_es"] is None
        
        # Now update the template with the translation
        update_payload = {
            "title_es": data["title"],
            "description_es": data["description"]
        }
        put_res = await client.put(f"/api/task-templates/{tmpl_id}", json=update_payload, headers=headers)
        assert put_res.status_code == 200
        
        # Verify it is now saved
        get_res = await client.get(f"/api/task-templates/{tmpl_id}", headers=headers)
        tmpl = get_res.json()
        assert tmpl["title_es"] == "Lavar Platos"
