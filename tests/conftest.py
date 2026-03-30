"""
Fixtures compartides per als tests de Rebuscada.

Proporciona:
- Dades de test (diccionari mock, rànquings mock, games.json mock)
- Clients de test per FastAPI (servidor de joc i admin)
- Base de dades d'estadístiques temporal
"""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Dades de test
# ---------------------------------------------------------------------------

MOCK_RANKING = {
    "estrella": 0,
    "cel": 1,
    "llum": 2,
    "sol": 3,
    "brillar": 4,
    "nit": 5,
    "constel·lació": 6,
    "galàxia": 7,
    "univers": 8,
    "planeta": 9,
    "lluna": 10,
    "telescopi": 11,
    "astronomia": 12,
    "fosc": 13,
    "claror": 14,
    "fulgor": 15,
    "resplandir": 16,
    "aurora": 17,
    "crepuscle": 18,
    "meteorit": 19,
}

MOCK_DICCIONARI_DATA = {
    "mapping_flexions_multi": {
        "estrella": ["estrella"],
        "estrelles": ["estrella"],
        "cel": ["cel"],
        "cels": ["cel"],
        "llum": ["llum"],
        "llums": ["llum"],
        "sol": ["sol"],
        "sols": ["sol"],
        "brillar": ["brillar"],
        "brilla": ["brillar"],
        "nit": ["nit"],
        "nits": ["nit"],
        "constel·lació": ["constel·lació"],
        "galàxia": ["galàxia"],
        "univers": ["univers"],
        "planeta": ["planeta"],
        "planetes": ["planeta"],
        "lluna": ["lluna"],
        "telescopi": ["telescopi"],
        "astronomia": ["astronomia"],
        "fosc": ["fosc"],
        "fosca": ["fosc"],
        "claror": ["claror"],
        "fulgor": ["fulgor"],
        "resplandir": ["resplandir"],
        "aurora": ["aurora"],
        "crepuscle": ["crepuscle"],
        "meteorit": ["meteorit"],
        "gat": ["gat"],
        "gats": ["gat"],
        "casa": ["casa"],
        "cases": ["casa"],
        "rentar-se": ["rentar"],   # verb pronominal
        "rentar": ["rentar"],
    },
    "canoniques": {
        "estrella": ["estrella", "estrelles"],
        "cel": ["cel", "cels"],
        "llum": ["llum", "llums"],
        "sol": ["sol", "sols"],
        "brillar": ["brillar", "brilla"],
        "nit": ["nit", "nits"],
        "constel·lació": ["constel·lació"],
        "galàxia": ["galàxia"],
        "univers": ["univers"],
        "planeta": ["planeta", "planetes"],
        "lluna": ["lluna"],
        "telescopi": ["telescopi"],
        "astronomia": ["astronomia"],
        "fosc": ["fosc", "fosca"],
        "claror": ["claror"],
        "fulgor": ["fulgor"],
        "resplandir": ["resplandir"],
        "aurora": ["aurora"],
        "crepuscle": ["crepuscle"],
        "meteorit": ["meteorit"],
        "gat": ["gat", "gats"],
        "casa": ["casa", "cases"],
        "rentar": ["rentar", "rentar-se"],
    },
    "lema_categories": {
        "estrella": ["NC"],
        "cel": ["NC"],
        "llum": ["NC"],
        "sol": ["NC"],
        "brillar": ["VM"],
        "nit": ["NC"],
        "constel·lació": ["NC"],
        "galàxia": ["NC"],
        "univers": ["NC"],
        "planeta": ["NC"],
        "lluna": ["NC"],
        "telescopi": ["NC"],
        "astronomia": ["NC"],
        "fosc": ["NC"],
        "claror": ["NC"],
        "fulgor": ["NC"],
        "resplandir": ["VM"],
        "aurora": ["NC"],
        "crepuscle": ["NC"],
        "meteorit": ["NC"],
        "gat": ["NC"],
        "casa": ["NC"],
        "rentar": ["VM"],
    },
    "freq": {
        "estrella": 5000,
        "cel": 8000,
        "llum": 7000,
        "sol": 9000,
        "brillar": 3000,
        "nit": 10000,
        "constel·lació": 500,
        "galàxia": 400,
        "univers": 2000,
        "planeta": 1500,
        "lluna": 3000,
        "telescopi": 200,
        "astronomia": 300,
        "fosc": 2500,
        "claror": 1000,
        "fulgor": 100,
        "resplandir": 150,
        "aurora": 800,
        "crepuscle": 600,
        "meteorit": 250,
        "gat": 4000,
        "casa": 15000,
        "rentar": 2000,
    },
}

MOCK_GAMES = {
    "games": [
        {"id": 1, "name": "estrella", "dies": 1},
        {"id": 2, "name": "casa", "dies": 1},
        {"id": 3, "name": "gat", "dies": 7},
    ],
    "startDate": "01-01-2025",
}

MOCK_DATE = {"startDate": "01-01-2025"}


@pytest.fixture
def test_data_dir(tmp_path):
    """Crea un directori temporal amb totes les dades de test necessàries."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    words_dir = data_dir / "words"
    words_dir.mkdir()

    # Rànquing d'estrella
    with open(words_dir / "estrella.json", "w", encoding="utf-8") as f:
        json.dump(MOCK_RANKING, f, ensure_ascii=False)

    # Diccionari reduït
    with open(data_dir / "diccionari.json", "w", encoding="utf-8") as f:
        json.dump(MOCK_DICCIONARI_DATA, f, ensure_ascii=False)

    # games.json
    with open(data_dir / "games.json", "w", encoding="utf-8") as f:
        json.dump(MOCK_GAMES, f, ensure_ascii=False)

    # date.json
    with open(data_dir / "date.json", "w", encoding="utf-8") as f:
        json.dump(MOCK_DATE, f, ensure_ascii=False)

    # exclusions.json (buit)
    with open(data_dir / "exclusions.json", "w", encoding="utf-8") as f:
        json.dump({"lemmas": [], "formes": []}, f)

    return tmp_path


@pytest.fixture
def mock_env(test_data_dir):
    """Configura variables d'entorn per als tests."""
    str(test_data_dir / "data")
    env_vars = {
        "DICCIONARI_PATH": str(test_data_dir / "data" / "diccionari.json"),
        "DEFAULT_REBUSCADA": "estrella",
        "ALLOWED_ORIGINS": "http://localhost:3000",
        "ADMIN_PASSWORD": "test-password",
        "ADMIN_SHARED_SECRET": "test-secret",
        "PORT": "8000",
        "ADMIN_PORT": "5001",
        "STATS_DB_PATH": str(test_data_dir / "data" / "stats.db"),
        "RANKING_CACHE_SIZE": "5",
        "COMPETITION_EXPIRY_DAYS": "2",
    }
    with patch.dict(os.environ, env_vars):
        yield env_vars


@pytest.fixture
def stats_db(test_data_dir):
    """Inicialitza una BD d'estadístiques temporal."""
    db_path = str(test_data_dir / "data" / "stats.db")
    with patch.dict(os.environ, {"STATS_DB_PATH": db_path}):
        # Reimportar per agafar el nou path
        import stats as game_stats
        # Forçar el nou path
        game_stats.DB_PATH = db_path
        game_stats.init_db()
        yield game_stats
        # El fitxer es neteja automàticament amb tmp_path
