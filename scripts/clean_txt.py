import argparse
import re
import sys
import os
from typing import List, Optional

# Allow importing from repo root if needed
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Optional spaCy load for better POS-based filtering
_SPACY_NLP = None

def _maybe_load_spacy(lang_model: str = "ca_core_news_sm"):
    global _SPACY_NLP
    if _SPACY_NLP is not None:
        return _SPACY_NLP
    try:
        import spacy  # type: ignore
        try:
            _SPACY_NLP = spacy.load(lang_model)
        except OSError:
            _SPACY_NLP = None
    except Exception:
        _SPACY_NLP = None
    return _SPACY_NLP

# A compact Catalan stopword list + frequent particles; extend as needed
CAT_STOPWORDS = set(map(str.lower, [
    "el","la","els","les","un","una","uns","unes","d","de","del","dels","al","als","a",
    "i","o","ni","per","perquè","perque","perqué","perqué?","per a","amb","sense","entre","contra",
    "en","sobre","sota","fins","des","durant","cap","que","què","qui","quan","on","com",
    "molt","molta","molts","moltes","poc","poca","pocs","poques","més","menys","tant","tanta","tants","tantes",
    "aquest","aquesta","aquests","aquestes","aquell","aquella","aquells","aquelles","allò","això","així",
    "jo","tu","ell","ella","nosaltres","vosaltres","ells","elles","me","em","m","te","t","se","s",
    "li","ens","us","vos","els","les","ho","lo","la","ne","hi",
    "no","sí","ja","també","doncs","donc","però","sinó","tanmateix","encara","només","sols",
    "dins","fora","sobre","davall","damunt","a","la","el","del","de","les","als",
]))

# Very small set of frequent verbs or auxiliaries to drop in fallback mode
CAT_COMMON_VERBS = set(map(str.lower, [
    "ser","és","són","estar","tenir","fer","dir","haver","poder","anar","venir","donar",
    "ocupar","ocupa","ocupen","ocupava","ocupat","ocupada",
]))

TOKEN_RE = re.compile(r"[\wÀ-ÖØ-öø-ÿ'-]+", re.UNICODE)


def tokenize(text: str) -> List[str]:
    return TOKEN_RE.findall(text)


def is_stop(token: str) -> bool:
    tl = token.lower()
    return tl in CAT_STOPWORDS or tl in CAT_COMMON_VERBS


def clean_with_spacy(text: str, keep_pos: Optional[set] = None, keep_case: bool = True) -> List[str]:
    nlp = _maybe_load_spacy()
    if not nlp:
        return clean_fallback(text, keep_case=keep_case)
    if keep_pos is None:
        keep_pos = {"NOUN", "PROPN", "ADJ"}
    doc = nlp(text)
    out: List[str] = []
    for tok in doc:
        if tok.is_punct or tok.is_space:
            continue
        if tok.like_num:
            continue
        if tok.pos_ not in keep_pos:
            continue
        t = tok.text if keep_case else tok.lemma_.lower() if tok.lemma_ != "" else tok.text.lower()
        if is_stop(t):
            continue
        out.append(t)
    return out


def clean_fallback(text: str, keep_case: bool = True) -> List[str]:
    toks = tokenize(text)
    out: List[str] = []
    for t in toks:
        if t.isnumeric():
            continue
        if is_stop(t):
            continue
        # Drop tokens that are just apostrophes or hyphens
        if set(t) <= set("'-"):
            continue
        # Heuristic: trim trailing punctuation already removed by regex
        out.append(t if keep_case else t.lower())
    return out


def concepts_from_text(text: str, prefer_spacy: bool = True, keep_case: bool = True) -> List[str]:
    if prefer_spacy and _maybe_load_spacy() is not None:
        return clean_with_spacy(text, keep_case=keep_case)
    return clean_fallback(text, keep_case=keep_case)


def main():
    parser = argparse.ArgumentParser(description="Neteja un text català i extreu conceptes (NOUN/ADJ).")
    parser.add_argument("--text", type=str, help="Text d'entrada a netejar.")
    parser.add_argument("--file", type=str, help="Fitxer de text d'entrada.")
    parser.add_argument("--no-spacy", action="store_true", help="No usar spaCy encara que estigui instal·lat.")
    parser.add_argument("--lower", action="store_true", help="Converteix tokens a minúscules.")

    args = parser.parse_args()

    if not args.text and not args.file:
        print("Cal especificar --text o --file", file=sys.stderr)
        sys.exit(2)

    if args.file:
        try:
            with open(args.file, "r", encoding="utf-8") as f:
                text = f.read().strip()
        except Exception as e:
            print(f"No s'ha pogut llegir el fitxer: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        text = args.text

    prefer_spacy = not args.no_spacy
    keep_case = not args.lower
    tokens = concepts_from_text(text, prefer_spacy=prefer_spacy, keep_case=keep_case)

    # Format com a l'exemple: [token1 token2 ...]
    print("[" + " ".join(tokens) + "]")


if __name__ == "__main__":
    main()
