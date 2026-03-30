import argparse
import glob
import importlib.util
import json
import os
import sys
from typing import Any

# Normal import of the extractor module (sibling in the same folder)
import extract_wiktionary_def as extractor_mod


def discover_lemmas_from_diccionari(diccionari_path: str) -> list[str]:
    """Load lemmas from data/diccionari.json using Diccionari.load."""
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    dic_module_path = os.path.join(repo_root, 'diccionari.py')
    spec = importlib.util.spec_from_file_location('diccionari_mod', dic_module_path)
    dic_mod = importlib.util.module_from_spec(spec)
    if spec.loader is None:
        raise RuntimeError('Cannot load diccionari module')
    spec.loader.exec_module(dic_mod)
    Diccionari = getattr(dic_mod, 'Diccionari')
    dic = Diccionari.load(diccionari_path)
    # Use all lemmas present in canoniques
    return sorted(dic.canoniques.keys())


def read_lemmas_file(path: str) -> list[str]:
    with open(path, encoding='utf-8') as f:
        data = f.read()
    try:
        j = json.loads(data)
        if isinstance(j, dict) and 'lemmas' in j and isinstance(j['lemmas'], list):
            return [str(x) for x in j['lemmas']]
        elif isinstance(j, list):
            return [str(x) for x in j]
    except Exception:
        pass
    # Fallback: one lemma per line
    return [line.strip() for line in data.splitlines() if line.strip()]


def write_definitions(output_dir: str, lemma: str, sections: list[dict[str, Any]]) -> str:
    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, f"{lemma}.definicions.json")
    payload = {
        'entry': lemma,
        'sections': sections,
    }
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return out_path


def build_list_definitions(wiktionary_dump_path: str, word_list: list[str]) -> dict[str, Any]:
    """Return a mapping lemma -> sections by streaming the dump once.
    Uses extractor_mod.iter_pages(wiktionary_dump_path) and processes only titles in word_list.
    """
    wanted = set(word_list)
    out: dict[str, Any] = {lemma: [] for lemma in wanted}
    for title, text in extractor_mod.iter_pages(wiktionary_dump_path):
        if title in wanted:
            print (f"Extracting definitions for: {title}")
            section_text = extractor_mod.extract_catalan_section(text)
            if not section_text:
                continue
            combined = extractor_mod.extract_defs_and_synonyms(section_text, with_examples=True)
            out[title] = [combined]
    return out


def main():
    parser = argparse.ArgumentParser(description='Build definicions.json per lemma using Catalan Wiktionary dump.')
    parser.add_argument('--dump', default=os.path.join('data', 'cawiktionary.xml'), help='Path to Wiktionary XML dump (default: data/cawiktionary.xml)')
    parser.add_argument('--lemmas', help='Path to a file containing lemmas (JSON list or one-per-line). If omitted, derive from data/diccionari.json')
    parser.add_argument('--limit', type=int, default=None, help='Limit number of lemmas to process (for testing).')
    parser.add_argument('--output', default=os.path.join('data', 'definicions.json'), help='Output JSON path for consolidated definitions (default: data/definicions.json).')
    parser.add_argument('--notfound', default=os.path.join('data', 'notfound.definitions.txt'), help='Path to write lemmas without definitions (default: data/notfound.definitions.txt).')
    args = parser.parse_args()

    diccionari_json = os.path.join('data', 'diccionari.json')
    if args.lemmas:
        lemmas = read_lemmas_file(args.lemmas)
    else:
        lemmas = discover_lemmas_from_diccionari(diccionari_json)
    if args.limit:
        lemmas = lemmas[:args.limit]

    print(f"Processing {len(lemmas)} lemmas...")
    processed = 0
    failed: list[str] = []
    # Build the mapping using the helper
    try:
        defs_map = build_list_definitions(args.dump, lemmas)
    except Exception as e:
        print(f"Error building definitions list: {e}")
        sys.exit(1)

    # Consolidate into a single JSON: only include lemmas with non-empty sections
    consolidated: dict[str, Any] = {}
    notfound: list[str] = []
    for lemma in lemmas:
        try:
            sections_raw = defs_map.get(lemma, [])
            if not sections_raw:
                notfound.append(lemma)
                continue
            # Normalize for JSON: ensure consistent shape
            sections: list[dict[str, Any]] = []
            for sec in sections_raw:
                pos = sec.get('pos')
                syns = sec.get('synonyms', [])
                defs_norm = []
                for d in sec.get('definitions', []):
                    if isinstance(d, dict):
                        defs_norm.append({'text': d.get('def', ''), 'examples': d.get('examples', [])})
                    else:
                        defs_norm.append({'text': str(d)})
                # Skip sections with no definitions
                if defs_norm:
                    sections.append({'pos': pos, 'definitions': defs_norm, 'synonyms': syns})
            if sections:
                consolidated[lemma] = sections
                processed += 1
            else:
                notfound.append(lemma)
        except Exception as e:
            print(f"Error processing '{lemma}': {e}")
            failed.append(lemma)

    # Write consolidated JSON
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump({'entries': consolidated}, f, ensure_ascii=False, indent=2)
    print(f"Wrote consolidated definitions to: {args.output}")

    # Write notfound list
    if notfound or failed:
        os.makedirs(os.path.dirname(args.notfound), exist_ok=True)
        with open(args.notfound, 'w', encoding='utf-8') as f:
            # notfound first, then failed entries marked
            for lemma in notfound:
                f.write(f"{lemma}\n")
            for lemma in failed:
                f.write(f"{lemma} [ERROR]\n")
        print(f"Wrote not-found list to: {args.notfound} ({len(notfound)} not found, {len(failed)} errors)")

    print(f"Done. Included: {processed}. Not found: {len(notfound)}. Errors: {len(failed)}")


if __name__ == '__main__':
    main()

