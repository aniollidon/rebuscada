import fasttext
import fasttext.util
import os
import json
import shutil
import numpy as np
from typing import List, Dict, Optional
from pathlib import Path

# Carpeta de dades relativa al fitxer actual (no al cwd) per evitar problemes en entorns diferents
BASE_DATA_DIR = Path(__file__).parent / "data"
MODEL_PATH = BASE_DATA_DIR / "cc.ca.300.bin"
OPENAI_CACHE_PATH = BASE_DATA_DIR / "embeddings_cache_openai.json"

def descarregar_model_fasttext():
    """Descarrega el model de fastText per al català dins de la carpeta data si no existeix.

    Soluciona els casos en què al servidor Linux el working directory no és el mateix i
    'data/cc.ca.300.bin' no es troba. Fem servir rutes absolutes i forcem la descarrega
    dins de BASE_DATA_DIR.
    """
    if MODEL_PATH.exists():
        return
    BASE_DATA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[fasttext] Descarregant model a '{MODEL_PATH}' ...")
    cwd = os.getcwd()
    try:
        # Canvia temporalment a la carpeta data perquè fasttext.util.download_model
        # desa els fitxers al cwd.
        os.chdir(BASE_DATA_DIR)
        fasttext.util.download_model('ca', if_exists='ignore')  # genera cc.ca.300.bin (.gz primer)
    finally:
        os.chdir(cwd)
    # Comprova i, si cal, mou el fitxer resultant
    downloaded = BASE_DATA_DIR / "cc.ca.300.bin"
    if not downloaded.exists():
        # Intent de fallback si només hi ha la versió .bin.gz sense descomprimir (versions antigues)
        gz = BASE_DATA_DIR / "cc.ca.300.bin.gz"
        if gz.exists():
            print("[fasttext] Descompressió manual del .gz...")
            import gzip
            with gzip.open(gz, 'rb') as f_in, open(downloaded, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
        else:
            raise RuntimeError("No s'ha pogut obtenir cc.ca.300.bin després de la descàrrega")
    size_mb = downloaded.stat().st_size / (1024 * 1024)
    if size_mb < 50:  # el model normalment és força més gran (> 1GB). Llindar baix per detectar descàrrega corrupta.
        print(f"[WARN] Mida inesperadament petita ({size_mb:.1f} MB). Pot estar corrupta la descàrrega.")
    print("[fasttext] Model descarregat/corresponent disponible.")

def carregar_model_fasttext():
    """Carrega el model de fastText amb rutes robustes (independentment del cwd)."""
    descarregar_model_fasttext()
    print(f"[fasttext] Carregant model des de '{MODEL_PATH}' ...")
    model = fasttext.load_model(str(MODEL_PATH))
    print("[fasttext] Model carregat.")
    return model

def calcular_similitud_cosinus(vec1, vec2):
    """Calcula la similitud del cosinus entre dos vectors."""
    return np.dot(vec1, vec2) / (np.linalg.norm(vec1) * np.linalg.norm(vec2))

def _carregar_openai_cache() -> Optional[Dict[str, List[float]]]:
    """Carrega el cache d'embeddings OpenAI si existeix."""
    if not OPENAI_CACHE_PATH.exists():
        print("[filtre creuat] Cache OpenAI no trobat, el filtre creuat no es pot aplicar.")
        return None
    with open(OPENAI_CACHE_PATH, 'r', encoding='utf-8') as f:
        cache = json.load(f)
    print(f"[filtre creuat] Cache OpenAI carregat: {len(cache)} paraules.")
    return cache


def _filtrar_creuat_openai(similituds, openai_cache, paraula_objectiu,
                            n_core=15, factor_min=0.1):
    """Penalitza paraules usant la similitud OpenAI com a senyal semàntic creuat.

    FastText decideix l'ordre base. OpenAI detecta intrusos.

    Per cada candidat fora del nucli:
      oai_sim = similitud cosinus amb la paraula objectiu a l'espai OpenAI
      referencia = mitjana d'oai_sim del nucli (excloent paraula objectiu)
      factor = min(1.0, max(factor_min, oai_sim / referencia))
      sim_ajustada = sim_fasttext * factor^suavitat

    El paràmetre suavitat (0.5 = arrel quadrada) fa que el factor sigui menys agressiu:
      factor=0.5 → factor_suavitzat=0.71 en lloc de 0.5

    Retorna (similituds_reordenades, penalitzades_info, referencia).
    """
    SUAVITAT = 0.5  # arrel quadrada: menys agressiu, protegeix paraules bones de FT
    n_core = min(n_core, len(similituds))

    # Precalcular vector OpenAI de la paraula objectiu
    if paraula_objectiu not in openai_cache:
        print(f"  [AVÍS] Paraula objectiu '{paraula_objectiu}' no és al cache OpenAI!")
        return similituds, {}, 0.0

    vec_obj = np.array(openai_cache[paraula_objectiu])
    norm_obj = np.linalg.norm(vec_obj)

    # Calcular similitud OpenAI per a les paraules del nucli (excloent objectiu)
    core_oai_sims = []
    for word, _ in similituds[:n_core]:
        if word == paraula_objectiu:
            continue  # no comptar la pròpia paraula
        if word in openai_cache:
            vec = np.array(openai_cache[word])
            oai_sim = float(np.dot(vec_obj, vec) / (norm_obj * np.linalg.norm(vec) + 1e-10))
            core_oai_sims.append(oai_sim)

    if not core_oai_sims:
        print("  [AVÍS] Cap paraula del nucli al cache OpenAI!")
        return similituds, {}, 0.0

    referencia = float(np.mean(core_oai_sims))
    core_std = float(np.std(core_oai_sims))
    print(f"  OpenAI nucli (sense objectiu): mitjana={referencia:.4f}, std={core_std:.4f}, min={min(core_oai_sims):.4f}, max={max(core_oai_sims):.4f}")
    print(f"  Referència: {referencia:.4f}, factor_min={factor_min}, suavitat={SUAVITAT}")

    # El nucli no es filtra
    resultat = list(similituds[:n_core])
    penalitzades_info = {}  # word -> (sim_original, oai_sim, factor)
    oai_sims = {}  # per debug

    for i in range(n_core, len(similituds)):
        paraula, sim = similituds[i]

        if paraula in openai_cache:
            vec = np.array(openai_cache[paraula])
            oai_sim = float(np.dot(vec_obj, vec) / (norm_obj * np.linalg.norm(vec) + 1e-10))
        else:
            oai_sim = referencia

        oai_sims[paraula] = oai_sim

        if oai_sim >= referencia:
            factor = 1.0
        else:
            factor_raw = max(factor_min, oai_sim / referencia)
            factor = factor_raw ** SUAVITAT  # suavitzar: 0.5^0.5=0.71

        new_sim = sim * factor
        resultat.append((paraula, new_sim))

        if factor < 1.0:
            penalitzades_info[paraula] = (sim, oai_sim, factor)

    # Reordenar per similitud ajustada
    resultat.sort(key=lambda x: x[1], reverse=True)

    # Debug: estadístiques
    if oai_sims:
        vals = list(oai_sims.values())
        n_pen = len(penalitzades_info)
        print(f"  Filtre creuat: {n_pen} paraules amb factor < 1.0 de {len(similituds) - n_core}")
        print(f"  OpenAI sim global - min={min(vals):.4f}  max={max(vals):.4f}  mitjana={np.mean(vals):.4f}  mediana={np.median(vals):.4f}")

        # Mostrar canvis al top-100
        print(f"  Canvis al top-100 original:")
        pos_nova = {w: i for i, (w, _) in enumerate(resultat)}
        for pos_orig, (paraula, sim_orig) in enumerate(similituds[:100]):
            if paraula not in oai_sims:
                continue
            oai_s = oai_sims[paraula]
            nova = pos_nova.get(paraula, -1)
            diff = nova - pos_orig
            if abs(diff) >= 3:
                info = penalitzades_info.get(paraula)
                factor_str = f"f={info[2]:.2f}" if info else "f=1.00"
                direction = f"+{diff}" if diff > 0 else str(diff)
                print(f"    pos {pos_orig:<3}→{nova:<4} ({direction:>4}) oai={oai_s:.4f} {factor_str}  {paraula}")

    return resultat, penalitzades_info, referencia


def calcular_ranking_complet(paraula_objectiu: str, diccionari: List[str], model, *,
                              filtre_coherencia: bool = False,
                              n_core: int = 15,
                              factor_penalitzacio: float = 0.1) -> Dict[str, int]:
    """Calcula el rànquing de totes les paraules del diccionari respecte a la paraula objectiu.

    Args:
        filtre_coherencia: Si True, aplica filtre creuat amb OpenAI per penalitzar
            paraules amb similitud FastText alta però similitud OpenAI baixa (soroll de subwords).
        n_core: Nombre de paraules del nucli semàntic (les top-N més similars).
        factor_penalitzacio: Factor mínim de penalització. Paraules amb oai_sim=0 reben
            aquest factor; les altres reben factor proporcional a oai_sim/referencia.
    """
    print(f"Calculant rànquing complet per a la paraula: '{paraula_objectiu}'...")

    vector_objectiu = model.get_word_vector(paraula_objectiu)

    # Calcular vectors per a totes les paraules
    print(f"  Calculant vectors per a {len(diccionari)} paraules...")
    vectors = np.array([model.get_word_vector(p) for p in diccionari])

    # Calcular similituds cosinus (vectoritzat)
    norm_obj = np.linalg.norm(vector_objectiu)
    norms = np.linalg.norm(vectors, axis=1)
    sims = (vectors @ vector_objectiu) / (norms * norm_obj + 1e-10)

    # Crear llista ordenada de (paraula, similitud)
    similituds = sorted(zip(diccionari, sims.tolist()), key=lambda x: x[1], reverse=True)

    penalitzades_info = {}
    referencia = 0.0
    if filtre_coherencia:
        print(f"  Aplicant filtre creuat OpenAI (nucli={n_core}, factor_min={factor_penalitzacio})...")
        openai_cache = _carregar_openai_cache()
        if openai_cache:
            similituds, penalitzades_info, referencia = _filtrar_creuat_openai(
                similituds, openai_cache, paraula_objectiu,
                n_core=n_core, factor_min=factor_penalitzacio
            )
        else:
            print("  [AVÍS] No s'ha pogut aplicar el filtre creuat (cache no disponible).")

    # Crear el diccionari de rànquing (posició a la llista ordenada)
    ranking_dict = {paraula: i for i, (paraula, _) in enumerate(similituds)}

    # Escriure el rànquing a un fitxer de debug
    debug_path = os.path.join("data", "ranking_debug.txt")
    with open(debug_path, "w", encoding="utf-8") as f:
        f.write(f"Rànquing per a la paraula objectiu: '{paraula_objectiu}'\n")
        if filtre_coherencia and penalitzades_info:
            f.write(f"Filtre creuat OpenAI: ON (nucli={n_core}, referència={referencia:.4f}, factor_min={factor_penalitzacio})\n")
            f.write(f"Paraules amb penalització: {len(penalitzades_info)}\n")
        f.write("="*60 + "\n")
        for i, (paraula, sim) in enumerate(similituds):
            if paraula in penalitzades_info:
                sim_orig, oai_sim, factor = penalitzades_info[paraula]
                f.write(f"{i:<5} | {paraula:<20} | Sim: {sim:.4f} [f={factor:.2f} orig={sim_orig:.4f} oai={oai_sim:.4f}]\n")
            else:
                f.write(f"{i:<5} | {paraula:<20} | Sim: {sim:.4f}\n")
    print(f"  Rànquing complet calculat i desat a '{debug_path}'.")
    return ranking_dict