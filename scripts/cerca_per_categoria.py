import argparse
import sys
import os
from typing import List, Dict, Tuple

# Make repo root importable
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from proximitatOpenAI import (
    obtenir_client_openai,
    carregar_cache_embeddings,
    obtenir_embedding,
    obtenir_embeddings_batch,
    calcular_similitud_cosinus,
    guardar_cache_embeddings
)
from diccionari import Diccionari


def trobar_paraules_categoria(categoria: str,
                               client,
                               cache: Dict[str, List[float]],
                               dicc_terms: List[str],
                               threshold: float = 0.5,
                               n: int = 100) -> List[Tuple[str, float]]:
    """Troba paraules similars a una categoria/concepte.
    
    Args:
        categoria: El concepte a buscar (ex: "planta", "color", "animal")
        client: Client OpenAI
        cache: Cache d'embeddings
        dicc_terms: Llista de paraules del diccionari
        threshold: Similitud mínima per incloure (0-1)
        n: Nombre màxim de resultats
        
    Returns:
        Llista de tuples (paraula, similitud) ordenades per similitud
    """
    print(f"Obtenint embedding per: '{categoria}'...")
    v_categoria = obtenir_embedding(categoria, client, cache)
    
    print(f"Comparant amb {len(dicc_terms)} paraules del diccionari...")
    embeddings_dict = obtenir_embeddings_batch(dicc_terms, client, cache)
    
    resultats: List[Tuple[str, float]] = []
    for w in dicc_terms:
        if w in embeddings_dict:
            sim = calcular_similitud_cosinus(v_categoria, embeddings_dict[w])
            if sim >= threshold:
                resultats.append((w, sim))
    
    resultats.sort(key=lambda x: x[1], reverse=True)
    return resultats[:n]


def main():
    parser = argparse.ArgumentParser(
        description='Cerca paraules similars a un concepte/categoria utilitzant embeddings d\'OpenAI'
    )
    parser.add_argument('concepte', type=str, help='Concepte o categoria a buscar (ex: "planta", "color", "animal")')
    parser.add_argument('--threshold', type=float, default=0.5,
                        help='Similitud mínima per incloure paraules (0-1). Per defecte: 0.5')
    parser.add_argument('--max', type=int, default=100,
                        help='Nombre màxim de resultats a mostrar. Per defecte: 100')
    parser.add_argument('--freq-min', type=int, default=20,
                        help='Freqüència mínima per filtrar diccionari. Per defecte: 20')
    parser.add_argument('--save', type=str,
                        help='Fitxer on desar els resultats (opcional)')
    args = parser.parse_args()

    print("=" * 60)
    print(f"Cercant paraules similars a: '{args.concepte}'")
    print(f"Threshold: {args.threshold}")
    print(f"Màxim resultats: {args.max}")
    print("=" * 60)
    
    # Carregar recursos
    print("\nCarregant diccionari i client OpenAI...")
    dicc = Diccionari.obtenir_diccionari(freq_min=args.freq_min)
    dicc_terms = dicc.totes_les_lemes(freq_min=args.freq_min)
    client = obtenir_client_openai()
    cache = carregar_cache_embeddings()
    cache_inicial = len(cache)
    print(f"Diccionari carregat: {len(dicc_terms)} paraules\n")
    
    # Buscar paraules similars
    resultats = trobar_paraules_categoria(
        args.concepte,
        client,
        cache,
        dicc_terms,
        threshold=args.threshold,
        n=args.max
    )
    
    # Guardar cache si s'han afegit nous embeddings
    if len(cache) > cache_inicial:
        guardar_cache_embeddings(cache)
        print(f"Cache actualitzat amb {len(cache) - cache_inicial} nous embeddings\n")
    
    # Mostrar resultats
    print("\n" + "=" * 60)
    print(f"RESULTATS: {len(resultats)} paraules trobades")
    print("=" * 60)
    
    if resultats:
        for i, (paraula, sim) in enumerate(resultats, 1):
            print(f"{i:3d}. {paraula:25s} (similitud: {sim:.4f})")
    else:
        print(f"No s'han trobat paraules amb similitud >= {args.threshold}")
    
    # Desar resultats si s'ha especificat
    if args.save:
        import json
        with open(args.save, 'w', encoding='utf-8') as f:
            json.dump([{"paraula": p, "similitud": s} for p, s in resultats],
                     f, ensure_ascii=False, indent=2)
        print(f"\nResultats desats a: {args.save}")


if __name__ == '__main__':
    main()
