"""
Tests del mòdul de diccionari (diccionari.py).

Cobreix:
- Càrrega i desament de diccionaris JSON
- normalitzar_paraula()
- obtenir_forma_canonica() (paraules directes, flexions, pronominals)
- Prioritat NC > VM
- Exclusions de formes i lemes
"""

import json
from pathlib import Path

import pytest

from diccionari import Diccionari
from tests.conftest import MOCK_DICCIONARI_DATA


@pytest.fixture
def dic():
    """Crea un Diccionari a partir de les dades mock."""
    return Diccionari(
        mapping_flexions_multi={k: set(v) for k, v in MOCK_DICCIONARI_DATA["mapping_flexions_multi"].items()},
        canoniques={k: set(v) for k, v in MOCK_DICCIONARI_DATA["canoniques"].items()},
        freq=MOCK_DICCIONARI_DATA["freq"],
        lema_categories={k: set(v) for k, v in MOCK_DICCIONARI_DATA["lema_categories"].items()},
    )


# ===========================================================================
# normalitzar_paraula
# ===========================================================================

class TestNormalitzarParaula:
    def test_minuscules(self):
        assert Diccionari.normalitzar_paraula("ESTRELLA") == "estrella"

    def test_espais(self):
        assert Diccionari.normalitzar_paraula("  cel  ") == "cel"

    def test_mixta(self):
        assert Diccionari.normalitzar_paraula("  Galàxia ") == "galàxia"


# ===========================================================================
# obtenir_forma_canonica
# ===========================================================================

class TestObtenirFormaCanonica:
    def test_paraula_directa(self, dic):
        """Una paraula que és el seu propi lema."""
        forma, es_flexio = dic.obtenir_forma_canonica("estrella")
        assert forma == "estrella"
        assert es_flexio is False

    def test_flexio(self, dic):
        """Una flexió ha de retornar el lema base."""
        forma, es_flexio = dic.obtenir_forma_canonica("estrelles")
        assert forma == "estrella"
        assert es_flexio is True

    def test_flexio_plural(self, dic):
        forma, es_flexio = dic.obtenir_forma_canonica("planetes")
        assert forma == "planeta"
        assert es_flexio is True

    def test_paraula_no_existent(self, dic):
        """Una paraula desconeguda retorna None."""
        forma, es_flexio = dic.obtenir_forma_canonica("xyznonexistent")
        assert forma is None
        assert es_flexio is False

    def test_majuscules(self, dic):
        """La cerca ha de normalitzar la paraula primer."""
        forma, es_flexio = dic.obtenir_forma_canonica("ESTRELLA")
        assert forma == "estrella"

    def test_verb_pronominal_se(self, dic):
        """Un verb pronominal acabat en -se ha de tornar el lema verb."""
        forma, es_flexio = dic.obtenir_forma_canonica("rentar-se")
        assert forma == "rentar"
        assert es_flexio is True

    def test_prioritat_nc_sobre_vm(self):
        """Quan una flexió mapa a múltiples lemes (nom i verb), prioritza NC."""
        dic = Diccionari(
            mapping_flexions_multi={
                "test": {"nom_lema", "verb_lema"},
            },
            canoniques={
                "nom_lema": {"test", "tests"},
                "verb_lema": {"test", "testant"},
            },
            freq={"nom_lema": 1000, "verb_lema": 2000},
            lema_categories={"nom_lema": {"NC"}, "verb_lema": {"VM"}},
        )
        forma, es_flexio = dic.obtenir_forma_canonica("test")
        # Malgrat que verb_lema té més freqüència, NC té prioritat
        assert forma == "nom_lema"
        assert es_flexio is True


# ===========================================================================
# load / save
# ===========================================================================

class TestLoadSave:
    def test_save_i_load(self, dic, tmp_path):
        """save() seguit de load() ha de retornar dades equivalents."""
        path = str(tmp_path / "dic.json")
        dic.save(path)
        dic2 = Diccionari.load(path)

        assert dic2.mapping_flexions_multi.keys() == dic.mapping_flexions_multi.keys()
        assert dic2.canoniques.keys() == dic.canoniques.keys()
        assert set(dic2.freq.keys()) == set(dic.freq.keys())

    def test_load_from_test_data(self, test_data_dir):
        """Carrega el diccionari mock creat per la fixture test_data_dir."""
        path = str(test_data_dir / "data" / "diccionari.json")
        dic = Diccionari.load(path)
        assert "estrella" in dic.mapping_flexions_multi
        assert "estrella" in dic.canoniques


# ===========================================================================
# Mètodes auxiliars
# ===========================================================================

class TestMetodesAuxiliars:
    def test_lema(self, dic):
        assert dic.lema("estrelles") == "estrella"

    def test_lemes(self, dic):
        assert "estrella" in dic.lemes("estrelles")

    def test_lema_paraula_desconeguda(self, dic):
        assert dic.lema("xyznonexistent") is None

    def test_categories_lema(self, dic):
        cats = dic.categories_lema("estrella")
        assert "NC" in cats

    def test_freq_lema(self, dic):
        assert dic.freq_lema("estrella") == 5000
        assert dic.freq_lema("xyznonexistent") == 0

    def test_totes_les_lemes(self, dic):
        lemes = dic.totes_les_lemes(freq_min=0)
        assert "estrella" in lemes
        assert "cel" in lemes

    def test_totes_les_lemes_filtre(self, dic):
        lemes = dic.totes_les_lemes(freq_min=10000)
        assert "nit" in lemes
        assert "fulgor" not in lemes  # freq=100

    def test_totes_les_flexions(self, dic):
        flexions = dic.totes_les_flexions("estrella")
        assert "estrella" in flexions
        assert "estrelles" in flexions

    def test_obtenir_paraula_aleatoria(self, dic):
        paraula = dic.obtenir_paraula_aleatoria(freq_min=0, seed=42)
        assert paraula in dic.canoniques


# ===========================================================================
# Exclusions
# ===========================================================================

class TestExclusions:
    def test_apply_exclusions_lemes(self, dic):
        """Excloure un lema l'ha d'eliminar de totes les estructures."""
        canoniques = {k: set(v) for k, v in dic.canoniques.items()}
        mapping = {k: set(v) for k, v in dic.mapping_flexions_multi.items()}
        cats = {k: set(v) for k, v in dic.lema_categories.items()}
        freq = dict(dic.freq)

        Diccionari._apply_exclusions_to_data(
            canoniques, mapping, cats, freq,
            forms_to_exclude=set(),
            lemmas_to_exclude={"gat"},
        )

        assert "gat" not in canoniques
        assert "gat" not in cats
        assert "gat" not in freq
        # "gats" ja no ha de mappejar a cap lema
        assert "gats" not in mapping

    def test_apply_exclusions_formes(self, dic):
        """Excloure una forma l'ha d'eliminar del mapping."""
        canoniques = {k: set(v) for k, v in dic.canoniques.items()}
        mapping = {k: set(v) for k, v in dic.mapping_flexions_multi.items()}
        cats = {k: set(v) for k, v in dic.lema_categories.items()}
        freq = dict(dic.freq)

        Diccionari._apply_exclusions_to_data(
            canoniques, mapping, cats, freq,
            forms_to_exclude={"estrelles"},
            lemmas_to_exclude=set(),
        )

        assert "estrelles" not in mapping
