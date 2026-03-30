"""
Tests d'integració per al servidor de joc (server.py).

Cobreix els endpoints vitals:
- POST /guess (paraula vàlida, invàlida, flexió, fora de rànquing)
- POST /pista
- POST /whynot
- POST /rendirse
- GET /ranking
- GET /paraula-dia
- GET /public-games
- GET /version
- POST /visit
"""

import json
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from httpx import AsyncClient, ASGITransport

from tests.conftest import MOCK_RANKING, MOCK_DICCIONARI_DATA, MOCK_GAMES, MOCK_DATE


@pytest.fixture
def server_app(test_data_dir, mock_env):
    """Crea una instància neta de l'aplicació FastAPI del servidor de joc."""
    import importlib
    data_dir = test_data_dir / "data"

    # Patch el path de dades abans d'importar el mòdul
    patches = [
        patch("stats.DB_PATH", str(data_dir / "stats.db")),
    ]
    for p in patches:
        p.start()

    # Reimportar stats per agafar el path correcte
    import stats as game_stats
    game_stats.DB_PATH = str(data_dir / "stats.db")
    game_stats.init_db()

    # Importar server i reconfigurar
    import server
    importlib.reload(server)

    # Reconfigurar el mòdul amb les dades de test
    from diccionari import Diccionari
    server.dicc = Diccionari.load(str(data_dir / "diccionari.json"))
    server.dicc_full = None  # No necessitem diccionari complet per als tests bàsics
    server.DEFAULT_REBUSCADA = "estrella"
    server.ALLOWED_ORIGINS = ["http://localhost:3000"]
    server.ADMIN_SHARED_SECRET = "test-secret"
    server.exclusions_set = set()
    server.competitions = {}
    server.competition_connections = {}

    # Netejar cache LRU
    server.carregar_ranking.cache_clear()

    # Patch les funcions que llegeixen del disc per usar dades de test
    original_carregar = server.carregar_ranking.__wrapped__

    def mock_carregar_ranking(rebuscada: str):
        words_file = data_dir / "words" / f"{rebuscada}.json"
        if not words_file.exists():
            raise Exception(f"No s'ha trobat el fitxer de rànquing per la paraula '{rebuscada}'")
        with open(words_file, "r", encoding="utf-8") as f:
            ranking = json.load(f)
        if not ranking:
            raise Exception(f"El fitxer de rànquing per la paraula '{rebuscada}' està buit.")
        total = len(ranking)
        objectiu = min(ranking, key=lambda k: ranking[k])
        return ranking, total, objectiu

    server.carregar_ranking = mock_carregar_ranking

    # Patch obtenir_start_date i validar_joc_disponible per usar dades de test
    def mock_obtenir_start_date():
        date_path = data_dir / "date.json"
        if date_path.exists():
            with open(date_path, encoding="utf-8") as f:
                return json.load(f).get("startDate", "01-01-2025")
        return "01-01-2025"

    server.obtenir_start_date = mock_obtenir_start_date

    def mock_validar_joc(rebuscada: str):
        # En tests, no validem disponibilitat
        pass

    server.validar_joc_disponible = mock_validar_joc

    def mock_obtenir_game_id(rebuscada: str):
        games_path = data_dir / "games.json"
        if games_path.exists():
            with open(games_path, encoding="utf-8") as f:
                data = json.load(f)
            for game in data.get("games", []):
                if game.get("name", "").lower() == rebuscada.lower():
                    return game.get("id")
        return None

    server.obtenir_game_id = mock_obtenir_game_id

    yield server.app

    for p in patches:
        p.stop()


@pytest.fixture
async def client(server_app):
    """Client HTTP asíncron per fer peticions al servidor de test."""
    transport = ASGITransport(app=server_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ===========================================================================
# Tests de GET /version
# ===========================================================================

@pytest.mark.asyncio
async def test_version(client):
    resp = await client.get("/version")
    assert resp.status_code == 200
    data = resp.json()
    assert "version" in data


# ===========================================================================
# Tests de GET / (root)
# ===========================================================================

@pytest.mark.asyncio
async def test_root(client):
    resp = await client.get("/")
    assert resp.status_code == 200
    data = resp.json()
    assert "message" in data


# ===========================================================================
# Tests de POST /guess
# ===========================================================================

@pytest.mark.asyncio
async def test_guess_paraula_correcta(client):
    """Endevinar la paraula objectiu ha de retornar posició 0 i es_correcta=True."""
    resp = await client.post("/guess", json={
        "paraula": "estrella",
        "rebuscada": "estrella",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["es_correcta"] is True
    assert data["posicio"] == 0
    assert data["paraula"] == "estrella"


@pytest.mark.asyncio
async def test_guess_paraula_valida_no_correcta(client):
    """Una paraula vàlida que no és l'objectiu retorna la seva posició."""
    resp = await client.post("/guess", json={
        "paraula": "cel",
        "rebuscada": "estrella",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["es_correcta"] is False
    assert data["posicio"] == 1  # "cel" és posició 1 al ranking mock
    assert data["total_paraules"] == len(MOCK_RANKING)


@pytest.mark.asyncio
async def test_guess_flexio(client):
    """Una flexió ha de retornar la forma canònica i la posició del lema."""
    resp = await client.post("/guess", json={
        "paraula": "estrelles",
        "rebuscada": "estrella",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["es_correcta"] is True
    assert data["forma_canonica"] == "estrella"


@pytest.mark.asyncio
async def test_guess_paraula_invalida(client):
    """Una paraula que no existeix al diccionari ha de retornar 400."""
    resp = await client.post("/guess", json={
        "paraula": "xyzzy",
        "rebuscada": "estrella",
    })
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_guess_paraula_fora_ranking(client):
    """Una paraula vàlida al diccionari però fora del rànquing retorna 400."""
    resp = await client.post("/guess", json={
        "paraula": "casa",
        "rebuscada": "estrella",
    })
    assert resp.status_code == 400
    data = resp.json()
    assert "no es troba" in data["detail"].lower() or "llistat" in data["detail"].lower()


@pytest.mark.asyncio
async def test_guess_session_id_header(client):
    """El header X-Session-Id s'utilitza correctament."""
    resp = await client.post(
        "/guess",
        json={"paraula": "cel", "rebuscada": "estrella"},
        headers={"X-Session-Id": "test-session-123"},
    )
    assert resp.status_code == 200


# ===========================================================================
# Tests de POST /pista
# ===========================================================================

@pytest.mark.asyncio
async def test_pista_sense_intents(client):
    """Demanar pista sense intents previs ha de retornar una paraula del rànquing."""
    resp = await client.post("/pista", json={
        "intents": [],
        "rebuscada": "estrella",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "paraula" in data
    assert "posicio" in data
    assert data["paraula"] in MOCK_RANKING
    assert data["paraula"] != "estrella"  # No ha de revelar la resposta


@pytest.mark.asyncio
async def test_pista_amb_intents(client):
    """Demanar pista amb intents previs ha de retornar una paraula no provada."""
    resp = await client.post("/pista", json={
        "intents": [
            {"paraula": "cel", "forma_canonica": "cel", "posicio": 1},
            {"paraula": "sol", "forma_canonica": "sol", "posicio": 3},
        ],
        "rebuscada": "estrella",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["paraula"] not in ("cel", "sol", "estrella")
    assert data["paraula"] in MOCK_RANKING


# ===========================================================================
# Tests de POST /whynot
# ===========================================================================

@pytest.mark.asyncio
async def test_whynot_paraula_valida_retorna_error(client):
    """Si la paraula és vàlida, /whynot ha de retornar 400."""
    resp = await client.post("/whynot", json={
        "paraula": "cel",
        "rebuscada": "estrella",
    })
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_whynot_espais(client):
    """Una paraula amb espais ha de rebre explicació adequada."""
    resp = await client.post("/whynot", json={
        "paraula": "dos mots",
        "rebuscada": "estrella",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "espai" in data["raó"].lower()


@pytest.mark.asyncio
async def test_whynot_caracters_no_catalans(client):
    """Caràcters no catalans han de rebre explicació adequada."""
    resp = await client.post("/whynot", json={
        "paraula": "hello@world",
        "rebuscada": "estrella",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "caràcters" in data["raó"].lower()


# ===========================================================================
# Tests de POST /rendirse
# ===========================================================================

@pytest.mark.asyncio
async def test_rendirse(client):
    """Rendir-se ha de revelar la paraula objectiu."""
    resp = await client.post("/rendirse", json={
        "rebuscada": "estrella",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["paraula_correcta"] == "estrella"


# ===========================================================================
# Tests de GET /ranking
# ===========================================================================

@pytest.mark.asyncio
async def test_ranking(client):
    """Obtenir el rànquing ha de retornar paraules ordenades per posició."""
    resp = await client.get("/ranking", params={"rebuscada": "estrella", "limit": 5})
    assert resp.status_code == 200
    data = resp.json()
    assert data["rebuscada"] == "estrella"
    assert data["total_paraules"] == len(MOCK_RANKING)
    assert len(data["ranking"]) == 5
    # Verificar que estan ordenades
    posicions = [item["posicio"] for item in data["ranking"]]
    assert posicions == sorted(posicions)
    # La primera ha de ser la paraula objectiu
    assert data["ranking"][0]["paraula"] == "estrella"
    assert data["ranking"][0]["posicio"] == 0


@pytest.mark.asyncio
async def test_ranking_limit(client):
    """El paràmetre limit s'ha de respectar."""
    resp = await client.get("/ranking", params={"rebuscada": "estrella", "limit": 3})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["ranking"]) == 3


# ===========================================================================
# Tests de GET /paraula-dia
# ===========================================================================

@pytest.mark.asyncio
async def test_paraula_dia(client):
    """Ha de retornar informació del joc del dia."""
    resp = await client.get("/paraula-dia")
    assert resp.status_code == 200
    data = resp.json()
    assert "id" in data
    assert "name" in data
    assert "startDate" in data
    assert "today" in data


# ===========================================================================
# Tests de GET /public-games
# ===========================================================================

@pytest.mark.asyncio
async def test_public_games(client):
    """Ha de retornar la llista de jocs públics."""
    resp = await client.get("/public-games")
    assert resp.status_code == 200
    data = resp.json()
    assert "games" in data
    assert "currentGameId" in data
    assert isinstance(data["games"], list)


# ===========================================================================
# Tests de POST /visit
# ===========================================================================

@pytest.mark.asyncio
async def test_visit(client):
    """Registrar una visita ha de funcionar correctament."""
    resp = await client.post(
        "/visit",
        json={"rebuscada": "estrella", "game_id": 1},
        headers={"X-Session-Id": "test-session-visit"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True


# ===========================================================================
# Tests de POST /internal/cache/clear
# ===========================================================================

@pytest.mark.asyncio
async def test_cache_clear_sense_token(client):
    """Netejar cache sense token ha de retornar 401."""
    resp = await client.post("/internal/cache/clear")
    assert resp.status_code == 401


# ===========================================================================
# Tests de funcions auxiliars
# ===========================================================================

def test_is_catalan():
    """Verifica la validació de caràcters catalans."""
    import server
    assert server.is_catalan("hola") is True
    assert server.is_catalan("àèéíïòóúüç") is True
    assert server.is_catalan("l·l") is True
    assert server.is_catalan("para-sol") is True
    assert server.is_catalan("") is False
    assert server.is_catalan("hello@world") is False
    assert server.is_catalan("123") is False
    assert server.is_catalan("a" * 101) is False


def test_calcular_joc_actual():
    """Verifica el càlcul del joc actual basat en dies."""
    import server
    games = [
        {"id": 1, "name": "a", "dies": 1},
        {"id": 2, "name": "b", "dies": 1},
        {"id": 3, "name": "c", "dies": 7},
    ]
    assert server.calcular_joc_actual(games, 0) == 1  # Dia 0 → joc 1
    assert server.calcular_joc_actual(games, 1) == 2  # Dia 1 → joc 2
    assert server.calcular_joc_actual(games, 2) == 3  # Dia 2 → joc 3 (dura 7 dies)
    assert server.calcular_joc_actual(games, 8) == 3  # Dia 8 → encara joc 3
    assert server.calcular_joc_actual(games, 100) == 3  # Superat tot → últim joc
