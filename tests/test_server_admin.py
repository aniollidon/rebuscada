"""
Tests d'integració per al servidor d'administració (server_admin.py).

Cobreix:
- Autenticació (sense token, amb token correcte/incorrecte)
- GET /api/rankings (llistat de fitxers)
- GET /api/rankings/{filename} (lectura paginada)
- POST /api/rankings/{filename} (actualització de fragment)
- POST /api/validations/{filename}
- POST /api/favorites/{filename}
- POST /api/difficulties/{filename}
- GET /api/games i POST /api/save-games
- POST /api/auth
- GET /api/stats/overview
"""

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from httpx import AsyncClient, ASGITransport

from tests.conftest import MOCK_RANKING, MOCK_GAMES, MOCK_DATE


@pytest.fixture
def admin_app(test_data_dir, mock_env):
    """Crea una instància neta de l'aplicació FastAPI del servidor d'administració."""
    import importlib

    data_dir = test_data_dir / "data"

    # Crear fitxers addicionals que l'admin necessita
    validations_path = data_dir / "validacions.json"
    if not validations_path.exists():
        with open(validations_path, "w", encoding="utf-8") as f:
            json.dump({}, f)

    favorites_path = data_dir / "preferits.json"
    if not favorites_path.exists():
        with open(favorites_path, "w", encoding="utf-8") as f:
            json.dump({}, f)

    difficulties_path = data_dir / "dificultats.json"
    if not difficulties_path.exists():
        with open(difficulties_path, "w", encoding="utf-8") as f:
            json.dump({}, f)

    # Patch stats DB
    import stats as game_stats
    game_stats.DB_PATH = str(data_dir / "stats.db")
    game_stats.init_db()

    # Mock de fast_ai per evitar dependències pesades (openai, etc.)
    from unittest.mock import MagicMock
    sys.modules.setdefault("fast_ai", MagicMock())

    # Importar i reconfigurar server_admin
    import server_admin
    importlib.reload(server_admin)

    # Reconfigurar paths
    server_admin.WORDS_DIR = data_dir / "words"
    server_admin.VALIDATIONS_PATH = validations_path
    server_admin.FAVORITES_PATH = favorites_path
    server_admin.DIFFICULTIES_PATH = difficulties_path
    server_admin.ADMIN_PASSWORD = "test-password"
    server_admin.ADMIN_SHARED_SECRET = "test-secret"

    yield server_admin.app


@pytest.fixture
async def admin_client(admin_app):
    """Client HTTP asíncron per a l'admin."""
    transport = ASGITransport(app=admin_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


AUTH_HEADER = {"x-admin-token": "test-password"}
BAD_AUTH_HEADER = {"x-admin-token": "wrong-password"}


# ===========================================================================
# Tests d'autenticació
# ===========================================================================

@pytest.mark.asyncio
async def test_auth_correcta(admin_client):
    """Autenticació amb contrasenya correcta ha de retornar ok."""
    resp = await admin_client.post("/api/auth", json={"password": "test-password"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True


@pytest.mark.asyncio
async def test_auth_incorrecta(admin_client):
    """Autenticació amb contrasenya incorrecta ha de retornar 401."""
    resp = await admin_client.post("/api/auth", json={"password": "wrong"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_endpoint_sense_token(admin_client):
    """Accedir a un endpoint protegit sense token ha de retornar 401."""
    resp = await admin_client.get("/api/rankings")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_endpoint_amb_token_incorrecte(admin_client):
    """Accedir amb token incorrecte ha de retornar 401."""
    resp = await admin_client.get("/api/rankings", headers=BAD_AUTH_HEADER)
    assert resp.status_code == 401


# ===========================================================================
# Tests de /api/rankings
# ===========================================================================

@pytest.mark.asyncio
async def test_llistar_rankings(admin_client):
    """Llistar rànquings ha de retornar fitxers .json de data/words/."""
    resp = await admin_client.get("/api/rankings", headers=AUTH_HEADER)
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert "estrella.json" in data


@pytest.mark.asyncio
async def test_llegir_ranking(admin_client):
    """Lectura paginada d'un rànquing ha de retornar paraules ordenades."""
    resp = await admin_client.get(
        "/api/rankings/estrella.json",
        params={"offset": 0, "limit": 5},
        headers=AUTH_HEADER,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == len(MOCK_RANKING)
    assert len(data["words"]) == 5
    # Primera paraula ha de ser posició 0
    assert data["words"][0]["pos"] == 0
    assert data["words"][0]["word"] == "estrella"


@pytest.mark.asyncio
async def test_llegir_ranking_no_existent(admin_client):
    """Lectura d'un rànquing inexistent ha de retornar 404."""
    resp = await admin_client.get(
        "/api/rankings/noexisteix.json",
        headers=AUTH_HEADER,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_actualitzar_fragment_ranking(admin_client, test_data_dir):
    """Actualitzar un fragment del rànquing ha de modificar les paraules."""
    # El fragment actualitza les posicions 1-2 amb noves paraules
    resp = await admin_client.post(
        "/api/rankings/estrella.json",
        json={
            "fragment": {"llum": 0, "cel": 1},
            "offset": 1,
        },
        headers=AUTH_HEADER,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True

    # Verificar que s'ha actualitzat
    resp2 = await admin_client.get(
        "/api/rankings/estrella.json",
        params={"offset": 1, "limit": 2},
        headers=AUTH_HEADER,
    )
    assert resp2.status_code == 200
    words = resp2.json()["words"]
    word_names = [w["word"] for w in words]
    assert "llum" in word_names
    assert "cel" in word_names


# ===========================================================================
# Tests de /api/validations
# ===========================================================================

@pytest.mark.asyncio
async def test_set_validation(admin_client):
    """Marcar un fitxer com a validat."""
    resp = await admin_client.post(
        "/api/validations/estrella.json",
        json={"validated": "validated"},
        headers=AUTH_HEADER,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["validated"] == "validated"

    # Verificar que apareix a la llista
    resp2 = await admin_client.get("/api/validations", headers=AUTH_HEADER)
    assert resp2.status_code == 200
    vals = resp2.json()
    assert vals.get("estrella.json") == "validated"


@pytest.mark.asyncio
async def test_set_validation_approved(admin_client):
    """Marcar un fitxer com a aprovat."""
    resp = await admin_client.post(
        "/api/validations/estrella.json",
        json={"validated": "approved"},
        headers=AUTH_HEADER,
    )
    assert resp.status_code == 200
    assert resp.json()["validated"] == "approved"


@pytest.mark.asyncio
async def test_remove_validation(admin_client):
    """Treure la validació d'un fitxer."""
    # Primer validar
    await admin_client.post(
        "/api/validations/estrella.json",
        json={"validated": "validated"},
        headers=AUTH_HEADER,
    )
    # Després treure
    resp = await admin_client.post(
        "/api/validations/estrella.json",
        json={"validated": ""},
        headers=AUTH_HEADER,
    )
    assert resp.status_code == 200

    # Verificar que s'ha tret
    resp2 = await admin_client.get("/api/validations", headers=AUTH_HEADER)
    vals = resp2.json()
    assert "estrella.json" not in vals


# ===========================================================================
# Tests de /api/favorites
# ===========================================================================

@pytest.mark.asyncio
async def test_set_favorite(admin_client):
    """Marcar un fitxer com a preferit."""
    resp = await admin_client.post(
        "/api/favorites/estrella.json",
        json={"favorite": True},
        headers=AUTH_HEADER,
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    resp2 = await admin_client.get("/api/favorites", headers=AUTH_HEADER)
    favs = resp2.json()
    assert favs.get("estrella.json") is True


@pytest.mark.asyncio
async def test_remove_favorite(admin_client):
    """Treure un fitxer dels preferits."""
    await admin_client.post(
        "/api/favorites/estrella.json",
        json={"favorite": True},
        headers=AUTH_HEADER,
    )
    resp = await admin_client.post(
        "/api/favorites/estrella.json",
        json={"favorite": False},
        headers=AUTH_HEADER,
    )
    assert resp.status_code == 200

    resp2 = await admin_client.get("/api/favorites", headers=AUTH_HEADER)
    favs = resp2.json()
    assert "estrella.json" not in favs


# ===========================================================================
# Tests de /api/difficulties
# ===========================================================================

@pytest.mark.asyncio
async def test_set_difficulty(admin_client):
    """Assignar dificultat a un fitxer."""
    resp = await admin_client.post(
        "/api/difficulties/estrella.json",
        json={"difficulty": "facil"},
        headers=AUTH_HEADER,
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    resp2 = await admin_client.get("/api/difficulties", headers=AUTH_HEADER)
    diffs = resp2.json()
    assert diffs.get("estrella.json") == "facil"


# ===========================================================================
# Tests de /api/games i /api/save-games
# ===========================================================================

@pytest.mark.asyncio
async def test_get_games(admin_client):
    """Obtenir el calendari de jocs."""
    resp = await admin_client.get("/api/games", headers=AUTH_HEADER)
    assert resp.status_code == 200
    data = resp.json()
    assert "games" in data
    assert isinstance(data["games"], list)


@pytest.mark.asyncio
async def test_save_games(admin_client, test_data_dir):
    """Desar un nou calendari de jocs."""
    new_games = [
        {"id": 1, "name": "estrella", "dies": 1},
        {"id": 2, "name": "casa", "dies": 7},
    ]
    resp = await admin_client.post(
        "/api/save-games",
        json={"games": new_games},
        headers=AUTH_HEADER,
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


# ===========================================================================
# Tests de /api/stats/overview
# ===========================================================================

@pytest.mark.asyncio
async def test_stats_overview(admin_client):
    """Obtenir estadístiques generals."""
    resp = await admin_client.get("/api/stats/overview", headers=AUTH_HEADER)
    assert resp.status_code == 200
    data = resp.json()
    assert "total_visits" in data
    assert "total_players" in data
    assert "total_completions" in data
