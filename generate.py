
import argparse
import json
from proximitat import carregar_model_fasttext, calcular_ranking_complet
from diccionari import Diccionari
from dotenv import load_dotenv

# Carregar variables d'entorn del fitxer .env
load_dotenv()

# Importació lazy de proximitatSOTA per evitar errors si no s'utilitza
_proximitat_sota_module = None
_proximitat_openai_module = None

def _get_proximitat_sota():
    global _proximitat_sota_module
    if _proximitat_sota_module is None:
        try:
            import proximitatSOTA
            _proximitat_sota_module = proximitatSOTA
        except ImportError as e:
            print(f"Error important proximitatSOTA: {e}")
            print("Instal·la les dependències necessàries amb:")
            print("  pip install sentence-transformers torch")
            print("  pip install \"numpy<2\"")
            raise
    return _proximitat_sota_module

def _get_proximitat_openai():
    global _proximitat_openai_module
    if _proximitat_openai_module is None:
        try:
            import proximitatOpenAI
            _proximitat_openai_module = proximitatOpenAI
        except ImportError as e:
            print(f"Error important proximitatOpenAI: {e}")
            print("Instal·la les dependències necessàries amb:")
            print("  pip install openai")
            raise
    return _proximitat_openai_module

def main():
    parser = argparse.ArgumentParser(description="Genera fitxers de rànquing de paraules en format JSON.")
    parser.add_argument("--paraula", type=str, required=False, help="Paraula o llista de paraules separades per comes per calcular els rànquings")
    parser.add_argument("--random", type=int, required=False, help="Nombre de paraules aleatòries per generar rànquings")
    parser.add_argument("--output", type=str, required=False, help="Fitxer de sortida per al rànquing (JSON). Per defecte: data/words/[PARAULA].json")
    parser.add_argument("--freq-min", type=int, default=20, help="Freqüència mínima per filtrar paraules")
    parser.add_argument("--freq-min-rand", type=int, default=-1, help="Freqüència mínima per proposar paraules aleatòries")
    parser.add_argument("--algorisme", type=str, choices=['fasttext', 'sota', 'openai'], default='fasttext', help="Algorisme a utilitzar: 'fasttext', 'sota' (Sentence Transformers) o 'openai' (text-embedding-3-large)")

    args = parser.parse_args()

    if args.freq_min_rand == -1:
        args.freq_min_rand = args.freq_min

    if not args.paraula and not args.random:
        parser.error("Cal especificar --paraula o --random [NUM]")

    print("Carregant i generant diccionari...")
    dicc = Diccionari.obtenir_diccionari(freq_min=args.freq_min)
    dicc.save("data/diccionari.json")
    print(f"Diccionari filtrat guardat a data/diccionari.json amb {len(dicc.canoniques)} lemes.")

    # Carregar el model segons l'algorisme escollit
    if args.algorisme == 'fasttext':
        print("Utilitzant algorisme FastText...")
        MODEL = carregar_model_fasttext()
        calcular_ranking_fn = calcular_ranking_complet
    elif args.algorisme == 'sota':
        print("Utilitzant algorisme SOTA (Sentence Transformers)...")
        proximitat_sota = _get_proximitat_sota()
        MODEL = proximitat_sota.carregar_model_sentence_transformer()
        calcular_ranking_fn = proximitat_sota.calcular_ranking_complet
    else:  # openai
        print("Utilitzant algorisme OpenAI (text-embedding-3-large)...")
        proximitat_openai = _get_proximitat_openai()
        MODEL = None  # OpenAI no necessita carregar model localment
        calcular_ranking_fn = proximitat_openai.calcular_ranking_complet
    
    paraules = dicc.totes_les_lemes(freq_min=args.freq_min)

    # Si s'ha especificat --paraula (pot ser llista separada per comes)
    if args.paraula:
        paraules_input = [p.strip() for p in args.paraula.split(',') if p.strip()]
        if not paraules_input:
            print("Cap paraula vàlida proporcionada a --paraula")
        else:
            for p in paraules_input:
                if args.output:
                    # Si l'usuari ha passat un path que acaba amb .json i només hi ha una paraula, usem tal qual
                    if args.output.endswith('.json') and len(paraules_input) == 1:
                        output_path = args.output
                    else:
                        # Tractem output com a directori base
                        import os
                        base_dir = args.output
                        os.makedirs(base_dir, exist_ok=True)
                        output_path = os.path.join(base_dir, f"{p}.json")
                else:
                    import os
                    os.makedirs("data/words", exist_ok=True)
                    output_path = f"data/words/{p}.json"
                print(f"Calculant rànquing per a la paraula: {p}")
                if args.algorisme == 'openai':
                    ranking = calcular_ranking_fn(p, paraules)
                else:
                    ranking = calcular_ranking_fn(p, paraules, MODEL)
                print(f"Guardant rànquing a {output_path}")
                with open(output_path, "w", encoding="utf-8") as f:
                    json.dump(ranking, f, ensure_ascii=False, indent=2)
            print("Fet!")

    # Si s'ha especificat --random
    if args.random:
        import os
        os.makedirs("data/words", exist_ok=True)
        for i in range(args.random):
            paraula_random = dicc.obtenir_paraula_aleatoria(freq_min=args.freq_min_rand, seed=None)
            output_path = f"data/words/{paraula_random}.json"
            print(f"Calculant rànquing per a la paraula aleatòria: {paraula_random}")
            if args.algorisme == 'openai':
                ranking = calcular_ranking_fn(paraula_random, paraules)
            else:
                ranking = calcular_ranking_fn(paraula_random, paraules, MODEL)
            print(f"Guardant rànquing a {output_path}")
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(ranking, f, ensure_ascii=False, indent=2)
        print("Fet!")

if __name__ == "__main__":
    main()
