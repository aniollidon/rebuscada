"""
Càlcul de proximitat semàntica utilitzant OpenAI text-embedding-3-large.
Utilitza l'API d'OpenAI per obtenir embeddings d'alta qualitat.
Inclou sistema de cache per evitar recalcular embeddings i estalviar costos d'API.
"""

import json
import os
from pathlib import Path

import numpy as np
from dotenv import load_dotenv
from openai import OpenAI

# Carregar variables d'entorn del fitxer .env
load_dotenv()

# Carpeta de dades relativa al fitxer actual
BASE_DATA_DIR = Path(__file__).parent / "data"
MODEL_NAME = "text-embedding-3-large"
EMBEDDINGS_CACHE_PATH = BASE_DATA_DIR / "embeddings_cache_openai.json"

# Client global per evitar crear-lo múltiples vegades
_CLIENT_CACHE = None


def obtenir_client_openai():
    """Obté el client d'OpenAI amb la clau API."""
    global _CLIENT_CACHE
    
    if _CLIENT_CACHE is not None:
        return _CLIENT_CACHE
    
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError(
            "No s'ha trobat la clau OPENAI_API_KEY. "
            "Defineix-la com a variable d'entorn: export OPENAI_API_KEY='sk-...'"
        )
    
    _CLIENT_CACHE = OpenAI(api_key=api_key)
    print(f"[OpenAI] Client inicialitzat amb model '{MODEL_NAME}'")
    return _CLIENT_CACHE


def carregar_cache_embeddings() -> dict[str, list[float]]:
    """Carrega el cache d'embeddings des del fitxer JSON."""
    if not EMBEDDINGS_CACHE_PATH.exists():
        return {}
    
    try:
        with open(EMBEDDINGS_CACHE_PATH, encoding='utf-8') as f:
            cache = json.load(f)
        print(f"[Cache OpenAI] Carregats {len(cache)} embeddings des del cache.")
        return cache
    except Exception as e:
        print(f"[Cache OpenAI] Error carregant cache: {e}")
        return {}


def guardar_cache_embeddings(cache: dict[str, list[float]]):
    """Guarda el cache d'embeddings al fitxer JSON."""
    try:
        BASE_DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(EMBEDDINGS_CACHE_PATH, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False)
        print(f"[Cache OpenAI] Guardat cache amb {len(cache)} embeddings.")
    except Exception as e:
        print(f"[Cache OpenAI] Error guardant cache: {e}")


def obtenir_embedding(paraula: str, client, cache: dict[str, list[float]]) -> np.ndarray:
    """
    Obté l'embedding d'una paraula utilitzant OpenAI API, amb cache.
    """
    if paraula in cache:
        return np.array(cache[paraula])
    
    try:
        # Cridar l'API d'OpenAI per obtenir l'embedding
        response = client.embeddings.create(
            input=paraula,
            model=MODEL_NAME
        )
        embedding = response.data[0].embedding
        
        # Guardar al cache
        cache[paraula] = embedding
        
        return np.array(embedding)
    except Exception as e:
        print(f"[OpenAI] Error obtenint embedding per '{paraula}': {e}")
        raise


def obtenir_embeddings_batch(paraules: list[str], client, cache: dict[str, list[float]]) -> dict[str, np.ndarray]:
    """
    Obté els embeddings de múltiples paraules en batch per optimitzar les crides a l'API.
    """
    # Separar paraules que ja estan al cache de les que cal processar
    paraules_a_processar = [p for p in paraules if p not in cache]
    resultats = {}
    
    # Afegir les que ja estan al cache
    for paraula in paraules:
        if paraula in cache:
            resultats[paraula] = np.array(cache[paraula])
    
    if not paraules_a_processar:
        return resultats
    
    # Processar en batches de 2000 (límit d'OpenAI per text-embedding-3-large)
    batch_size = 2000
    cache_inicial_batch = len(cache)
    
    for i in range(0, len(paraules_a_processar), batch_size):
        batch = paraules_a_processar[i:i + batch_size]
        
        try:
            print(f"[OpenAI] Processant batch {i//batch_size + 1} amb {len(batch)} paraules...")
            response = client.embeddings.create(
                input=batch,
                model=MODEL_NAME
            )
            
            # Guardar els embeddings al cache i resultats
            for j, paraula in enumerate(batch):
                embedding = response.data[j].embedding
                cache[paraula] = embedding
                resultats[paraula] = np.array(embedding)
            
            # Guardar cache després de cada batch per seguretat
            if len(cache) > cache_inicial_batch:
                BASE_DATA_DIR.mkdir(parents=True, exist_ok=True)
                with open(EMBEDDINGS_CACHE_PATH, 'w', encoding='utf-8') as f:
                    json.dump(cache, f, ensure_ascii=False)
                print(f"[Cache OpenAI] Guardat {len(cache)} embeddings al cache.")
                cache_inicial_batch = len(cache)
                
        except Exception as e:
            print(f"[OpenAI] Error processant batch: {e}")
            # Intentar processar les paraules una per una en cas d'error
            for paraula in batch:
                if paraula not in resultats:
                    try:
                        resultats[paraula] = obtenir_embedding(paraula, client, cache)
                        # Guardar després de cada paraula individual en cas d'error
                        if len(cache) > cache_inicial_batch:
                            with open(EMBEDDINGS_CACHE_PATH, 'w', encoding='utf-8') as f:
                                json.dump(cache, f, ensure_ascii=False)
                            cache_inicial_batch = len(cache)
                    except:
                        pass
    
    return resultats


def calcular_similitud_cosinus(vec1, vec2):
    """Calcula la similitud del cosinus entre dos vectors."""
    norm1 = np.linalg.norm(vec1)
    norm2 = np.linalg.norm(vec2)
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return np.dot(vec1, vec2) / (norm1 * norm2)


def calcular_ranking_complet(
    paraula_objectiu: str, 
    diccionari: list[str],
    guardar_debug: bool = True
) -> dict[str, int]:
    """
    Calcula el rànquing de totes les paraules del diccionari respecte a la paraula objectiu.
    Utilitza l'API d'OpenAI amb cache per evitar crides duplicades.
    """
    print(f"Calculant rànquing complet (OpenAI) per a la paraula: '{paraula_objectiu}'...")
    
    # Obtenir client
    client = obtenir_client_openai()
    
    # Carregar cache
    cache = carregar_cache_embeddings()
    cache_inicial = len(cache)
    
    # Obtenir embedding de la paraula objectiu
    vector_objectiu = obtenir_embedding(paraula_objectiu, client, cache)
    
    # Obtenir embeddings de totes les paraules del diccionari en batch
    print(f"[OpenAI] Obtenint embeddings per {len(diccionari)} paraules...")
    embeddings = obtenir_embeddings_batch(diccionari, client, cache)
    
    # Calcular similituds
    print("[OpenAI] Calculant similituds...")
    similituds = []
    for paraula in diccionari:
        if paraula in embeddings:
            vector_paraula = embeddings[paraula]
            sim = calcular_similitud_cosinus(vector_objectiu, vector_paraula)
            similituds.append((paraula, sim))
        else:
            print(f"[OpenAI] Advertència: No s'ha pogut obtenir embedding per '{paraula}'")
    
    # Guardar cache si s'han afegit noves paraules
    if len(cache) > cache_inicial:
        noves = len(cache) - cache_inicial
        print(f"[Cache OpenAI] Afegides {noves} noves paraules al cache.")
        guardar_cache_embeddings(cache)
    
    # Ordenar per similitud (de major a menor)
    similituds.sort(key=lambda x: x[1], reverse=True)
    
    # Crear el diccionari de rànquing (posició a la llista ordenada)
    ranking_dict = {paraula: i for i, (paraula, _) in enumerate(similituds)}
    
    # Escriure el rànquing a un fitxer de debug
    if guardar_debug:
        debug_path = BASE_DATA_DIR / "ranking_debug_openai.txt"
        with open(debug_path, "w", encoding="utf-8") as f:
            f.write(f"Rànquing OpenAI per a la paraula objectiu: '{paraula_objectiu}'\n")
            f.write(f"Model: {MODEL_NAME}\n")
            f.write("="*50 + "\n")
            for i, (paraula, sim) in enumerate(similituds[:100]):  # Només primeres 100
                f.write(f"{i:<5} | {paraula:<20} | Similitud: {sim:.4f}\n")
        print(f"Rànquing OpenAI calculat i desat a '{debug_path}'.")
    
    return ranking_dict
