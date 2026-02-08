"""
Mòdul d'estadístiques per Rebuscada.cat

Guarda estadístiques de joc en una base de dades SQLite:
- Visites (accés a la web)
- Jugadors actius (envien paraules vàlides)
- Jugadors recurrents (han jugat en jocs anteriors)
- Completacions de joc (amb quantes paraules)
- Pistes demanades per joc
- Paraules jugades per cada joc (per gràfics)
"""

import sqlite3
import os
import logging
from datetime import datetime, date
from pathlib import Path
from typing import Optional, Dict, List, Any
from contextlib import contextmanager

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("STATS_DB_PATH", "data/stats.db")


@contextmanager
def get_db():
    """Context manager per obtenir una connexió a la base de dades."""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Inicialitza la base de dades creant les taules necessàries."""
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)

    with get_db() as conn:
        conn.executescript("""
            -- Visites: cada accés únic per session_id i dia
            CREATE TABLE IF NOT EXISTS visits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                rebuscada TEXT,
                game_id INTEGER,
                data TEXT NOT NULL,
                timestamp TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_visits_data ON visits(data);
            CREATE INDEX IF NOT EXISTS idx_visits_session ON visits(session_id, data);
            CREATE INDEX IF NOT EXISTS idx_visits_rebuscada ON visits(rebuscada, data);

            -- Intents: cada paraula enviada (vàlida)
            CREATE TABLE IF NOT EXISTS guesses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                rebuscada TEXT NOT NULL,
                game_id INTEGER,
                paraula TEXT NOT NULL,
                forma_canonica TEXT,
                posicio INTEGER NOT NULL,
                es_correcta INTEGER NOT NULL DEFAULT 0,
                data TEXT NOT NULL,
                timestamp TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_guesses_data ON guesses(data);
            CREATE INDEX IF NOT EXISTS idx_guesses_session ON guesses(session_id);
            CREATE INDEX IF NOT EXISTS idx_guesses_rebuscada ON guesses(rebuscada, data);
            CREATE INDEX IF NOT EXISTS idx_guesses_session_rebuscada ON guesses(session_id, rebuscada);

            -- Pistes: cada pista demanada
            CREATE TABLE IF NOT EXISTS hints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                rebuscada TEXT NOT NULL,
                game_id INTEGER,
                paraula_pista TEXT NOT NULL,
                posicio INTEGER NOT NULL,
                data TEXT NOT NULL,
                timestamp TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_hints_data ON hints(data);
            CREATE INDEX IF NOT EXISTS idx_hints_rebuscada ON hints(rebuscada, data);

            -- Rendicions
            CREATE TABLE IF NOT EXISTS surrenders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                rebuscada TEXT NOT NULL,
                game_id INTEGER,
                data TEXT NOT NULL,
                timestamp TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_surrenders_rebuscada ON surrenders(rebuscada, data);

            -- Completacions de joc (quan un jugador encerta la paraula)
            CREATE TABLE IF NOT EXISTS completions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                rebuscada TEXT NOT NULL,
                game_id INTEGER,
                num_intents INTEGER NOT NULL,
                num_pistes INTEGER NOT NULL DEFAULT 0,
                data TEXT NOT NULL,
                timestamp TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_completions_rebuscada ON completions(rebuscada);
            CREATE INDEX IF NOT EXISTS idx_completions_data ON completions(data);
        """)
    logger.info(f"Stats DB initialized at {DB_PATH}")


# ==================== FUNCIONS D'ENREGISTRAMENT ====================

def record_visit(session_id: str, rebuscada: Optional[str] = None, game_id: Optional[int] = None):
    """Registra una visita (accés a la web). Deduplicat per session_id + dia."""
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")

    with get_db() as conn:
        # Comprovar si ja existeix una visita per aquesta sessió i dia
        existing = conn.execute(
            "SELECT id FROM visits WHERE session_id = ? AND data = ?",
            (session_id, today)
        ).fetchone()

        if not existing:
            conn.execute(
                "INSERT INTO visits (session_id, rebuscada, game_id, data, timestamp) VALUES (?, ?, ?, ?, ?)",
                (session_id, rebuscada, game_id, today, now.isoformat())
            )


def record_guess(session_id: str, rebuscada: str, paraula: str,
                 forma_canonica: Optional[str], posicio: int, es_correcta: bool,
                 game_id: Optional[int] = None):
    """Registra un intent vàlid."""
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")

    with get_db() as conn:
        conn.execute(
            """INSERT INTO guesses 
               (session_id, rebuscada, game_id, paraula, forma_canonica, posicio, es_correcta, data, timestamp) 
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (session_id, rebuscada, game_id, paraula, forma_canonica, posicio,
             1 if es_correcta else 0, today, now.isoformat())
        )

        # Si és correcta, registrar completació
        if es_correcta:
            # Comptar intents totals d'aquesta sessió per aquesta rebuscada
            num_intents = conn.execute(
                "SELECT COUNT(*) FROM guesses WHERE session_id = ? AND rebuscada = ?",
                (session_id, rebuscada)
            ).fetchone()[0]

            num_pistes = conn.execute(
                "SELECT COUNT(*) FROM hints WHERE session_id = ? AND rebuscada = ?",
                (session_id, rebuscada)
            ).fetchone()[0]

            conn.execute(
                """INSERT INTO completions 
                   (session_id, rebuscada, game_id, num_intents, num_pistes, data, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (session_id, rebuscada, game_id, num_intents, num_pistes, today, now.isoformat())
            )


def record_hint(session_id: str, rebuscada: str, paraula_pista: str, posicio: int,
                game_id: Optional[int] = None):
    """Registra una pista demanada."""
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")

    with get_db() as conn:
        conn.execute(
            """INSERT INTO hints 
               (session_id, rebuscada, game_id, paraula_pista, posicio, data, timestamp) 
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (session_id, rebuscada, game_id, paraula_pista, posicio, today, now.isoformat())
        )


def record_surrender(session_id: str, rebuscada: str, game_id: Optional[int] = None):
    """Registra una rendició."""
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")

    with get_db() as conn:
        conn.execute(
            """INSERT INTO surrenders 
               (session_id, rebuscada, game_id, data, timestamp) 
               VALUES (?, ?, ?, ?, ?)""",
            (session_id, rebuscada, game_id, today, now.isoformat())
        )


# ==================== FUNCIONS DE CONSULTA ====================

def get_overview_stats() -> Dict[str, Any]:
    """Retorna estadístiques generals (resum)."""
    with get_db() as conn:
        today = date.today().strftime("%Y-%m-%d")

        # Helper SQL: normalitza anon-* a un sol ID
        # NSID = Normalized Session ID
        NSID = "CASE WHEN session_id LIKE 'anon-%' THEN '__anon__' ELSE session_id END"

        # Visites totals (sessions úniques per dia)
        total_visits = conn.execute(
            f"SELECT COUNT(DISTINCT {NSID} || data) FROM visits"
        ).fetchone()[0]

        visits_today = conn.execute(
            f"SELECT COUNT(DISTINCT {NSID}) FROM visits WHERE data = ?",
            (today,)
        ).fetchone()[0]

        # Jugadors actius (sessions que han enviat almenys un guess)
        total_players = conn.execute(
            f"SELECT COUNT(DISTINCT {NSID}) FROM guesses"
        ).fetchone()[0]

        players_today = conn.execute(
            f"SELECT COUNT(DISTINCT {NSID}) FROM guesses WHERE data = ?",
            (today,)
        ).fetchone()[0]

        # Jugadors recurrents (han jugat a més d'una rebuscada diferent)
        returning_players = conn.execute(
            f"""SELECT COUNT(*) FROM (
                SELECT {NSID} as nsid FROM guesses 
                GROUP BY nsid 
                HAVING COUNT(DISTINCT rebuscada) > 1
            )"""
        ).fetchone()[0]

        # Completacions totals
        total_completions = conn.execute(
            "SELECT COUNT(*) FROM completions"
        ).fetchone()[0]

        completions_today = conn.execute(
            "SELECT COUNT(*) FROM completions WHERE data = ?",
            (today,)
        ).fetchone()[0]

        # Rendicions totals
        total_surrenders = conn.execute(
            "SELECT COUNT(*) FROM surrenders"
        ).fetchone()[0]

        # Mitjana d'intents per completar
        avg_intents = conn.execute(
            "SELECT AVG(num_intents) FROM completions"
        ).fetchone()[0]

        # Total pistes demanades
        total_hints = conn.execute(
            "SELECT COUNT(*) FROM hints"
        ).fetchone()[0]

        return {
            "total_visits": total_visits or 0,
            "visits_today": visits_today or 0,
            "total_players": total_players or 0,
            "players_today": players_today or 0,
            "returning_players": returning_players or 0,
            "total_completions": total_completions or 0,
            "completions_today": completions_today or 0,
            "total_surrenders": total_surrenders or 0,
            "avg_intents_per_completion": round(avg_intents, 1) if avg_intents else 0,
            "total_hints": total_hints or 0,
        }


def get_daily_stats(days: int = 30) -> List[Dict[str, Any]]:
    """Retorna estadístiques diàries dels últims N dies."""
    with get_db() as conn:
        rows = conn.execute("""
            SELECT 
                d.data,
                COALESCE(v.visits, 0) as visits,
                COALESCE(g.players, 0) as players,
                COALESCE(g.guesses, 0) as guesses,
                COALESCE(c.completions, 0) as completions,
                COALESCE(s.surrenders, 0) as surrenders,
                COALESCE(h.hints, 0) as hints
            FROM (
                SELECT DISTINCT data FROM (
                    SELECT data FROM visits
                    UNION SELECT data FROM guesses
                    UNION SELECT data FROM completions
                    UNION SELECT data FROM surrenders
                    UNION SELECT data FROM hints
                ) ORDER BY data DESC LIMIT ?
            ) d
            LEFT JOIN (
                SELECT data, COUNT(DISTINCT CASE WHEN session_id LIKE 'anon-%' THEN '__anon__' ELSE session_id END) as visits FROM visits GROUP BY data
            ) v ON d.data = v.data
            LEFT JOIN (
                SELECT data, COUNT(DISTINCT CASE WHEN session_id LIKE 'anon-%' THEN '__anon__' ELSE session_id END) as players, COUNT(*) as guesses 
                FROM guesses GROUP BY data
            ) g ON d.data = g.data
            LEFT JOIN (
                SELECT data, COUNT(*) as completions FROM completions GROUP BY data
            ) c ON d.data = c.data
            LEFT JOIN (
                SELECT data, COUNT(*) as surrenders FROM surrenders GROUP BY data
            ) s ON d.data = s.data
            LEFT JOIN (
                SELECT data, COUNT(*) as hints FROM hints GROUP BY data
            ) h ON d.data = h.data
            ORDER BY d.data ASC
        """, (days,)).fetchall()

        return [dict(row) for row in rows]


def get_per_game_stats() -> List[Dict[str, Any]]:
    """Retorna estadístiques per joc (rebuscada)."""
    with get_db() as conn:
        rows = conn.execute("""
            SELECT 
                g.rebuscada,
                g.game_id,
                COUNT(DISTINCT CASE WHEN g.session_id LIKE 'anon-%' THEN '__anon__' ELSE g.session_id END) as jugadors,
                COUNT(*) as total_intents,
                COALESCE(c.completions, 0) as completions,
                COALESCE(s.surrenders, 0) as surrenders,
                COALESCE(h.hints, 0) as hints,
                COALESCE(c.avg_intents, 0) as avg_intents,
                ROUND(CAST(COALESCE(c.completions, 0) AS FLOAT) / NULLIF(COUNT(DISTINCT CASE WHEN g.session_id LIKE 'anon-%' THEN '__anon__' ELSE g.session_id END), 0) * 100, 1) as completion_rate
            FROM guesses g
            LEFT JOIN (
                SELECT rebuscada, COUNT(*) as completions, AVG(num_intents) as avg_intents
                FROM completions GROUP BY rebuscada
            ) c ON g.rebuscada = c.rebuscada
            LEFT JOIN (
                SELECT rebuscada, COUNT(*) as surrenders
                FROM surrenders GROUP BY rebuscada
            ) s ON g.rebuscada = s.rebuscada
            LEFT JOIN (
                SELECT rebuscada, COUNT(*) as hints
                FROM hints GROUP BY rebuscada
            ) h ON g.rebuscada = h.rebuscada
            GROUP BY g.rebuscada
            ORDER BY g.game_id DESC NULLS LAST, g.rebuscada
        """).fetchall()

        return [dict(row) for row in rows]


def get_words_played_for_game(rebuscada: str) -> List[Dict[str, Any]]:
    """Retorna les paraules més jugades per una rebuscada específica (per gràfics)."""
    with get_db() as conn:
        rows = conn.execute("""
            SELECT 
                COALESCE(forma_canonica, paraula) as paraula,
                COUNT(*) as vegades,
                MIN(posicio) as millor_posicio,
                AVG(posicio) as posicio_mitjana
            FROM guesses 
            WHERE rebuscada = ?
            GROUP BY COALESCE(forma_canonica, paraula)
            ORDER BY vegades DESC
            LIMIT 50
        """, (rebuscada,)).fetchall()

        return [dict(row) for row in rows]


def get_players_for_game(rebuscada: str) -> List[Dict[str, Any]]:
    """Retorna la llista de jugadors (sessions) per una rebuscada, amb resum.
    Fusiona totes les sessions anònimes (anon-*) en un sol jugador."""
    with get_db() as conn:
        rows = conn.execute("""
            SELECT 
                CASE WHEN g.session_id LIKE 'anon-%' THEN '__anon__' ELSE g.session_id END as session_id,
                COUNT(*) as num_intents,
                MAX(g.es_correcta) as ha_completat,
                MIN(g.timestamp) as primer_intent,
                MAX(g.timestamp) as ultim_intent,
                COALESCE(SUM(h.num_pistes), 0) as num_pistes,
                MAX(COALESCE(sr.rendicio, 0)) as es_rendicio
            FROM guesses g
            LEFT JOIN (
                SELECT session_id, rebuscada, COUNT(*) as num_pistes
                FROM hints WHERE rebuscada = ?
                GROUP BY session_id
            ) h ON g.session_id = h.session_id AND h.rebuscada = g.rebuscada
            LEFT JOIN (
                SELECT session_id, rebuscada, 1 as rendicio
                FROM surrenders WHERE rebuscada = ?
            ) sr ON g.session_id = sr.session_id AND sr.rebuscada = g.rebuscada
            WHERE g.rebuscada = ?
            GROUP BY CASE WHEN g.session_id LIKE 'anon-%' THEN '__anon__' ELSE g.session_id END
            ORDER BY MIN(g.timestamp)
        """, (rebuscada, rebuscada, rebuscada)).fetchall()

        result = []
        player_num = 0
        for row in rows:
            d = dict(row)
            sid = d['session_id']
            if sid == '__anon__':
                d['label'] = "Anònim"
                d['short_id'] = "anònim"
            else:
                player_num += 1
                d['label'] = f"Jugador {player_num}"
                d['short_id'] = sid[:8] if len(sid) > 8 else sid
            result.append(d)
        return result


def get_player_session(rebuscada: str, session_id: str) -> Dict[str, Any]:
    """Retorna la partida completa d'un jugador per una rebuscada.
    Si session_id és '__anon__', agrupa totes les sessions anon-*."""
    with get_db() as conn:
        is_anon = session_id == '__anon__'
        session_filter = "session_id LIKE 'anon-%'" if is_anon else "session_id = ?"
        params = (rebuscada,) if is_anon else (rebuscada, session_id)

        guesses = conn.execute(f"""
            SELECT paraula, forma_canonica, posicio, es_correcta, timestamp
            FROM guesses
            WHERE rebuscada = ? AND {session_filter}
            ORDER BY timestamp ASC
        """, params).fetchall()

        hints = conn.execute(f"""
            SELECT paraula_pista, posicio, timestamp
            FROM hints
            WHERE rebuscada = ? AND {session_filter}
            ORDER BY timestamp ASC
        """, params).fetchall()

        surrender = conn.execute(f"""
            SELECT timestamp FROM surrenders
            WHERE rebuscada = ? AND {session_filter}
            LIMIT 1
        """, params).fetchone()

        return {
            "guesses": [dict(r) for r in guesses],
            "hints": [dict(r) for r in hints],
            "surrendered": surrender is not None,
            "surrender_time": dict(surrender)["timestamp"] if surrender else None
        }


def get_completion_distribution(rebuscada: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retorna la distribució d'intents per completar jocs (per gràfic de barres)."""
    with get_db() as conn:
        if rebuscada:
            rows = conn.execute("""
                SELECT 
                    CASE 
                        WHEN num_intents <= 5 THEN '1-5'
                        WHEN num_intents <= 10 THEN '6-10'
                        WHEN num_intents <= 20 THEN '11-20'
                        WHEN num_intents <= 30 THEN '21-30'
                        WHEN num_intents <= 50 THEN '31-50'
                        ELSE '50+'
                    END as rang,
                    COUNT(*) as jugadors
                FROM completions
                WHERE rebuscada = ?
                GROUP BY rang
                ORDER BY MIN(num_intents)
            """, (rebuscada,)).fetchall()
        else:
            rows = conn.execute("""
                SELECT 
                    CASE 
                        WHEN num_intents <= 5 THEN '1-5'
                        WHEN num_intents <= 10 THEN '6-10'
                        WHEN num_intents <= 20 THEN '11-20'
                        WHEN num_intents <= 30 THEN '21-30'
                        WHEN num_intents <= 50 THEN '31-50'
                        ELSE '50+'
                    END as rang,
                    COUNT(*) as jugadors
                FROM completions
                GROUP BY rang
                ORDER BY MIN(num_intents)
            """).fetchall()

        return [dict(row) for row in rows]


def get_hint_stats_per_game() -> List[Dict[str, Any]]:
    """Retorna estadístiques de pistes per joc."""
    with get_db() as conn:
        rows = conn.execute("""
            SELECT 
                h.rebuscada,
                COUNT(*) as total_pistes,
                COUNT(DISTINCT h.session_id) as jugadors_amb_pistes,
                ROUND(CAST(COUNT(*) AS FLOAT) / NULLIF(COUNT(DISTINCT h.session_id), 0), 1) as pistes_per_jugador
            FROM hints h
            GROUP BY h.rebuscada
            ORDER BY total_pistes DESC
        """).fetchall()

        return [dict(row) for row in rows]
