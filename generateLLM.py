"""
Generació de rànkings semàntics combinant FastText + LLM.

Estratègia:
  1. FastText genera un rànking base complet (27k paraules)
  2. Demanem a un LLM que generi paraules semànticament properes a l'objectiu
  3. Creuem les paraules del LLM amb el diccionari (resolent flexions a lemes)
  4. Injectem les paraules del LLM al pool del top (si FastText les tenia lluny)
  5. Demanem al LLM que puntui el top en lots petits
  6. Combinem puntuació LLM + FastText per al rànking final
"""

import argparse
import json
import os
import re
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from diccionari import Diccionari
from proximitat import calcular_ranking_complet, carregar_model_fasttext

load_dotenv()

# --- Configuració ---
BASE_DATA_DIR = Path(__file__).parent / "data"
LLM_CACHE_DIR = BASE_DATA_DIR / "llm_cache"

# Model per defecte
DEFAULT_MODEL = "gpt-5-mini"

# Quantes paraules del top de FastText avaluem amb LLM
TOP_A_AVALUAR = 500

# Mida dels lots per puntuar (quantes paraules per crida LLM)
MIDA_LOT = 25

# Pes relatiu de la puntuació LLM vs FastText al rànking final
PES_LLM = 0.7
PES_FASTTEXT = 0.3

# Models de raonament que NO suporten temperature=0
MODELS_SENSE_TEMPERATURE = {"o1", "o1-mini", "o1-preview", "o3", "o3-mini", "o4-mini", "gpt-5-mini", "gpt-5-nano"}

def _params_model(model: str) -> dict:
    """Retorna paràmetres extra per a la crida API segons el model."""
    if any(model.startswith(prefix) for prefix in MODELS_SENSE_TEMPERATURE):
        return {}
    return {"temperature": 0}


def obtenir_client_openai() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("No s'ha trobat OPENAI_API_KEY. Defineix-la al fitxer .env")
    return OpenAI(api_key=api_key)


# =============================================================================
# PAS 1: Demanar al LLM paraules relacionades
# =============================================================================

PROMPT_GENERAR = """Genera una llista de PARAULES INDIVIDUALS en català semànticament properes a "{paraula}".

REGLES IMPORTANTS:
- Només paraules individuals (NO expressions com "hora de dinar" o "rellotge de sol")
- Prioritza NOMS (substantius) per sobre de verbs
- Inclou alguns verbs rellevants però que no dominin la llista
- No incloguis adjectius, adverbis, preposicions ni determinants

Categories de relació a explorar:
1. Sinònims i quasi-sinònims del concepte
2. Objectes, instruments o eines directament relacionats
3. Unitats o mesures del mateix àmbit
4. Conceptes del mateix camp semàntic (tant generals com específics)
5. Accions específiques fortament associades (verbs, amb moderació)
6. Esdeveniments o situacions típicament associades
7. Parts o subdivisions del concepte
8. Paraules que un parlant associaria immediatament amb "{paraula}"

Exemple de format correcte: paraula1, paraula2, paraula3
Exemple de format INCORRECTE: paraula de context, una altra expressió llarga

Genera com a mínim 200 paraules, ordenades de més a menys properes.
Respon NOMÉS amb la llista de paraules separades per comes."""


def generar_paraules_llm(
    client: OpenAI, paraula: str, model: str = DEFAULT_MODEL
) -> list[str]:
    """Demana a l'LLM que generi paraules semànticament relacionades."""
    print(f"[LLM] Generant paraules relacionades amb '{paraula}'...")

    response = client.chat.completions.create(
        model=model,
        **_params_model(model),
        messages=[
            {
                "role": "system",
                "content": "Ets un lingüista expert en català. Respons sempre en català.",
            },
            {
                "role": "user",
                "content": PROMPT_GENERAR.format(paraula=paraula),
            },
        ],
    )

    text = response.choices[0].message.content.strip()
    paraules_raw = [p.strip().lower() for p in text.split(",") if p.strip()]
    print(f"[LLM] Generades {len(paraules_raw)} paraules")
    return paraules_raw


# =============================================================================
# PAS 2: Creuar paraules LLM amb el diccionari (resolent flexions)
# =============================================================================


def creuar_amb_diccionari(
    paraules_llm: list[str], diccionari: Diccionari, lemes_diccionari: set[str]
) -> tuple[set[str], list[str]]:
    """Creua les paraules del LLM amb el diccionari, resolent flexions a lemes.

    Retorna:
        - lemes_trobats: conjunt de lemes del diccionari que coincideixen
        - no_trobades: paraules del LLM que no s'han pogut resoldre
    """
    lemes_trobats = set()
    no_trobades = []

    for paraula in paraules_llm:
        paraula_norm = Diccionari.normalitzar_paraula(paraula)

        # 1. És directament un lema del diccionari?
        if paraula_norm in lemes_diccionari:
            lemes_trobats.add(paraula_norm)
            continue

        # 2. És una flexió? Resolem al(s) lema(es)
        lemes_possibles = diccionari.lemes(paraula_norm)
        if lemes_possibles:
            lemes_valids = lemes_possibles & lemes_diccionari
            if lemes_valids:
                lemes_trobats.update(lemes_valids)
                continue

        # 3. No trobada
        no_trobades.append(paraula)

    return lemes_trobats, no_trobades


# =============================================================================
# PAS 3: Puntuar paraules en lots amb LLM
# =============================================================================

PROMPT_PUNTUAR = """Puntua del 0 al 10 la proximitat semàntica de cadascuna d'aquestes paraules catalanes amb "{paraula}".

Escala:
0 = cap relació semàntica
1-2 = relació molt indirecta
3-4 = relació indirecta però existent
5-6 = relació clara
7-8 = molt relacionades
9 = quasi-sinònim o relació directíssima
10 = sinònim exacte

Paraules a puntuar:
{llista_paraules}

Respon NOMÉS amb el format (una línia per paraula, sense cap altra text):
paraula:puntuació"""


def puntuar_lot(
    client: OpenAI,
    paraula_objectiu: str,
    lot: list[str],
    model: str = DEFAULT_MODEL,
) -> dict[str, float]:
    """Puntua un lot de paraules amb el LLM.

    Retorna dict paraula -> puntuació (0-10).
    """
    llista = ", ".join(lot)

    response = client.chat.completions.create(
        model=model,
        **_params_model(model),
        messages=[
            {
                "role": "system",
                "content": "Ets un lingüista expert en català. Segueixes les instruccions al peu de la lletra.",
            },
            {
                "role": "user",
                "content": PROMPT_PUNTUAR.format(
                    paraula=paraula_objectiu, llista_paraules=llista
                ),
            },
        ],
    )

    text = response.choices[0].message.content.strip()
    puntuacions: dict[str, float] = {}

    for linia in text.split("\n"):
        linia = linia.strip()
        if not linia or ":" not in linia:
            continue
        # Parsejar "paraula:puntuació" o "paraula: puntuació"
        parts = linia.rsplit(":", 1)
        if len(parts) != 2:
            continue
        paraula = parts[0].strip().lower()
        try:
            puntuacio = float(parts[1].strip())
            puntuacions[paraula] = puntuacio
        except ValueError:
            continue

    return puntuacions


def puntuar_paraules(
    client: OpenAI,
    paraula_objectiu: str,
    paraules: list[str],
    model: str = DEFAULT_MODEL,
    mida_lot: int = MIDA_LOT,
) -> dict[str, float]:
    """Puntua una llista de paraules en lots."""
    totes_puntuacions: dict[str, float] = {}
    total_lots = (len(paraules) + mida_lot - 1) // mida_lot

    for i in range(0, len(paraules), mida_lot):
        lot = paraules[i : i + mida_lot]
        num_lot = i // mida_lot + 1
        print(f"[LLM] Puntuant lot {num_lot}/{total_lots} ({len(lot)} paraules)...")
        puntuacions = puntuar_lot(client, paraula_objectiu, lot, model)
        totes_puntuacions.update(puntuacions)

        # Verificar paraules perdudes
        lot_set = set(lot)
        rebudes = set(puntuacions.keys())
        perdudes = lot_set - rebudes
        if perdudes:
            print(f"  ⚠ Paraules no puntuades: {perdudes}")

    print(
        f"[LLM] Total puntuades: {len(totes_puntuacions)} / {len(paraules)}"
    )
    return totes_puntuacions


# =============================================================================
# PAS 4: Combinar FastText + LLM per generar rànking final
# =============================================================================


def combinar_rankings(
    ranking_fasttext: dict[str, int],
    puntuacions_llm: dict[str, float],
    top_avaluat: int = TOP_A_AVALUAR,
    pes_llm: float = PES_LLM,
    pes_ft: float = PES_FASTTEXT,
) -> dict[str, int]:
    """Combina el rànking de FastText amb les puntuacions del LLM.

    Per a les paraules avaluades pel LLM:
      puntuació_combinada = pes_llm * (puntuació_llm normalitzada) + pes_ft * (puntuació_ft normalitzada)

    Per a la resta: mantenim l'ordre de FastText.
    """
    len(ranking_fasttext)

    # Trobar la paraula objectiu (posició 0 a FastText)
    paraula_objectiu = None
    for p, pos in ranking_fasttext.items():
        if pos == 0:
            paraula_objectiu = p
            break

    # Normalitzar posicions FastText a [0, 1] (0 = millor, 1 = pitjor)
    # Només per les paraules del top avaluat, excloent la paraula objectiu
    ft_scores = {}
    for paraula, pos in ranking_fasttext.items():
        if pos < top_avaluat and paraula != paraula_objectiu:
            # Invertir: posició 0 → score 1.0, posició top_avaluat → score 0.0
            ft_scores[paraula] = 1.0 - (pos / top_avaluat)

    # Paraules avaluades pel LLM (normalitzar 0-10 a 0-1)
    llm_scores = {}
    for paraula, puntuacio in puntuacions_llm.items():
        llm_scores[paraula] = puntuacio / 10.0

    # Totes les paraules candidates (unió de top FT + paraules LLM)
    paraules_avaluades = set(ft_scores.keys()) | set(llm_scores.keys())

    # Calcular puntuació combinada
    puntuacions_combinades: dict[str, float] = {}
    for paraula in paraules_avaluades:
        score_llm = llm_scores.get(paraula, 0.0)
        score_ft = ft_scores.get(paraula, 0.0)
        puntuacions_combinades[paraula] = pes_llm * score_llm + pes_ft * score_ft

    # Ordenar per puntuació combinada (descendent)
    top_ordenat = sorted(
        puntuacions_combinades.items(), key=lambda x: x[1], reverse=True
    )

    # Construir rànking final
    ranking_final: dict[str, int] = {}

    # 0. La paraula objectiu sempre va a la posició 0
    if paraula_objectiu:
        ranking_final[paraula_objectiu] = 0
    pos_actual = 1

    # 1. Afegir paraules avaluades, per ordre combinat
    for paraula, score in top_ordenat:
        if paraula == paraula_objectiu:
            continue
        ranking_final[paraula] = pos_actual
        pos_actual += 1

    # 2. Afegir la resta de paraules amb l'ordre de FastText
    restants = [
        (p, pos)
        for p, pos in ranking_fasttext.items()
        if p not in ranking_final
    ]
    restants.sort(key=lambda x: x[1])
    for paraula, _ in restants:
        ranking_final[paraula] = pos_actual
        pos_actual += 1

    return ranking_final


# =============================================================================
# Cache per evitar crides repetides
# =============================================================================


def carregar_cache_llm(paraula: str) -> dict | None:
    """Carrega resultats LLM cachejats per una paraula."""
    cache_path = LLM_CACHE_DIR / f"{paraula}.json"
    if cache_path.exists():
        with open(cache_path, encoding="utf-8") as f:
            return json.load(f)
    return None


def guardar_cache_llm(paraula: str, data: dict):
    """Guarda resultats LLM al cache."""
    LLM_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = LLM_CACHE_DIR / f"{paraula}.json"
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# =============================================================================
# Pipeline principal
# =============================================================================


def pipeline_llm(
    paraula_objectiu: str,
    diccionari: Diccionari,
    model_ft,
    client: OpenAI,
    model_llm: str = DEFAULT_MODEL,
    top_avaluar: int = TOP_A_AVALUAR,
    mida_lot: int = MIDA_LOT,
    pes_llm: float = PES_LLM,
    pes_ft: float = PES_FASTTEXT,
    usar_cache: bool = True,
    filtre_creuat: bool = False,
) -> dict[str, int]:
    """Pipeline complet: FastText + generació LLM + puntuació LLM → rànking final."""

    lemes = diccionari.totes_les_lemes(freq_min=20)
    lemes_set = set(lemes)

    # --- Pas 0: Rànking base amb FastText ---
    print(f"\n{'='*60}")
    print(f"Pas 0: Rànking FastText per '{paraula_objectiu}'")
    print(f"{'='*60}")

    filtre_kwargs = {}
    if filtre_creuat:
        filtre_kwargs = {"filtre_coherencia": True, "n_core": 15, "factor_penalitzacio": 0.1}
        print("Filtre creuat OpenAI activat.")

    ranking_ft = calcular_ranking_complet(paraula_objectiu, lemes, model_ft, **filtre_kwargs)
    print(f"Rànking FastText: {len(ranking_ft)} paraules")

    # --- Comprovar cache ---
    cache_data = None
    if usar_cache:
        cache_data = carregar_cache_llm(paraula_objectiu)

    paraules_generades_llm = None
    lemes_llm = None
    puntuacions_llm = None

    if cache_data:
        print(f"\n[Cache] Trobat cache per '{paraula_objectiu}'")
        paraules_generades_llm = cache_data.get("paraules_generades", [])
        lemes_llm = set(cache_data.get("lemes_trobats", []))
        puntuacions_llm = cache_data.get("puntuacions", {})
        print(f"  Paraules generades: {len(paraules_generades_llm)}")
        print(f"  Lemes trobats: {len(lemes_llm)}")
        print(f"  Puntuacions: {len(puntuacions_llm)}")
    
    if not puntuacions_llm:
        # --- Pas 1: Generar paraules amb LLM ---
        print(f"\n{'='*60}")
        print(f"Pas 1: Generant paraules amb LLM ({model_llm})")
        print(f"{'='*60}")
        paraules_generades_llm = generar_paraules_llm(client, paraula_objectiu, model_llm)

        # --- Pas 2: Creuar amb diccionari ---
        print(f"\n{'='*60}")
        print("Pas 2: Creuant amb diccionari")
        print(f"{'='*60}")
        lemes_llm, no_trobades = creuar_amb_diccionari(
            paraules_generades_llm, diccionari, lemes_set
        )
        print(f"Lemes trobats al diccionari: {len(lemes_llm)}")
        print(f"Paraules no trobades: {len(no_trobades)}")
        if no_trobades:
            print(f"  Exemples no trobades: {no_trobades[:20]}")

        # Mostrar lemes LLM que FastText tenia lluny
        injectades = []
        for lema in lemes_llm:
            pos_ft = ranking_ft.get(lema, -1)
            if pos_ft >= top_avaluar:
                injectades.append((lema, pos_ft))
        if injectades:
            injectades.sort(key=lambda x: x[1])
            print("\nParaules LLM que FastText tenia lluny (injectades al top):")
            for lema, pos in injectades[:30]:
                print(f"  {lema}: posició FT {pos}")

        # --- Pas 3: Puntuar el top ---
        print(f"\n{'='*60}")
        print(f"Pas 3: Puntuant top {top_avaluar} amb LLM")
        print(f"{'='*60}")

        # Construir pool: top FT + paraules LLM injectades
        top_ft = [p for p, pos in sorted(ranking_ft.items(), key=lambda x: x[1]) if pos < top_avaluar]
        pool = list(dict.fromkeys(top_ft + list(lemes_llm)))  # Sense duplicats, mantenint ordre
        pool = [p for p in pool if p != paraula_objectiu]  # Treure la paraula objectiu

        print(f"Pool a puntuar: {len(pool)} paraules ({len(top_ft)} top FT + {len(lemes_llm)} LLM)")
        puntuacions_llm = puntuar_paraules(client, paraula_objectiu, pool, model_llm, mida_lot)

        # --- Guardar cache ---
        guardar_cache_llm(paraula_objectiu, {
            "paraula": paraula_objectiu,
            "model_llm": model_llm,
            "paraules_generades": paraules_generades_llm,
            "lemes_trobats": list(lemes_llm),
            "no_trobades": no_trobades,
            "puntuacions": puntuacions_llm,
        })

    # --- Pas 4: Combinar ---
    print(f"\n{'='*60}")
    print(f"Pas 4: Combinant rànkings (LLM={pes_llm}, FT={pes_ft})")
    print(f"{'='*60}")

    ranking_final = combinar_rankings(
        ranking_ft, puntuacions_llm, top_avaluar, pes_llm, pes_ft
    )

    return ranking_final


# =============================================================================
# Comparació de rànkings
# =============================================================================


def comparar_rankings(
    ranking_ft: dict[str, int],
    ranking_final: dict[str, int],
    paraula_objectiu: str,
    top_n: int = 100,
):
    """Mostra comparació entre rànking FastText i rànking final."""
    print(f"\n{'='*60}")
    print(f"Comparació top {top_n} per '{paraula_objectiu}'")
    print(f"{'='*60}")

    # Top N del rànking final
    top_final = sorted(
        [(p, pos) for p, pos in ranking_final.items() if pos < top_n],
        key=lambda x: x[1],
    )

    print(f"\n{'Pos':>4} {'Paraula':<20} {'Pos FT':>7} {'Canvi':>8}")
    print("-" * 45)
    for paraula, pos_final in top_final:
        pos_ft = ranking_ft.get(paraula, -1)
        if pos_ft == -1:
            canvi = "NOVA"
        elif pos_ft == pos_final:
            canvi = "="
        else:
            diff = pos_ft - pos_final
            canvi = f"+{diff}" if diff > 0 else str(diff)
        print(f"{pos_final:>4} {paraula:<20} {pos_ft:>7} {canvi:>8}")


# =============================================================================
# CLI
# =============================================================================


def main():
    parser = argparse.ArgumentParser(
        description="Genera rànkings semàntics combinant FastText + LLM."
    )
    parser.add_argument("--paraula", type=str, required=True, help="Paraula objectiu")
    parser.add_argument(
        "--model-llm", type=str, default=DEFAULT_MODEL, help=f"Model LLM (defecte: {DEFAULT_MODEL})"
    )
    parser.add_argument(
        "--top", type=int, default=TOP_A_AVALUAR, help=f"Quantes paraules del top avaluar (defecte: {TOP_A_AVALUAR})"
    )
    parser.add_argument(
        "--lot", type=int, default=MIDA_LOT, help=f"Mida del lot per puntuar (defecte: {MIDA_LOT})"
    )
    parser.add_argument(
        "--pes-llm", type=float, default=PES_LLM, help=f"Pes del LLM al rànking (defecte: {PES_LLM})"
    )
    parser.add_argument(
        "--pes-ft", type=float, default=PES_FASTTEXT, help=f"Pes de FastText al rànking (defecte: {PES_FASTTEXT})"
    )
    parser.add_argument(
        "--output", type=str, help="Fitxer de sortida (defecte: data/words/<paraula>.json)"
    )
    parser.add_argument(
        "--no-cache", action="store_true", help="No utilitzar cache LLM"
    )
    parser.add_argument(
        "--filtre-creuat", action="store_true", help="Aplicar filtre creuat OpenAI al rànking FastText base"
    )
    parser.add_argument(
        "--compara", action="store_true", help="Mostra comparació amb el rànking FastText"
    )
    parser.add_argument(
        "--freq-min", type=int, default=20, help="Freqüència mínima del diccionari"
    )

    args = parser.parse_args()

    # Carregar diccionari
    print("Carregant diccionari...")
    dicc = Diccionari.obtenir_diccionari(freq_min=args.freq_min)

    # Carregar FastText
    print("Carregant model FastText...")
    model_ft = carregar_model_fasttext()

    # Client OpenAI (per LLM)
    client = obtenir_client_openai()

    # Suport per múltiples paraules separades per comes
    paraules = [p.strip() for p in args.paraula.split(",") if p.strip()]

    for idx, paraula in enumerate(paraules):
        if len(paraules) > 1:
            print(f"\n{'#'*60}")
            print(f"# Paraula {idx+1}/{len(paraules)}: {paraula}")
            print(f"{'#'*60}")

        # Executar pipeline
        ranking_final = pipeline_llm(
            paraula_objectiu=paraula,
            diccionari=dicc,
            model_ft=model_ft,
            client=client,
            model_llm=args.model_llm,
            top_avaluar=args.top,
            mida_lot=args.lot,
            pes_llm=args.pes_llm,
            pes_ft=args.pes_ft,
            usar_cache=not args.no_cache,
            filtre_creuat=args.filtre_creuat,
        )

        # Guardar
        output_path = args.output if (args.output and len(paraules) == 1) else f"data/words/{paraula}.json"
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(ranking_final, f, ensure_ascii=False, indent=2)
        print(f"\nRànking guardat a {output_path}")

        # Comparació opcional
        if args.compara:
            lemes = dicc.totes_les_lemes(freq_min=args.freq_min)
            ranking_ft = calcular_ranking_complet(paraula, lemes, model_ft)
            comparar_rankings(ranking_ft, ranking_final, paraula)


if __name__ == "__main__":
    main()
