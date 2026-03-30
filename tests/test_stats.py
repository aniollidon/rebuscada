"""
Tests del mòdul d'estadístiques (stats.py).

Cobreix:
- Inicialització de la BD
- record_visit() amb deduplicació
- record_guess() amb completació automàtica
- record_hint()
- record_surrender()
- get_overview_stats()
- get_daily_stats()
- get_per_game_stats()
- get_words_played_for_game()
"""

import pytest

# ===========================================================================
# Tests d'enregistrament
# ===========================================================================

class TestRecordVisit:
    def test_registra_visita(self, stats_db):
        """record_visit ha de crear un registre."""
        stats_db.record_visit("session-1", "estrella", 1)
        stats = stats_db.get_overview_stats()
        assert stats["total_visits"] >= 1

    def test_deduplicacio_visita(self, stats_db):
        """Múltiples visites de la mateixa sessió el mateix dia compten com una."""
        stats_db.record_visit("session-1", "estrella", 1)
        stats_db.record_visit("session-1", "estrella", 1)
        stats_db.record_visit("session-1", "estrella", 1)
        stats = stats_db.get_overview_stats()
        assert stats["total_visits"] == 1

    def test_visites_sessions_diferents(self, stats_db):
        """Visites de sessions diferents compten separadament."""
        stats_db.record_visit("session-1", "estrella", 1)
        stats_db.record_visit("session-2", "estrella", 1)
        stats = stats_db.get_overview_stats()
        assert stats["total_visits"] == 2

    def test_visita_sense_rebuscada(self, stats_db):
        """Pot registrar visita sense paraula rebuscada."""
        stats_db.record_visit("session-1")
        stats = stats_db.get_overview_stats()
        assert stats["total_visits"] >= 1


class TestRecordGuess:
    def test_registra_intent(self, stats_db):
        """record_guess ha de crear un registre d'intent."""
        stats_db.record_guess("session-1", "estrella", "cel", "cel", 1, False, 1)
        stats = stats_db.get_overview_stats()
        assert stats["total_players"] >= 1

    def test_intent_correcte_genera_completacio(self, stats_db):
        """Un intent correcte ha de generar automàticament una completació."""
        stats_db.record_guess("session-1", "estrella", "cel", "cel", 1, False, 1)
        stats_db.record_guess("session-1", "estrella", "estrella", "estrella", 0, True, 1)
        stats = stats_db.get_overview_stats()
        assert stats["total_completions"] == 1

    def test_completacio_compta_intents(self, stats_db):
        """La completació ha de registrar el nombre d'intents."""
        stats_db.record_guess("s1", "estrella", "cel", "cel", 1, False, 1)
        stats_db.record_guess("s1", "estrella", "sol", "sol", 3, False, 1)
        stats_db.record_guess("s1", "estrella", "estrella", "estrella", 0, True, 1)

        with stats_db.get_db() as conn:
            row = conn.execute(
                "SELECT num_intents FROM completions WHERE session_id = ? AND rebuscada = ?",
                ("s1", "estrella")
            ).fetchone()
        # 3 intents (cel, sol, estrella)
        assert row["num_intents"] == 3


class TestRecordHint:
    def test_registra_pista(self, stats_db):
        """record_hint ha de crear un registre de pista."""
        stats_db.record_hint("session-1", "estrella", "llum", 2, 1)
        stats = stats_db.get_overview_stats()
        assert stats["total_hints"] >= 1


class TestRecordSurrender:
    def test_registra_rendicio(self, stats_db):
        """record_surrender ha de crear un registre de rendició."""
        stats_db.record_surrender("session-1", "estrella", 1)
        stats = stats_db.get_overview_stats()
        assert stats["total_surrenders"] >= 1


# ===========================================================================
# Tests de consulta
# ===========================================================================

class TestGetOverviewStats:
    def test_overview_buit(self, stats_db):
        """Overview amb BD buida ha de retornar zeros."""
        stats = stats_db.get_overview_stats()
        assert stats["total_visits"] == 0
        assert stats["total_players"] == 0
        assert stats["total_completions"] == 0
        assert stats["total_surrenders"] == 0
        assert stats["total_hints"] == 0

    def test_overview_amb_dades(self, stats_db):
        """Overview amb dades ha de retornar valors coherents."""
        stats_db.record_visit("s1", "estrella", 1)
        stats_db.record_visit("s2", "estrella", 1)
        stats_db.record_guess("s1", "estrella", "cel", "cel", 1, False, 1)
        stats_db.record_guess("s1", "estrella", "estrella", "estrella", 0, True, 1)
        stats_db.record_hint("s2", "estrella", "llum", 2, 1)
        stats_db.record_surrender("s2", "estrella", 1)

        stats = stats_db.get_overview_stats()
        assert stats["total_visits"] == 2
        assert stats["total_players"] >= 1
        assert stats["total_completions"] == 1
        assert stats["total_surrenders"] == 1
        assert stats["total_hints"] == 1


class TestGetDailyStats:
    def test_daily_stats_buit(self, stats_db):
        """Daily stats amb BD buida retorna llista buida."""
        stats = stats_db.get_daily_stats(30)
        assert isinstance(stats, list)
        assert len(stats) == 0

    def test_daily_stats_amb_dades(self, stats_db):
        """Daily stats amb dades retorna registres."""
        stats_db.record_visit("s1", "estrella", 1)
        stats_db.record_guess("s1", "estrella", "cel", "cel", 1, False, 1)

        stats = stats_db.get_daily_stats(30)
        assert len(stats) >= 1
        assert "data" in stats[0]
        assert "visits" in stats[0]
        assert "guesses" in stats[0]


class TestGetPerGameStats:
    def test_per_game_stats(self, stats_db):
        """Per-game stats ha de agrupar per rebuscada."""
        stats_db.record_guess("s1", "estrella", "cel", "cel", 1, False, 1)
        stats_db.record_guess("s1", "estrella", "estrella", "estrella", 0, True, 1)

        stats = stats_db.get_per_game_stats()
        assert isinstance(stats, list)
        assert len(stats) >= 1
        game = stats[0]
        assert game["rebuscada"] == "estrella"
        assert game["jugadors"] >= 1
        assert game["total_intents"] >= 2


class TestGetWordsPlayed:
    def test_words_played(self, stats_db):
        """Words played ha de retornar les paraules més jugades."""
        stats_db.record_guess("s1", "estrella", "cel", "cel", 1, False, 1)
        stats_db.record_guess("s2", "estrella", "cel", "cel", 1, False, 1)
        stats_db.record_guess("s1", "estrella", "sol", "sol", 3, False, 1)

        words = stats_db.get_words_played_for_game("estrella")
        assert isinstance(words, list)
        assert len(words) >= 2
        # "cel" ha de ser la més jugada
        assert words[0]["paraula"] == "cel"
        assert words[0]["vegades"] == 2
