"""
Càlcul de proximitat semàntica utilitzant Sentence Transformers (State-of-the-Art).
Utilitza el model multilingual-e5-large per obtenir embeddings més precisos.
Inclou sistema de cache per evitar recalcular embeddings cada vegada.
"""

import json
import os
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer

# Carpeta de dades relativa al fitxer actual
BASE_DATA_DIR = Path(__file__).parent / "data"
MODEL_NAME = "intfloat/multilingual-e5-large"
EMBEDDINGS_CACHE_PATH = BASE_DATA_DIR / "embeddings_cache.json"

# Model global per evitar carregar-lo múltiples vegades
_MODEL_CACHE = None


def carregar_model_sentence_transformer():
    """Carrega el model de Sentence Transformers (multilingual-e5-large)."""
    global _MODEL_CACHE
    
    if _MODEL_CACHE is not None:
        return _MODEL_CACHE
    
    print(f"[SentenceTransformer] Carregant model '{MODEL_NAME}'...")
    BASE_DATA_DIR.mkdir(parents=True, exist_ok=True)
    
    # El model es descarregarà automàticament si no existeix
    model = SentenceTransformer(MODEL_NAME)
    _MODEL_CACHE = model
    print("[SentenceTransformer] Model carregat.")
    return model


def carregar_cache_embeddings() -> dict[str, list[float]]:
    """Carrega el cache d'embeddings des del fitxer JSON."""
    if not EMBEDDINGS_CACHE_PATH.exists():
        return {}
    
    try:
        with open(EMBEDDINGS_CACHE_PATH, encoding='utf-8') as f:
            cache = json.load(f)
        print(f"[Cache] Carregats {len(cache)} embeddings des del cache.")
        return cache
    except Exception as e:
        print(f"[Cache] Error carregant cache: {e}")
        return {}


def guardar_cache_embeddings(cache: dict[str, list[float]]):
    """Guarda el cache d'embeddings al fitxer JSON."""
    try:
        with open(EMBEDDINGS_CACHE_PATH, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False)
        print(f"[Cache] Guardat cache amb {len(cache)} embeddings.")
    except Exception as e:
        print(f"[Cache] Error guardant cache: {e}")


def obtenir_embedding(paraula: str, model, cache: dict[str, list[float]]) -> np.ndarray:
    """
    Obté l'embedding d'una paraula, utilitzant el cache si està disponible.
    
    Per al model E5, s'afegeix el prefix "query: " per obtenir millors resultats.
    """
    if paraula in cache:
        return np.array(cache[paraula])
    
    # Per al model E5, s'afegeix "query: " per millorar la qualitat
    text_input = f"query: {paraula}"
    embedding = model.encode(text_input, normalize_embeddings=True)
    
    # Guardar al cache
    cache[paraula] = embedding.tolist()
    
    return embedding


def calcular_similitud_cosinus(vec1, vec2):
    """Calcula la similitud del cosinus entre dos vectors."""
    # Si els vectors ja estan normalitzats (com amb normalize_embeddings=True),
    # la similitud cosinus és simplement el producte escalar
    return np.dot(vec1, vec2)


def calcular_ranking_complet(
    paraula_objectiu: str, 
    diccionari: list[str], 
    model,
    guardar_debug: bool = True
) -> dict[str, int]:
    """
    Calcula el rànquing de totes les paraules del diccionari respecte a la paraula objectiu.
    Utilitza cache per evitar recalcular embeddings.
    """
    print(f"Calculant rànquing complet (SOTA) per a la paraula: '{paraula_objectiu}'...")
    
    # Carregar cache
    cache = carregar_cache_embeddings()
    cache_inicial = len(cache)
    
    # Obtenir embedding de la paraula objectiu
    vector_objectiu = obtenir_embedding(paraula_objectiu, model, cache)
    
    # Calcular similituds
    similituds = []
    total = len(diccionari)
    for i, paraula in enumerate(diccionari):
        if (i + 1) % 1000 == 0:
            print(f"  Processant {i + 1}/{total} paraules...")
            # Guardar cache cada 1000 paraules per seguretat
            if len(cache) > cache_inicial:
                guardar_cache_embeddings(cache)
        
        vector_paraula = obtenir_embedding(paraula, model, cache)
        sim = calcular_similitud_cosinus(vector_objectiu, vector_paraula)
        similituds.append((paraula, sim))
    
    # Guardar cache final si s'han afegit noves paraules
    if len(cache) > cache_inicial:
        noves = len(cache) - cache_inicial
        print(f"[Cache] Afegides {noves} noves paraules al cache.")
        guardar_cache_embeddings(cache)
    
    # Ordenar per similitud (de major a menor)
    similituds.sort(key=lambda x: x[1], reverse=True)
    
    # Crear el diccionari de rànquing (posició a la llista ordenada)
    ranking_dict = {paraula: i for i, (paraula, _) in enumerate(similituds)}
    
    # Escriure el rànquing a un fitxer de debug
    if guardar_debug:
        debug_path = BASE_DATA_DIR / "ranking_debug_sota.txt"
        with open(debug_path, "w", encoding="utf-8") as f:
            f.write(f"Rànquing SOTA per a la paraula objectiu: '{paraula_objectiu}'\n")
            f.write(f"Model: {MODEL_NAME}\n")
            f.write("="*50 + "\n")
            for i, (paraula, sim) in enumerate(similituds[:100]):  # Només primeres 100
                f.write(f"{i:<5} | {paraula:<20} | Similitud: {sim:.4f}\n")
        print(f"Rànquing SOTA calculat i desat a '{debug_path}'.")
    
    return ranking_dict
