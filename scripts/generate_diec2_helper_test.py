import argparse
import json
import os
import sys
from typing import List, Dict, Any, Tuple

# Make repo root importable
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.extract_diec2_def import extract_diec2_definitions  # type: ignore
from scripts.clean_txt import concepts_from_text  # type: ignore
from proximitat import carregar_model_fasttext, calcular_similitud_cosinus
from diccionari import Diccionari

IGNORED_CATEGORY_TEXTS = {"lèxic comú", "lèxic general", "léxic general"}


def top_n_from_text_terms(terms: List[str],
                          model,
                          dicc_terms: List[str],
                          n: int) -> List[str]:
    """Compute top-N similar words using sentence vector of joined terms vs. dictionary words.
    This mirrors generate_advanced's ranking intent for multi-term input.
    """
    if not terms:
        return []
    sent = " ".join(terms)
    v_obj = model.get_sentence_vector(sent)
    sims: List[Tuple[str, float]] = []
    for w in dicc_terms:
        v_w = model.get_word_vector(w)
        sims.append((w, calcular_similitud_cosinus(v_obj, v_w)))
    sims.sort(key=lambda x: x[1], reverse=True)
    return [w for w, _ in sims[:n]]


def build_tests_for_definitions(entry: str, gen: int, model, dicc_terms: List[str], prefer_spacy: bool = True, include_categories: bool = False) -> Dict[str, Any]:
    defs = extract_diec2_definitions(entry)

    # Build definitions array with tests
    definitions: List[Dict[str, Any]] = []
    category_texts_order: List[str] = []
    seen_cats = set()

    for d in defs:
        text = d.get('text', '') or ''
        tokens = concepts_from_text(text, prefer_spacy=prefer_spacy, keep_case=True)
        test_list = top_n_from_text_terms(tokens, model, dicc_terms, gen)
        definitions.append({
            'text': text,
            'test': test_list,
            'num': d.get('num'),
            'subnum': d.get('subnum'),
            'morfologia': d.get('morfologia'),
            'phrase_made': d.get('phrase_made'),
            'categories': d.get('categories', []),
        })
        if include_categories:
            for cat in d.get('categories', []) or []:
                if not cat:
                    continue
                # Ignore LC / general lexicon
                if cat.strip().lower() in IGNORED_CATEGORY_TEXTS:
                    continue
                if cat not in seen_cats:
                    seen_cats.add(cat)
                    category_texts_order.append(cat)

    # Build category tests
    result: Dict[str, Any] = {
        'entry': entry,
        'definitions': definitions,
    }
    if include_categories:
        categories: List[Dict[str, Any]] = []
        for cat_text in category_texts_order:
            cat_tokens = concepts_from_text(cat_text, prefer_spacy=prefer_spacy, keep_case=True)
            cat_test = top_n_from_text_terms(cat_tokens, model, dicc_terms, gen)
            categories.append({'text': cat_text, 'test': cat_test})
        result['categories'] = categories
    return result


def main():
    parser = argparse.ArgumentParser(description='Genera proves de definicions DIEC2 + categories')
    parser.add_argument('--paraula', type=str, help='Entrada al DIEC2')
    parser.add_argument('--folder', type=str, help='Carpeta amb fitxers .json per processar')
    parser.add_argument('--gen', required=False, type=int, default=20, help='Nombre de paraules a generar per test')
    parser.add_argument('--freq-min', required=False, type=int, default=20, help='Freqüència mínima per filtrar diccionari')
    parser.add_argument('--no-spacy', action='store_true', help='Desactiva spaCy i usa el mode de reserva lleuger')
    parser.add_argument('--categories', action='store_true', help='Inclou el tractament de categories DIEC2')
    args = parser.parse_args()

    if not args.paraula and not args.folder:
        parser.error("Cal especificar --paraula o --folder")

    print("Carregant diccionari i model...")
    dicc = Diccionari.obtenir_diccionari(freq_min=args.freq_min)
    dicc_terms = dicc.totes_les_lemes(freq_min=args.freq_min)
    model = carregar_model_fasttext()
    print("Recursos carregats.")

    words_to_process = []
    if args.paraula:
        words_to_process.append(args.paraula)
    
    if args.folder:
        if not os.path.isdir(args.folder):
            print(f"Error: {args.folder} no és un directori.")
            sys.exit(1)
        for filename in os.listdir(args.folder):
            if filename.endswith(".json") and not filename.startswith("_"):
                word = os.path.splitext(filename)[0]
                words_to_process.append(word)
    
    # Remove duplicates
    words_to_process = sorted(list(set(words_to_process)))
    
    out_dir = os.path.join('data', 'words', 'deftests')
    os.makedirs(out_dir, exist_ok=True)

    prefer_spacy = not args.no_spacy

    for word in words_to_process:
        out_path = os.path.join(out_dir, f"{word}.deftest.json")
        if os.path.exists(out_path):
            print(f"Saltant {word}: ja existeix a {out_path}")
            continue

        print(f"Processant: {word}")
        try:
            result = build_tests_for_definitions(
                word,
                args.gen,
                model,
                dicc_terms,
                prefer_spacy=prefer_spacy,
                include_categories=args.categories,
            )
            
            with open(out_path, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            print(f"  Desat a {out_path}")
        except Exception as e:
            print(f"  [ERROR] Error processant '{word}': {e}")


if __name__ == '__main__':
    main()
