import argparse
import json
import os

# inclou directori parent al PATH
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from diccionari import Diccionari
from proximitat import calcular_similitud_cosinus, carregar_model_fasttext


def combinar_vectors(model, paraula: str, contexts: list[str], pes_context: float) -> list[float]:
    """Combina el vector de la paraula amb els vectors de frase del context.

    - `pes_context` s'aplica a cada context; si hi ha múltiples, es fa mitjana.
    """
    v_paraula = model.get_word_vector(paraula)
    if not contexts:
        return v_paraula
    # Calcular vector mitjà del context
    v_context_total = None
    n = 0
    for ctx in contexts:
        if not ctx:
            continue
        v_ctx = model.get_sentence_vector(ctx)
        if v_context_total is None:
            v_context_total = v_ctx
        else:
            v_context_total += v_ctx
        n += 1
    if n == 0:
        return v_paraula
    v_context_promig = v_context_total / n
    # Combinar amb pes menor pel context
    return v_paraula + pes_context * v_context_promig


def calcular_ranking_complet_amb_context(paraula_objectiu: str, diccionari: list[str], model,
                                         contexts: list[str], pes_context: float):
    """Calcula el rànquing complet de paraules respecte a la combinació paraula+context."""
    print(f"Calculant rànquing avançat per a: '{paraula_objectiu}' amb context...")
    v_obj = combinar_vectors(model, paraula_objectiu, contexts, pes_context)

    similituds = []
    for paraula in diccionari:
        v_paraula = model.get_word_vector(paraula)
        sim = calcular_similitud_cosinus(v_obj, v_paraula)
        similituds.append((paraula, sim))

    similituds.sort(key=lambda x: x[1], reverse=True)
    # Diccionari de rànquing: posició a la llista ordenada (sense límit)
    ranking_dict = {paraula: i for i, (paraula, _) in enumerate(similituds)}
    return ranking_dict


def main():
    parser = argparse.ArgumentParser(
        description="Genera rànquings avançats (paraula + context) en JSON, sense límit. Opcionalment, mode test per imprimir top-N.")
    parser.add_argument("--paraula", type=str, required=True,
                        help="Paraula objectiu (o llista separada per comes) per calcular rànquings")
    parser.add_argument("--context", type=str, action="append", default=[],
                        help="Text de context (pot repetir-se). Sovint definició normalitzada.")
    parser.add_argument("--pes-context", type=float, default=0.3,
                        help="Pes relatiu del vector de context (default: 0.3)")
    parser.add_argument("--output", type=str, required=False,
                        help="Fitxer o directori de sortida. Per defecte: data/words/[PARAULA].json")
    parser.add_argument("--freq-min", type=int, default=20,
                        help="Freqüència mínima per filtrar paraules del diccionari")
    parser.add_argument("--test", type=int, default=None,
                        help="Si s'especifica, imprimeix les TOP-N paraules separades per comes en lloc de generar fitxers")
    # Eliminat el límit: retornem rànquing complet com a generate.py

    args = parser.parse_args()

    print("Carregant i generant diccionari...")
    dicc = Diccionari.obtenir_diccionari(freq_min=args.freq_min)
    dicc.save("data/diccionari.json")
    print(f"Diccionari filtrat guardat a data/diccionari.json amb {len(dicc.canoniques)} lemes.")

    FT_MODEL = carregar_model_fasttext()
    paraules = dicc.totes_les_lemes(freq_min=args.freq_min)

    paraules_input = [p.strip() for p in args.paraula.split(',') if p.strip()]
    if not paraules_input:
        raise SystemExit("Cap paraula vàlida proporcionada a --paraula")

    for p in paraules_input:
        if args.output:
            if args.output.endswith('.json') and len(paraules_input) == 1:
                output_path = args.output
            else:
                base_dir = args.output
                os.makedirs(base_dir, exist_ok=True)
                output_path = os.path.join(base_dir, f"{p}.json")
        else:
            os.makedirs("data/words", exist_ok=True)
            output_path = f"data/words/{p}.json"

        print(f"Calculant rànquing complet per a: {p}")
        ranking = calcular_ranking_complet_amb_context(
            p, paraules, FT_MODEL, args.context, args.pes_context)

        if args.test is not None:
            # En mode test, imprimim les TOP-N paraules separades per comes i no escrivim fitxer
            # El diccionari de rànquing és {paraula: posicio}; ordenem per posició ascendent
            top_items = sorted(ranking.items(), key=lambda kv: kv[1])[:args.test]
            top_words = [w for w, _ in top_items]
            print(",".join(top_words))
        else:
            print(f"Guardant rànquing a {output_path}")
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(ranking, f, ensure_ascii=False, indent=2)

    print("Fet!")


if __name__ == "__main__":
    main()
