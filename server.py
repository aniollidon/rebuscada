
import asyncio
import hashlib
import json
import logging
import os
import uuid
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import stats as game_stats
from diccionari import Diccionari
from diccionari_full import DiccionariFull


class GuessRequest(BaseModel):
    paraula: str
    rebuscada: str | None = None  # Paraula del dia opcional
    comp_id: str | None = None  # ID de competició opcional
    nom_jugador: str | None = None  # Nom del jugador en competició
    es_personalitzada: bool | None = False  # Si és True, no valida disponibilitat del joc

class GuessResponse(BaseModel):
    paraula: str
    forma_canonica: str | None
    posicio: int
    total_paraules: int
    es_correcta: bool

class ExplicacioNoValida(BaseModel):
    raó: str
    suggeriments: list[str] | None = None

class PistaRequest(BaseModel):
    intents: list[dict]
    rebuscada: str | None = None  # Paraula del dia opcional
    comp_id: str | None = None  # ID de competició opcional
    nom_jugador: str | None = None  # Nom del jugador en competició
    es_personalitzada: bool | None = False  # Si és True, no valida disponibilitat del joc

class PistaResponse(BaseModel):
    paraula: str
    forma_canonica: str | None
    posicio: int
    total_paraules: int

class RendirseRequest(BaseModel):
    rebuscada: str | None = None  # Paraula del dia opcional
    comp_id: str | None = None  # ID de competició opcional
    nom_jugador: str | None = None  # Nom del jugador en competició
    es_personalitzada: bool | None = False  # Si és True, no valida disponibilitat del joc

class RendirseResponse(BaseModel):
    paraula_correcta: str

class RankingItem(BaseModel):
    paraula: str
    posicio: int

class RankingListResponse(BaseModel):
    rebuscada: str
    total_paraules: int
    objectiu: str
    ranking: list[RankingItem]

# Models per competicions
class PlayerState(BaseModel):
    nom: str
    intents: int = 0
    pistes: int = 0
    estat_joc: str = "jugant"  # "jugant", "guanyat" o "rendit"
    millor_posicio: int | None = None  # Millor posició aconseguida
    ultima_actualitzacio: str
    paraules: list[dict] = []  # Paraules provades: [{paraula, posicio, es_pista}]

class CompetitionState(BaseModel):
    comp_id: str
    rebuscada: str
    creador: str
    jugadors: dict[str, PlayerState]
    data_creacio: str
    ultima_activitat: str
    game_id: int | None = None  # ID del joc associat (si existeix)

class CreateCompetitionRequest(BaseModel):
    nom_creador: str
    rebuscada: str | None = None
    intents_existents: list[dict] | None = None

class CreateCompetitionResponse(BaseModel):
    comp_id: str
    rebuscada: str
    game_id: int | None = None

class JoinCompetitionRequest(BaseModel):
    nom_jugador: str
    intents_existents: list[dict] | None = None
    paraula_verificacio: str | None = None  # Per verificar identitat si el nom ja existeix

class JoinCompetitionResponse(BaseModel):
    comp_id: str
    rebuscada: str
    nom_jugador: str
    game_id: int | None = None

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('game.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

load_dotenv()
app = FastAPI()

# Versió de l'API - incrementar quan hi hagi canvis incompatibles amb localStorage
API_VERSION = "1.0.1"

@app.on_event("startup")
async def startup_event():
    """Inicia la tasca de neteja de competicions caducades i la base de dades d'estadístiques"""
    # Inicialitzar base de dades d'estadístiques
    game_stats.init_db()
    logger.info("Stats DB initialized")
    
    asyncio.create_task(cleanup_expired_competitions())
    logger.info(f"Competition cleanup task started (expiry: {COMPETITION_EXPIRY_DAYS} days)")
    logger.info(f"API Version: {API_VERSION}")

# Configurar CORS
# En producció només permetre rebuscada.cat, en desenvolupament també localhost
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "https://rebuscada.cat, https://www.rebuscada.cat, http://localhost:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Secret compartit per operacions internes d'administració entre serveis
ADMIN_SHARED_SECRET = os.getenv("ADMIN_SHARED_SECRET", "")

# Carregar diccionari
DICCIONARI_PATH = os.getenv("DICCIONARI_PATH", "data/diccionari.json")
DEFAULT_REBUSCADA = os.getenv("DEFAULT_REBUSCADA", "paraula")
DICCIONARI_FULL_DB = os.path.join("data", DiccionariFull.DB_FILE)
COMPETITION_EXPIRY_DAYS = int(os.getenv("COMPETITION_EXPIRY_DAYS", "2"))

dicc = Diccionari.load(DICCIONARI_PATH)
dicc_full = DiccionariFull(DICCIONARI_FULL_DB) if os.path.exists(DICCIONARI_FULL_DB) else None

# Emmagatzematge en memòria per competicions
competitions: dict[str, CompetitionState] = {}
competition_connections: dict[str, list[WebSocket]] = {}

def get_session_id(request: Request) -> str:
    """Obté el session_id del header X-Session-Id o en genera un estable basat en IP+UA."""
    sid = request.headers.get("x-session-id")
    if sid:
        return sid
    # Fallback: hash estable de IP + User-Agent perquè el mateix navegador = mateix jugador
    ip = request.client.host if request.client else "unknown"
    ua = request.headers.get("user-agent", "")
    raw = f"{ip}:{ua}"
    return f"anon-{hashlib.sha256(raw.encode()).hexdigest()[:16]}"


def obtenir_start_date() -> str:
    """Obté la data d'inici des del fitxer date.json"""
    date_path = Path("data/date.json")
    if not date_path.exists():
        logger.warning("date.json no trobat, utilitzant data per defecte")
        return "15-11-2025"
    try:
        with open(date_path, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("startDate", "15-11-2025")
    except Exception as e:
        logger.error(f"Error llegint date.json: {e}")
        return "15-11-2025"

# Funció de neteja de competicions caducades
async def cleanup_expired_competitions():
    """Esborra competicions que no han tingut activitat en els últims N dies"""
    while True:
        try:
            await asyncio.sleep(3600)  # Comprova cada hora
            
            now = datetime.now()
            expired_ids = []
            
            for comp_id, competition in competitions.items():
                ultima_activitat = datetime.fromisoformat(competition.ultima_activitat)
                days_inactive = (now - ultima_activitat).days
                
                if days_inactive >= COMPETITION_EXPIRY_DAYS:
                    expired_ids.append(comp_id)
                    logger.info(f"COMPETITION: Expiring {comp_id} (inactive for {days_inactive} days)")
            
            # Esborrar competicions caducades
            for comp_id in expired_ids:
                del competitions[comp_id]
                if comp_id in competition_connections:
                    del competition_connections[comp_id]
        except Exception as e:
            logger.error(f"Error in cleanup_expired_competitions: {e}")

# Carregar llista d'exclusions
EXCLUSIONS_PATH = os.path.join("data", "exclusions.json")
exclusions_set = set()
if os.path.exists(EXCLUSIONS_PATH):
    with open(EXCLUSIONS_PATH, encoding="utf-8") as f:
        exclusions_data = json.load(f)
        exclusions_set = set(Diccionari.normalitzar_paraula(w) for w in exclusions_data.get("lemmas", []))

# Cache per emmagatzemar fins a 10 rànquings carregats (evita recarregar constantment)
CACHE_MAX_SIZE = int(os.getenv("RANKING_CACHE_SIZE", "10"))

def is_catalan(word: str) -> bool:
    """Retorna false si hi ha un caràcter no alfabètic (català, accepta accents, ç, dièresis, punt volat i guionet)
    """
    if not word or len(word) > 100:  # Evita strings buides o massa llargues
        return False
    if not any(c.isalpha() for c in word):  # Almenys una lletra
        return False
    return all(c.isalpha() or c in "àèéíïòóúüç·-" for c in word)

def calcular_joc_actual(games: list, days_diff: int) -> int:
    """Calcula l'ID del joc actual basat en els dies transcorreguts i la durada de cada joc.
    Cada joc té un camp 'dies' que indica quants dies dura (1=diari, 7=setmanal).
    Retorna l'ID del joc que correspon al dia actual.
    """
    sorted_games = sorted(games, key=lambda g: g.get("id", 0))
    cumulative_days = 0
    for game in sorted_games:
        dies = game.get("dies", 1)
        if days_diff < cumulative_days + dies:
            return game.get("id", 1)
        cumulative_days += dies
    # Si hem superat tots els jocs, retorna l'últim
    return sorted_games[-1].get("id", 1) if sorted_games else 1

@lru_cache(maxsize=CACHE_MAX_SIZE)
def carregar_ranking(rebuscada: str):
    """Carrega el rànquing per una paraula específica"""

    # Comprova caràcters vàlids
    if not is_catalan(rebuscada):
        raise Exception(f"La paraula '{rebuscada}' conté caràcters no vàlids.")

    words_dir = Path("data/words")
    fitxer_paraula = words_dir / f"{rebuscada}.json"
    
    if not fitxer_paraula.exists():
        raise Exception(f"No s'ha trobat el fitxer de rànquing per la paraula '{rebuscada}'")
    
    try:
        with open(fitxer_paraula, encoding="utf-8") as f:
            ranking_diccionari = json.load(f)
        
        # Si el rànquing està buit
        if not ranking_diccionari:
            raise Exception(f"El fitxer de rànquing per la paraula '{rebuscada}' està buit.")
        
        total_paraules_ranking = len(ranking_diccionari)
        paraula_objectiu = min(ranking_diccionari, key=lambda k: ranking_diccionari[k])
        
        return ranking_diccionari, total_paraules_ranking, paraula_objectiu
        
    except Exception as e:
        raise Exception(f"Error carregant el fitxer de rànquing: {str(e)}")

def validar_joc_disponible(rebuscada: str):
    """Valida que el joc estigui disponible (no sigui futur)"""
    games_path = Path("data/games.json")
    
    if not games_path.exists():
        return  # Si no hi ha games.json, permetre qualsevol paraula
    
    try:
        with open(games_path, encoding="utf-8") as f:
            data = json.load(f)
        
        games = data.get("games", [])
        start_date_str = obtenir_start_date()
        
        # Calcular l'ID del joc actual usant durada variable (dies)
        start_date = datetime.strptime(start_date_str, "%d-%m-%Y").date()
        today = datetime.now().date()
        days_diff = (today - start_date).days
        current_game_id = max(1, calcular_joc_actual(games, days_diff))
        
        # Buscar la paraula als jocs
        for game in games:
            if game.get("name", "").lower() == rebuscada.lower():
                game_id = game.get("id", 0)
                if game_id > current_game_id:
                    raise HTTPException(
                        status_code=403,
                        detail=f"Aquest joc encara no està disponible. Només podeu jugar fins al joc #{current_game_id}."
                    )
                break
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"Error validant disponibilitat del joc '{rebuscada}': {str(e)}")
        # En cas d'error, permetre el joc

def obtenir_game_id(rebuscada: str) -> int | None:
    """Retorna l'ID del joc per una paraula rebuscada si existeix en games.json"""
    games_path = Path("data/games.json")
    if not games_path.exists():
        return None
    try:
        with open(games_path, encoding="utf-8") as f:
            data = json.load(f)
        for game in data.get("games", []):
            if game.get("name", "").lower() == rebuscada.lower():
                return game.get("id")
    except Exception as e:
        logger.warning(f"No s'ha pogut obtenir game_id per '{rebuscada}': {e}")
    return None

def obtenir_ranking_actiu(rebuscada_request: str | None = None, es_personalitzada: bool = False):
    """Obté el rànquing actiu, sigui el global o el especificat"""
    rebuscada = rebuscada_request.lower() if rebuscada_request else DEFAULT_REBUSCADA
    
    # Validar que el joc estigui disponible (només si no és personalitzada)
    if not es_personalitzada:
        validar_joc_disponible(rebuscada)
    
    try:
        return carregar_ranking(rebuscada)
    except Exception as e:
        logger.error(f"Error carregant el rànquing per la paraula '{rebuscada}': {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/internal/cache/clear")
async def internal_cache_clear(request: Request):
    """Endpoint intern per netejar la memòria cau LRU.

    Requereix el header 'X-Admin-Token' que ha de coincidir amb ADMIN_SHARED_SECRET.
    """
    token = request.headers.get("x-admin-token") or request.headers.get("X-Admin-Token")
    if not ADMIN_SHARED_SECRET:
        logger.warning("/internal/cache/clear rebut però ADMIN_SHARED_SECRET no està configurat")
        raise HTTPException(status_code=503, detail="Configuració d'administració no disponible")
    if not token or token != ADMIN_SHARED_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")

    caches_info = []
    total_before = 0
    total_after = 0

    try:
        # Llista de funcions cachejades a netejar
        lru_funcs = [
            ("carregar_ranking", carregar_ranking),
        ]

        for name, func in lru_funcs:
            try:
                info_before = func.cache_info()
                before_curr = getattr(info_before, "currsize", 0)
            except Exception:
                info_before = None
                before_curr = 0

            try:
                func.cache_clear()
            except Exception as e:
                logger.error(f"Error netejant cache per {name}: {e}")

            try:
                info_after = func.cache_info()
                after_curr = getattr(info_after, "currsize", 0)
            except Exception:
                info_after = None
                after_curr = 0

            total_before += before_curr
            total_after += after_curr

            caches_info.append({
                "name": name,
                "before": {
                    "hits": getattr(info_before, "hits", 0) if info_before else 0,
                    "misses": getattr(info_before, "misses", 0) if info_before else 0,
                    "maxsize": getattr(info_before, "maxsize", None) if info_before else None,
                    "currsize": before_curr,
                },
                "after": {
                    "hits": getattr(info_after, "hits", 0) if info_after else 0,
                    "misses": getattr(info_after, "misses", 0) if info_after else 0,
                    "maxsize": getattr(info_after, "maxsize", None) if info_after else None,
                    "currsize": after_curr,
                },
            })

        logger.info(f"ADMIN: Cache netejada (total abans={total_before}, després={total_after})")
        return {
            "ok": True,
            "cleared": total_before,
            "remaining": total_after,
            "caches": caches_info,
        }
    except Exception as e:
        logger.error(f"Error intern en netejar la cache: {e}")
        raise HTTPException(status_code=500, detail="Error intern en netejar la memòria cau")

@app.post("/guess", response_model=GuessResponse)
async def guess(request: GuessRequest, raw_request: Request):
    # Obtenir rànquing actiu (global o especificat)
    ranking_diccionari, total_paraules, paraula_objectiu = obtenir_ranking_actiu(request.rebuscada, request.es_personalitzada)
    
    paraula_introduida = Diccionari.normalitzar_paraula(request.paraula)
    forma_canonica, es_flexio = dicc.obtenir_forma_canonica(paraula_introduida)
    if forma_canonica is None:
        # Millora: si la paraula no és al diccionari però sí apareix literalment al rànquing, accepta-la.
        rank_directe = ranking_diccionari.get(paraula_introduida)
        if rank_directe is not None:
            es_correcta_directe = paraula_introduida == paraula_objectiu
            logger.info(
                f"GUESS: '{paraula_introduida}' (fora diccionari però trobat al rànquing) -> "
                f"{'CORRECTA!' if es_correcta_directe else '#'+str(rank_directe)} (objectiu: {paraula_objectiu})"
            )
            # Registrar estadística
            try:
                session_id = get_session_id(raw_request)
                game_stats.record_guess(
                    session_id=session_id,
                    rebuscada=request.rebuscada or DEFAULT_REBUSCADA,
                    paraula=paraula_introduida,
                    forma_canonica=None,
                    posicio=rank_directe,
                    es_correcta=es_correcta_directe,
                    game_id=obtenir_game_id(request.rebuscada or DEFAULT_REBUSCADA)
                )
            except Exception as e:
                logger.warning(f"Error registrant estadística de guess directe: {e}")
            # Si és una competició, actualitzar estat (guess directe)
            if request.comp_id and request.nom_jugador:
                await actualitzar_progres_competicio(
                    request.comp_id,
                    request.nom_jugador,
                    posicio=rank_directe,
                    estat_joc="guanyat" if es_correcta_directe else None,
                    paraula=paraula_introduida
                )
            return GuessResponse(
                paraula=paraula_introduida,
                forma_canonica=None,
                posicio=rank_directe,
                total_paraules=total_paraules,
                es_correcta=es_correcta_directe
            )
        # Si no, rebutja la paraula
        msg = "Aquesta paraula no és vàlida."
        logger.info(f"GUESS: '{paraula_introduida}' -> INVÀLIDA (objectiu: {paraula_objectiu}) | reason={msg}")
        raise HTTPException(status_code=400, detail=msg)
    rank = ranking_diccionari.get(forma_canonica)
    if rank is None:
        logger.info(f"GUESS: '{paraula_introduida}' ({forma_canonica}) -> NO TROBADA (objectiu: {paraula_objectiu})")
        raise HTTPException(
            status_code=400,
            detail="Aquesta paraula no es troba al nostre llistat."
        )
    es_correcta = forma_canonica == paraula_objectiu
    
    # Log de l'intent
    status = "CORRECTA!" if es_correcta else f"#{rank}"
    logger.info(f"GUESS: '{paraula_introduida}'{' ('+ forma_canonica + ')' if es_flexio else ''} -> {status} (objectiu: {paraula_objectiu})")
    
    # Si és una competició, actualitzar estat
    if request.comp_id and request.nom_jugador:
        await actualitzar_progres_competicio(
            request.comp_id, 
            request.nom_jugador, 
            posicio=rank,
            estat_joc="guanyat" if es_correcta else None,
            paraula=forma_canonica or paraula_introduida
        )
    
    # Registrar estadístiques
    try:
        session_id = get_session_id(raw_request)
    except Exception:
        session_id = "unknown"
    try:
        game_stats.record_guess(
            session_id=session_id,
            rebuscada=request.rebuscada or DEFAULT_REBUSCADA,
            paraula=paraula_introduida,
            forma_canonica=forma_canonica if es_flexio else None,
            posicio=rank,
            es_correcta=es_correcta,
            game_id=obtenir_game_id(request.rebuscada or DEFAULT_REBUSCADA)
        )
    except Exception as e:
        logger.warning(f"Error registrant estadística de guess: {e}")
    
    return GuessResponse(
        paraula=paraula_introduida,
        forma_canonica=forma_canonica if es_flexio else None,
        posicio=rank,
        total_paraules=total_paraules,
        es_correcta=es_correcta
    )

@app.post("/pista", response_model=PistaResponse)
async def donar_pista(request: PistaRequest, raw_request: Request):
    # Obtenir rànquing actiu (global o especificat)
    ranking_diccionari, total_paraules, paraula_objectiu = obtenir_ranking_actiu(request.rebuscada, request.es_personalitzada)
    intents_actuals = request.intents
    
    # Obtenir les formes canòniques de les paraules provades
    formes_canoniques_provades = set()
    for intent in intents_actuals:
        forma_canonica = intent.get('forma_canonica')
        if forma_canonica:
            formes_canoniques_provades.add(forma_canonica)
        else:
            formes_canoniques_provades.add(intent['paraula'])
    
    # Obtenir la millor posició actual
    millor_ranking = min([intent['posicio'] for intent in intents_actuals]) if intents_actuals else total_paraules
    
    # Crear llista ordenada per posició (rànquing invers)
    ranking_invers = sorted(ranking_diccionari.keys(), key=lambda k: ranking_diccionari[k])
    
    # Determinar el rang de posicions per la pista
    if not intents_actuals or millor_ranking >= 1000:
        # Primera pista o molt lluny: començar a prop de la posició 500
        target_pos = 500
        variacio = 50
        inici_rang = max(0, target_pos - variacio)
        fi_rang = min(target_pos + variacio, total_paraules - 1)
    elif millor_ranking == 1:
        # Si ja tenen la posició 1, donar una paraula molt propera (posicions 2-5)
        inici_rang = 1  # posició 2 (index 1)
        fi_rang = min(4, total_paraules - 1)  # posició 5 màxim
    elif millor_ranking <= 10:
        # Si estan molt a prop, donar alguna cosa una mica millor
        target_pos = millor_ranking // 2
        inici_rang = max(0, target_pos - 2)
        fi_rang = max(target_pos + 2, millor_ranking - 1)
    elif millor_ranking <= 50:
        # Rang mitjà-petit: més a prop de la meitat
        target_pos = millor_ranking // 2
        inici_rang = max(0, target_pos - 5)
        fi_rang = max(target_pos + 5, millor_ranking - 1)
    elif millor_ranking <= 200:
        # Rang mitjà: centrat a la meitat amb una mica de variació
        target_pos = millor_ranking // 2
        inici_rang = max(0, target_pos - 10)
        fi_rang = max(target_pos + 10, millor_ranking - 1)
    elif millor_ranking <= 500:
        # Rang llunyà però no extremadament: a prop de la meitat
        target_pos = millor_ranking // 2
        variacio = min(15, millor_ranking // 15)
        inici_rang = max(0, target_pos - variacio)
        fi_rang = max(target_pos + variacio, millor_ranking - 1)
    else:
        # Rang molt llunyà: centrat a la meitat
        target_pos = millor_ranking // 2
        variacio = min(25, millor_ranking // 12)
        inici_rang = max(0, target_pos - variacio)
        fi_rang = max(target_pos + variacio, millor_ranking - 1)
    
    # Buscar una paraula adequada (prioritza freqüència de lema dins del rang)
    paraula_pista = None
    try:
        subllista = ranking_invers[inici_rang:fi_rang + 1] if fi_rang >= inici_rang else []
        candidats = [w for w in subllista if w not in formes_canoniques_provades and w != paraula_objectiu]
        if candidats:
            # Tria el candidat amb més freqüència al diccionari; si empata, el de millor rànquing (valor més petit), i després ordre alfabètic
            paraula_pista = max(
                candidats,
                key=lambda w: (dicc.freq_lema(w), -ranking_diccionari.get(w, total_paraules), w)
            )
    except Exception:
        paraula_pista = None
    
    # Si no trobem cap paraula adequada, buscar qualsevol paraula no provada
    if paraula_pista is None:
        for paraula_candidata in ranking_invers:
            if (paraula_candidata not in formes_canoniques_provades and 
                paraula_candidata != paraula_objectiu):
                paraula_pista = paraula_candidata
                break
    
    if paraula_pista is None:
        logger.warning(f"PISTA: No s'ha trobat cap pista adequada (objectiu: {paraula_objectiu}, millor: #{millor_ranking})")
        raise HTTPException(status_code=404, detail="No s'ha pogut trobar una pista adequada.")
    
    # Log de la pista donada
    logger.info(f"PISTA: '{paraula_pista}' -> #{ranking_diccionari[paraula_pista]} (objectiu: {paraula_objectiu}, millor: #{millor_ranking})")
    
    # Si és una competició, actualitzar pistes
    if request.comp_id and request.nom_jugador:
        await actualitzar_progres_competicio(
            request.comp_id, 
            request.nom_jugador, 
            incrementar_pistes=True,
            posicio=ranking_diccionari[paraula_pista],
            paraula=paraula_pista,
            es_pista=True
        )
    
    # Registrar estadística de pista
    try:
        session_id = get_session_id(raw_request)
        game_stats.record_hint(
            session_id=session_id,
            rebuscada=request.rebuscada or DEFAULT_REBUSCADA,
            paraula_pista=paraula_pista,
            posicio=ranking_diccionari[paraula_pista],
            game_id=obtenir_game_id(request.rebuscada or DEFAULT_REBUSCADA)
        )
    except Exception as e:
        logger.warning(f"Error registrant estadística de pista: {e}")
    
    return PistaResponse(
        paraula=paraula_pista,
        forma_canonica=None,
        posicio=ranking_diccionari[paraula_pista],
        total_paraules=total_paraules
    )

@app.post("/whynot", response_model=ExplicacioNoValida)
async def whynot(request: GuessRequest):
    """Endpoint per explicar per què una paraula no és vàlida"""
    ranking_diccionari, total_paraules, paraula_objectiu = obtenir_ranking_actiu(request.rebuscada, request.es_personalitzada)
    paraula_introduida = Diccionari.normalitzar_paraula(request.paraula)
    # Cas específic: espais no permesos (només una paraula simple)
    if any(ch.isspace() for ch in request.paraula):
        suggeriments = None
        try:
            if dicc_full is not None:
                # Prova sense espais per suggerir alternatives
                sense_espais = "".join(paraula_introduida.split())
                if sense_espais:
                    near_result = dicc_full.near(sense_espais, limit=6, min_score=60)
                    if near_result and near_result.get('candidates'):
                        suggeriments = [c['word'] for c in near_result['candidates']]
        except Exception:
            suggeriments = None

        logger.info(f"WHYNOT: '{request.paraula}' -> conté espais")
        return ExplicacioNoValida(
            raó=(
                "Sembla que has introduït un espai. Només s'accepten paraules simples (sense espais)."
            ),
            suggeriments=suggeriments
        )

    # Validació de caràcters catalans permesos
    if not is_catalan(paraula_introduida):
        logger.info(f"WHYNOT: '{paraula_introduida}' -> caràcters no permesos")
        return ExplicacioNoValida(
            raó=(
                "Aquesta paraula conté caràcters no permesos. Només s'accepten lletres catalanes amb accents, "
                "dièresi, la ce trencada (ç), el punt volat (l·l) i el guionet (-)."
            ),
            suggeriments=None
        )
    forma_canonica, es_flexio = dicc.obtenir_forma_canonica(paraula_introduida)
    rank_directe = ranking_diccionari.get(paraula_introduida)

    
    # Si la paraula és vàlida respondre HTTP Error ja que la paraula és correcta
    if forma_canonica is not None or rank_directe is not None:
        raise HTTPException(
            status_code=400,
            detail="La paraula introduïda és vàlida; aquest endpoint només és per paraules no vàlides."
        )

    # Si no tenim diccionari complet, no podem donar explicacions detallades
    if dicc_full is None:
        raise HTTPException(
            status_code=500,
            detail="El diccionari complet no està disponible."
        )

    # Obtenir informació de la paraula del diccionari complet
    info = dicc_full.info(paraula_introduida)

    explicacio = "Aquesta paraula simplement no és vàlida."
    suggeriments = None
    
    # 1. Si la paraula no existeix al diccionari complet -> error tipogràfic
    if not info['known_form']:
        explicacio = "Aquesta paraula probablement no està ben escrita."
        # Recomanar paraules similars amb la funció near
        near_result = dicc_full.near(paraula_introduida, limit=6, min_score=60)
        if near_result['candidates']:
            suggeriments = [c['word'] for c in near_result['candidates']]
    
    # 2. Si existeix, comprovar la categoria
    else:
        lemes = info['lemmas']
        primary_lemma = info['primary_lemma'] or (lemes[0] if lemes else None)
        
        if not primary_lemma:
            explicacio = "Aquesta paraula no és vàlida per una inconsistència al diccionari (#NOLEMA-ERROR). Si creus que hi hauria d'estar, si us plau, informa'ns."
        else:
            # Obtenir categories del lema principal
            categories = info['lemma_categories'].get(primary_lemma, [])
            ','.join(categories)
            
            # Comprovar si és una categoria no permesa (no NC ni VM)
            te_nc_o_vm = any(cat in ['NC', 'VM'] for cat in categories)
            
            if not te_nc_o_vm and categories:
                # Té categories però no són NC o VM
                # Trobar la categoria més comuna per fer el missatge
                from collections import Counter
                counter = Counter(categories)
                cat_principal = counter.most_common(1)[0][0] if counter else categories[0]
                
                # Etiqueta humana de la categoria
                cat_label = dicc_full._cat2_label(cat_principal)
                explicacio = f"Aquesta paraula és {cat_label}. Només es permeten noms i verbs comuns."
            
            # 3. Si està a la llista d'exclusions
            elif primary_lemma in exclusions_set:              
                if te_nc_o_vm:
                    # Intentem justificar si té alguna altre categoria diferent a NC o VM
                    altre_categories = [cat for cat in categories if cat not in ['NC', 'VM']]
                    if altre_categories:
                        from collections import Counter
                        counter = Counter(altre_categories)
                        cat_principal = counter.most_common(1)[0][0] if counter else altre_categories[0]
                        cat_label = dicc_full._cat2_label(cat_principal)
                        explicacio = f"Aquesta paraula és principalment {cat_label} i s'ha exclòs del joc."
                    else:
                        explicacio = "Aquesta paraula s'ha exclòs del joc (pot ser un arcaisme, castellanisme o per canvis ortogràfics recents)."
            
            # 4. Si existeix al diccionari però no al ranking -> poca freqüència
            elif forma_canonica is None and rank_directe is None:
                explicacio = "Aquesta paraula és massa poc comuna i s'ha exclòs del joc, per facilitar la jugabilitat."

    logger.info(f"WHYNOT: '{paraula_introduida}' -> {explicacio[:50]}...")
    
    return ExplicacioNoValida(
        raó=explicacio,
        suggeriments=suggeriments
    )


async def actualitzar_progres_competicio(
    comp_id: str, 
    nom_jugador: str, 
    incrementar_pistes: bool = False,
    posicio: int | None = None,
    estat_joc: str | None = None,
    paraula: str | None = None,
    es_pista: bool = False
):
    """Actualitza el progrés d'un jugador en una competició
    
    Args:
        estat_joc: "guanyat", "rendit" o None (per mantenir estat actual)
        paraula: La paraula provada (per guardar-la)
        es_pista: Si la paraula és una pista
    """
    if comp_id not in competitions:
        return
    
    competition = competitions[comp_id]
    if nom_jugador not in competition.jugadors:
        return
    
    player = competition.jugadors[nom_jugador]
    
    if not incrementar_pistes:
        player.intents += 1
    
    if incrementar_pistes:
        player.pistes += 1
    
    if estat_joc is not None:
        player.estat_joc = estat_joc
    
    # Guardar paraula provada
    if paraula and posicio is not None:
        player.paraules.append({
            "paraula": paraula,
            "posicio": posicio,
            "es_pista": es_pista
        })
    
    # Actualitzar millor posició
    if posicio is not None:
        if player.millor_posicio is None or posicio < player.millor_posicio:
            player.millor_posicio = posicio
    
    now = datetime.now().isoformat()
    player.ultima_actualitzacio = now
    competition.ultima_activitat = now
    
    # Notificar altres jugadors
    await broadcast_competition_update(comp_id)

async def broadcast_competition_update(comp_id: str):
    """Envia actualitzacions a tots els clients connectats a una competició"""
    if comp_id not in competition_connections:
        return
    
    if comp_id not in competitions:
        return
    
    competition = competitions[comp_id]
    message = {
        "type": "update",
        "jugadors": [
            {
                "nom": player.nom,
                "intents": player.intents,
                "pistes": player.pistes,
                "estat_joc": player.estat_joc,
                "millor_posicio": player.millor_posicio,
                "paraules": player.paraules
            }
            for player in competition.jugadors.values()
        ]
    }
    
    # Enviar a tots els websockets connectats
    disconnected = []
    for websocket in competition_connections[comp_id]:
        try:
            await websocket.send_json(message)
        except:
            disconnected.append(websocket)
    
    # Netejar connexions desconnectades
    for ws in disconnected:
        competition_connections[comp_id].remove(ws)

@app.post("/competition/create", response_model=CreateCompetitionResponse)
async def create_competition(request: CreateCompetitionRequest):
    """Crea una nova competició"""
    try:
        comp_id = str(uuid.uuid4())[:8]  # ID curt
        rebuscada = request.rebuscada or DEFAULT_REBUSCADA
        
        # Validar que la rebuscada existeix
        try:
            carregar_ranking(rebuscada)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Paraula no vàlida: {str(e)}")
        
        now = datetime.now().isoformat()
        
        # Calcular intents i millor posició dels intents existents
        intents_count = len(request.intents_existents) if request.intents_existents else 0
        millor_pos = None
        paraules_inicials = []
        if request.intents_existents:
            posicions = [intent.get('posicio') for intent in request.intents_existents if 'posicio' in intent]
            if posicions:
                millor_pos = min(posicions)
            for intent in request.intents_existents:
                paraules_inicials.append({
                    "paraula": intent.get("forma_canonica") or intent.get("paraula", ""),
                    "posicio": intent.get("posicio", 0),
                    "es_pista": intent.get("es_pista", False)
                })
        
        player_state = PlayerState(
            nom=request.nom_creador,
            intents=intents_count,
            pistes=0,
            estat_joc="jugant",
            millor_posicio=millor_pos,
            ultima_actualitzacio=now,
            paraules=paraules_inicials
        )
        
        competition = CompetitionState(
            comp_id=comp_id,
            rebuscada=rebuscada,
            creador=request.nom_creador,
            jugadors={request.nom_creador: player_state},
            data_creacio=now,
            ultima_activitat=now,
            game_id=obtenir_game_id(rebuscada)
        )
        
        competitions[comp_id] = competition
        competition_connections[comp_id] = []
        
        logger.info(f"COMPETITION: Created {comp_id} by {request.nom_creador} for word '{rebuscada}' with {intents_count} existing attempts (millor pos: {millor_pos})")
        
        return CreateCompetitionResponse(
            comp_id=comp_id,
            rebuscada=rebuscada,
            game_id=competition.game_id
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating competition: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/competition/{comp_id}/join", response_model=JoinCompetitionResponse)
async def join_competition(comp_id: str, request: JoinCompetitionRequest):
    """Uneix un jugador a una competició existent"""
    if comp_id not in competitions:
        raise HTTPException(status_code=404, detail="Competició no trobada")
    
    competition = competitions[comp_id]
    
    # Comprovar si el nom ja existeix
    now = datetime.now().isoformat()
    if request.nom_jugador in competition.jugadors:
        existing_player = competition.jugadors[request.nom_jugador]
        
        if existing_player.paraules:
            # Jugador té paraules - requereix verificació
            if not request.paraula_verificacio:
                logger.info(f"COMPETITION: Name '{request.nom_jugador}' already taken in {comp_id}, verification required")
                return JSONResponse(
                    status_code=409,
                    content={
                        "message": "El nom ja està en ús en aquesta competició",
                        "nom_existent": True,
                        "te_paraules": True
                    }
                )
            # Verificar la paraula
            paraula_verificacio_norm = Diccionari.normalitzar_paraula(request.paraula_verificacio)
            paraules_jugador = [Diccionari.normalitzar_paraula(p.get("paraula", "")) for p in existing_player.paraules]
            if paraula_verificacio_norm not in paraules_jugador:
                logger.info(f"COMPETITION: Wrong verification for '{request.nom_jugador}' in {comp_id}")
                return JSONResponse(
                    status_code=403,
                    content={"message": "La paraula de verificació no és correcta"}
                )
            # Verificació correcta - permetre reincorporació
            logger.info(f"COMPETITION: Player '{request.nom_jugador}' verified and rejoining {comp_id}")
        else:
            # Jugador sense paraules - no es pot verificar, bloquejar
            logger.info(f"COMPETITION: Name '{request.nom_jugador}' taken (no words) in {comp_id}")
            return JSONResponse(
                status_code=409,
                content={
                    "message": "El nom ja està en ús en aquesta competició",
                    "nom_existent": True,
                    "te_paraules": False
                }
            )
        
        # Notificar altres jugadors (per refrescar l'estat)
        await broadcast_competition_update(comp_id)
    else:
        # Nou jugador
        intents_count = len(request.intents_existents) if request.intents_existents else 0
        
        # Calcular la millor posició dels intents existents
        millor_pos = None
        paraules_inicials = []
        if request.intents_existents:
            posicions = [intent.get('posicio') for intent in request.intents_existents if 'posicio' in intent]
            if posicions:
                millor_pos = min(posicions)
            for intent in request.intents_existents:
                paraules_inicials.append({
                    "paraula": intent.get("forma_canonica") or intent.get("paraula", ""),
                    "posicio": intent.get("posicio", 0),
                    "es_pista": intent.get("es_pista", False)
                })
        
        player_state = PlayerState(
            nom=request.nom_jugador,
            intents=intents_count,
            pistes=0,
            estat_joc="jugant",
            millor_posicio=millor_pos,
            ultima_actualitzacio=now,
            paraules=paraules_inicials
        )
        
        competition.jugadors[request.nom_jugador] = player_state
        logger.info(f"COMPETITION: Player {request.nom_jugador} joined {comp_id} with {intents_count} existing attempts (millor pos: {millor_pos})")
        
        # Notificar altres jugadors
        await broadcast_competition_update(comp_id)
    
    return JoinCompetitionResponse(
        comp_id=comp_id,
        rebuscada=competition.rebuscada,
        nom_jugador=request.nom_jugador,
        game_id=competition.game_id
    )

@app.get("/competition/{comp_id}", response_model=CompetitionState)
async def get_competition(comp_id: str):
    """Obté l'estat actual d'una competició"""
    if comp_id not in competitions:
        raise HTTPException(status_code=404, detail="Competició no trobada")
    
    return competitions[comp_id]

@app.post("/competition/{comp_id}/leave")
async def leave_competition(comp_id: str, nom_jugador: str = Query(...)):
    """Surt d'una competició (elimina el jugador)"""
    if comp_id not in competitions:
        raise HTTPException(status_code=404, detail="Competició no trobada")
    
    competition = competitions[comp_id]
    
    if nom_jugador not in competition.jugadors:
        raise HTTPException(status_code=404, detail="Jugador no trobat en aquesta competició")
    
    # Eliminar jugador
    del competition.jugadors[nom_jugador]
    logger.info(f"COMPETITION: Player {nom_jugador} left {comp_id}")
    
    # Si no queden jugadors, eliminar la competició
    if len(competition.jugadors) == 0:
        del competitions[comp_id]
        if comp_id in competition_connections:
            del competition_connections[comp_id]
        logger.info(f"COMPETITION: Deleted {comp_id} (no players left)")
    else:
        # Notificar altres jugadors
        await broadcast_competition_update(comp_id)
    
    return {"message": "Has sortit de la competició"}

@app.websocket("/ws/competition/{comp_id}")
async def competition_websocket(websocket: WebSocket, comp_id: str):
    """WebSocket per rebre actualitzacions en temps real d'una competició"""
    if comp_id not in competitions:
        await websocket.close(code=1008, reason="Competició no trobada")
        return
    
    await websocket.accept()
    
    if comp_id not in competition_connections:
        competition_connections[comp_id] = []
    
    competition_connections[comp_id].append(websocket)
    logger.info(f"COMPETITION WS: Client connected to {comp_id}")
    
    try:
        # Enviar estat inicial
        competition = competitions[comp_id]
        await websocket.send_json({
            "type": "init",
            "jugadors": [
                {
                    "nom": player.nom,
                    "intents": player.intents,
                    "pistes": player.pistes,
                    "estat_joc": player.estat_joc,
                    "millor_posicio": player.millor_posicio,
                    "paraules": player.paraules
                }
                for player in competition.jugadors.values()
            ]
        })
        
        # Mantenir connexió oberta
        while True:
            # Esperar missatges (per detectar desconnexions)
            await websocket.receive_text()
    except WebSocketDisconnect:
        logger.info(f"COMPETITION WS: Client disconnected from {comp_id}")
    except Exception as e:
        logger.error(f"COMPETITION WS: Error - {str(e)}")
    finally:
        if websocket in competition_connections.get(comp_id, []):
            competition_connections[comp_id].remove(websocket)

@app.post("/visit")
async def register_visit(request: Request):
    """Registra una visita a la web."""
    try:
        session_id = get_session_id(request)
        body = await request.json()
        rebuscada = body.get("rebuscada")
        game_id = body.get("game_id")
        game_stats.record_visit(session_id, rebuscada, game_id)
        return {"ok": True}
    except Exception as e:
        logger.warning(f"Error registrant visita: {e}")
        return {"ok": False}

@app.get("/")
async def root():
    return {"message": "API del joc de paraules (refactoritzat)"}

@app.get("/version")
async def get_version():
    """Retorna la versió de l'API"""
    return {"version": API_VERSION}

@app.get("/paraula-dia")
async def get_rebuscada():
    """Retorna la paraula del dia actual basada en games.json"""
    games_path = Path("data/games.json")
    
    from datetime import datetime
    
    if not games_path.exists():
        # Si no existeix games.json, retorna la paraula per defecte
        today = datetime.now().date()
        return {
            "id": 1,
            "name": DEFAULT_REBUSCADA,
            "startDate": today.strftime("%d-%m-%Y"),
            "today": today.strftime("%d-%m-%Y")
        }
    
    try:
        with open(games_path, encoding="utf-8") as f:
            data = json.load(f)
        
        games = data.get("games", [])
        start_date_str = obtenir_start_date()
        
        # Parseja la data d'inici
        start_date = datetime.strptime(start_date_str, "%d-%m-%Y").date()
        today = datetime.now().date()
        
        if not games:
            return {
                "id": 1,
                "name": DEFAULT_REBUSCADA,
                "startDate": start_date_str,
                "today": today.strftime("%d-%m-%Y")
            }
        
        # Calcula la ID del joc usant durada variable (dies)
        days_diff = (today - start_date).days
        target_id = calcular_joc_actual(games, max(0, days_diff))
        
        # Busca el joc amb l'ID més proper
        sorted_games = sorted(games, key=lambda g: g.get("id", 0))
        
        if target_id > sorted_games[-1].get("id", 0):
            # Si l'ID és superior a l'últim, retorna l'últim
            selected_game = sorted_games[-1]
        else:
            # Busca l'ID exacte o el més proper
            selected_game = None
            for game in sorted_games:
                if game.get("id", 0) >= target_id:
                    selected_game = game
                    break
            
            if not selected_game:
                selected_game = sorted_games[0]
        
        # Retorna informació completa del joc
        return {
            "id": selected_game.get("id", 1),
            "name": selected_game.get("name", DEFAULT_REBUSCADA),
            "startDate": start_date_str,
            "today": today.strftime("%d-%m-%Y")
        }
        
    except Exception as e:
        logger.error(f"Error obtenint paraula del dia: {str(e)}")
        today = datetime.now().date()
        return {
            "id": 1,
            "name": DEFAULT_REBUSCADA,
            "startDate": today.strftime("%d-%m-%Y"),
            "today": today.strftime("%d-%m-%Y")
        }

@app.get("/public-games")
async def get_public_games():
    """Retorna tots els jocs disponibles (sense autenticació)"""
    games_path = Path("data/games.json")
    
    if not games_path.exists():
        from datetime import datetime
        today = datetime.now().date()
        return {
            "startDate": today.strftime("%d-%m-%Y"),
            "today": today.strftime("%d-%m-%Y"),
            "games": [],
            "currentGameId": 1
        }
    
    try:
        with open(games_path, encoding="utf-8") as f:
            data = json.load(f)
        
        from datetime import datetime
        start_date_str = obtenir_start_date()
        start_date = datetime.strptime(start_date_str, "%d-%m-%Y").date()
        today = datetime.now().date()
        
        # Calcular l'ID del joc actual usant durada variable (dies)
        games = data.get("games", [])
        days_diff = (today - start_date).days
        current_game_id = calcular_joc_actual(games, max(0, days_diff))
        
        return {
            "startDate": start_date_str,
            "today": today.strftime("%d-%m-%Y"),
            "games": games,
            "currentGameId": max(1, current_game_id)
        }
    except Exception as e:
        logger.error(f"Error llegint games.json: {str(e)}")
        from datetime import datetime
        today = datetime.now().date()
        return {
            "startDate": today.strftime("%d-%m-%Y"),
            "today": today.strftime("%d-%m-%Y"),
            "currentGameId": 1,
            "games": []
        }

@app.post("/rendirse", response_model=RendirseResponse)
async def rendirse(request: RendirseRequest, raw_request: Request):
    """Endpoint per rendir-se i obtenir la resposta correcta"""
    try:
        # Obtenir rànquing actiu (global o especificat)
        ranking_diccionari, total_paraules, paraula_objectiu = obtenir_ranking_actiu(request.rebuscada, request.es_personalitzada)
        
        # Log de rendició
        logger.info(f"RENDICIÓ: Revelada paraula '{paraula_objectiu}'")
        
        # Si és una competició, marcar com a rendit
        if request.comp_id and request.nom_jugador:
            await actualitzar_progres_competicio(
                request.comp_id, 
                request.nom_jugador, 
                estat_joc="rendit"
            )
        
        # Registrar estadística de rendició
        try:
            session_id = get_session_id(raw_request)
            game_stats.record_surrender(
                session_id=session_id,
                rebuscada=request.rebuscada or DEFAULT_REBUSCADA,
                game_id=obtenir_game_id(request.rebuscada or DEFAULT_REBUSCADA)
            )
        except Exception as e:
            logger.warning(f"Error registrant estadística de rendició: {e}")
        
        return RendirseResponse(paraula_correcta=paraula_objectiu)
    
    except Exception as e:
        logger.error(f"RENDICIÓ: Error - {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Hi ha un error en abandonar: {str(e)}"
        )

@app.get("/ranking", response_model=RankingListResponse)
async def obtenir_ranking(limit: int = Query(300, ge=1, le=2000), rebuscada: str | None = None):
    """Retorna les primeres 'limit' paraules del rànquing per la paraula del dia actual o l'especificada.

    Parameters
    ----------
    limit: int
        Nombre màxim de paraules a retornar (per defecte 300, màxim 2000)
    rebuscada: Optional[str]
        Paraula del dia per la qual es vol obtenir el rànquing (opcional)
    """
    try:
        ranking_diccionari, total_paraules, paraula_objectiu = obtenir_ranking_actiu(rebuscada)
        # Ordenar per posició (valor més petit = més proper)
        ordenat = sorted(ranking_diccionari.items(), key=lambda kv: kv[1])[:limit]
        return RankingListResponse(
            rebuscada=rebuscada.lower() if rebuscada else DEFAULT_REBUSCADA,
            total_paraules=total_paraules,
            objectiu=paraula_objectiu,
            ranking=[RankingItem(paraula=p, posicio=pos) for p, pos in ordenat]
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Hi ha un error en obtenir el rànquing: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
