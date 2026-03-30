import argparse
import json
import os
import sys
from typing import Any

# Make repo root importable
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from diccionari import Diccionari
from proximitatOpenAI import (
    calcular_similitud_cosinus,
    carregar_cache_embeddings,
    guardar_cache_embeddings,
    obtenir_client_openai,
    obtenir_embedding,
    obtenir_embeddings_batch,
)
from scripts.clean_txt import concepts_from_text, extract_keywords_rake  # type: ignore
from scripts.extract_diec2_def import extract_diec2_definitions  # type: ignore

IGNORED_CATEGORY_TEXTS = {"lèxic comú", "lèxic general", "léxic general"}


def top_n_from_text_full(text: str,
                         client,
                         cache: dict[str, list[float]],
                         dicc_terms: list[str],
                         n: int) -> list[str]:
    """Compute top-N similar words using OpenAI embeddings of full text vs. dictionary words.
    Uses the complete definition text without filtering.
    """
    if not text or not text.strip():
        return []
    
    v_obj = obtenir_embedding(text, client, cache)
    
    # Obtenir embeddings del diccionari en batch per eficiència
    embeddings_dict = obtenir_embeddings_batch(dicc_terms, client, cache)
    
    sims: list[tuple[str, float]] = []
    for w in dicc_terms:
        if w in embeddings_dict:
            v_w = embeddings_dict[w]
            sims.append((w, calcular_similitud_cosinus(v_obj, v_w)))
    sims.sort(key=lambda x: x[1], reverse=True)
    return [w for w, _ in sims[:n]]


def top_n_from_text_terms(terms: list[str],
                          client,
                          cache: dict[str, list[float]],
                          dicc_terms: list[str],
                          n: int) -> list[str]:
    """Compute top-N similar words using OpenAI embeddings of joined terms vs. dictionary words.
    This mirrors generate_advanced's ranking intent for multi-term input.
    """
    if not terms:
        return []
    sent = " ".join(terms)
    v_obj = obtenir_embedding(sent, client, cache)
    
    # Obtenir embeddings del diccionari en batch per eficiència
    embeddings_dict = obtenir_embeddings_batch(dicc_terms, client, cache)
    
    sims: list[tuple[str, float]] = []
    for w in dicc_terms:
        if w in embeddings_dict:
            v_w = embeddings_dict[w]
            sims.append((w, calcular_similitud_cosinus(v_obj, v_w)))
    sims.sort(key=lambda x: x[1], reverse=True)
    return [w for w, _ in sims[:n]]


def build_tests_for_definitions(entry: str, gen: int, client, cache: dict[str, list[float]], dicc_terms: list[str], filter_mode: str = 'nofilter', include_categories: bool = False) -> dict[str, Any]:
    """Build test lists for definitions.
    
    Args:
        filter_mode: 'nofilter' (text complet), 'spacy' (filtra amb spaCy), 'rake' (algoritme RAKE)
    """
    defs = extract_diec2_definitions(entry)

    # Build definitions array with tests
    definitions: list[dict[str, Any]] = []
    category_texts_order: list[str] = []
    seen_cats = set()

    for d in defs:
        text = d.get('text', '') or ''
        
        # Generar test segons mode de filtratge
        if filter_mode == 'nofilter':
            test_list = top_n_from_text_full(text, client, cache, dicc_terms, gen)
        elif filter_mode == 'rake':
            tokens = extract_keywords_rake(text)
            test_list = top_n_from_text_terms(tokens, client, cache, dicc_terms, gen)
        elif filter_mode == 'spacy':
            tokens = concepts_from_text(text, prefer_spacy=True, keep_case=True)
            test_list = top_n_from_text_terms(tokens, client, cache, dicc_terms, gen)
        else:
            raise ValueError(f"Mode de filtratge desconegut: {filter_mode}")
        
        definitions.append({
            'text': text,
            'test': test_list,
            'num': d.get('num'),
            'subnum': d.get('subnum'),
            'morfologia': d.get('morfologia'),
            'phrase_made': d.get('phrase_made'),
            'categories': d.get('categories', []),
            'tags': d.get('tags', []),
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
    result: dict[str, Any] = {
        'entry': entry,
        'definitions': definitions,
    }
    if include_categories:
        categories: list[dict[str, Any]] = []
        for cat_text in category_texts_order:
            if filter_mode == 'nofilter':
                cat_test = top_n_from_text_full(cat_text, client, cache, dicc_terms, gen)
            elif filter_mode == 'rake':
                cat_tokens = extract_keywords_rake(cat_text)
                cat_test = top_n_from_text_terms(cat_tokens, client, cache, dicc_terms, gen)
            elif filter_mode == 'spacy':
                cat_tokens = concepts_from_text(cat_text, prefer_spacy=True, keep_case=True)
                cat_test = top_n_from_text_terms(cat_tokens, client, cache, dicc_terms, gen)
            else:
                raise ValueError(f"Mode de filtratge desconegut: {filter_mode}")
            categories.append({'text': cat_text, 'test': cat_test})
        result['categories'] = categories
    return result


def main():
    parser = argparse.ArgumentParser(description='Genera proves de definicions DIEC2 + categories')
    parser.add_argument('--paraula', type=str, help='Entrada al DIEC2')
    parser.add_argument('--folder', type=str, help='Carpeta amb fitxers .json per processar')
    parser.add_argument('--gen', required=False, type=int, default=20, help='Nombre de paraules a generar per test')
    parser.add_argument('--freq-min', required=False, type=int, default=20, help='Freqüència mínima per filtrar diccionari')
    parser.add_argument('--filter', type=str, choices=['nofilter', 'spacy', 'rake'], default='nofilter',
                        help='Mode de filtratge: nofilter (text complet), spacy (filtra amb spaCy), rake (algoritme RAKE). Per defecte: nofilter')
    parser.add_argument('--categories', action='store_true', help='Inclou el tractament de categories DIEC2')
    args = parser.parse_args()

    if not args.paraula and not args.folder:
        parser.error("Cal especificar --paraula o --folder")

    print("Carregant diccionari i client OpenAI...")
    dicc = Diccionari.obtenir_diccionari(freq_min=args.freq_min)
    dicc_terms = dicc.totes_les_lemes(freq_min=args.freq_min)
    client = obtenir_client_openai()
    cache = carregar_cache_embeddings()
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

    filter_mode_names = {
        'nofilter': 'text complet sense filtrar',
        'spacy': 'filtratge amb spaCy',
        'rake': 'algoritme RAKE'
    }

    for word in words_to_process:
        out_path = os.path.join(out_dir, f"{word}.deftest.json")
        if os.path.exists(out_path):
            print(f"Saltant {word}: ja existeix a {out_path}")
            continue

        print(f"Processant: {word}")
        print(f"Mode de filtratge: {filter_mode_names[args.filter]}")
        cache_inicial = len(cache)
        try:
            result = build_tests_for_definitions(
                word,
                args.gen,
                client,
                cache,
                dicc_terms,
                filter_mode=args.filter,
                include_categories=args.categories,
            )
            
            with open(out_path, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            print(f"  Desat a {out_path}")
            
            # Guardar cache si s'han afegit noves paraules
            if len(cache) > cache_inicial:
                guardar_cache_embeddings(cache)
                print(f"  Cache actualitzat amb {len(cache) - cache_inicial} nous embeddings")
        except Exception as e:
            print(f"  [ERROR] Error processant '{word}': {e}")


if __name__ == '__main__':
    main()

