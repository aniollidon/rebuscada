import argparse
import re
import sys
import os
from typing import List, Optional
from collections import Counter, defaultdict

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
    "li","ens","us","vos","els","les","ho","lo","la","ne","hi", "per", "pel", "pels",
    "no","sí","ja","també","doncs","donc","però","sinó","tanmateix","encara","només","sols",
    "dins","fora","sobre","davall","sovint","damunt","a","la","el","del","de","les","als", "l", "n", "d", 
    "ésser", "color", "després", "forma", "diverses", "divers", "quan", "dimensions", "conté",
    "contenir", "tipus", "varietat", "varietats", "seu", "seus", "mateix", "mateixa", "mateixos", "mateixes",
    "part", "parts", "funció", "funcions", "són", "estat", "situat", "situada",
    "situats", "situades", "constitueix", "constituir", "inclou", "incloure", "inclouen", "incloent",
    "forma","formes","fins","finalment","això","allò","aquest","aquesta","aquests","aquestes",
    "aquell","aquella","aquells","aquelles","alguns","algunes","altres","altres","cada","cada",
    "cert","certa","certs","certes","diversos","diverses","moltíssim","moltíssima","moltíssims","moltíssimes",
    "poquissim","poquíssima","poquíssims","poquíssimes","qualsevol","qualsevol","tothom","ningú",
    "primer","primera","primers","primeres","segon","segona","segons","segones",
    "tercer","tercera","tercers","terceres", "últim","última","últims","últimes",
    "darrer","darrera","darrers","darreres", "gran","gran","grans","gros","grossa","grossos","grosses",
    "petit","petita","petits","petites","alt","alta","alts","altes","baix","baixa","baixos","baixes",
    "nou","nova","nous","noves","vell","vella","vells","velles",
    "bo","bona","bons","bones","dolent","dolenta","dolents","dolentes",
    "bé","malament","moltíssim","moltíssima","moltíssims","moltíssimes",
    "poc","poca","pocs","poques", "mica", "semblant", "varietat", "tipus", "classe", "classes", "categoria", "categories",
    "posar","posat","posada","posats","posades", "fer","fet","feta","fets","fetes",
    "estar","estat","estada","estats","estades", "anar","anat","anada","anats","anades",
    "venir","vingut","vinguda","vinguts","vingudes", "donar","donat","donada","donats","donades",
    "tenir","tingut","tinguda","tinguts","tingudes", "haver","hagut","haguada","haguts","hagudes",
    "fer","fa","fan","feia","feien","fet","feta","fets","fetes",
    "cosa","coses","assumpte","assumptes","element","elements","factor","factors",
    "aspecte","aspectes","punt","punts","detall","detalls","tema","temes",
    "qüestió","qüestions","problema","problemes","situació","situacions","condició","condicions",
    "capacitat","capacitats","possibilitat","possibilitats","funció","funcions","objectiu","objectius",
    "finalitat","finalitats",

]))

# Very small set of frequent verbs or auxiliaries to drop in fallback mode
CAT_COMMON_VERBS = set(map(str.lower, [
    "ser","és","són","estar","tenir","fer","dir","haver","poder","anar","venir","donar",
    "ocupar","ocupa","ocupen","ocupava","ocupat","ocupada",
]))

TOKEN_RE = re.compile(r"[\wÀ-ÖØ-öø-ÿ'·-]+", re.UNICODE)


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


def extract_keywords_rake(text: str, min_chars: int = 3) -> List[str]:
    """
    Implementation of RAKE (Rapid Automatic Keyword Extraction).
    Returns a list of unique words found in the top ranked phrases.
    """
    # 1. Split into phrases by punctuation
    phrases = re.split(r'[.!?,;:\t\n\r\(\)\[\]\{\}]', text)
    
    # 2. Generate candidate keywords (sequences of non-stopwords)
    candidates = []
    for phrase in phrases:
        phrase_tokens = tokenize(phrase)
        current_candidate = []
        for token in phrase_tokens:
            # Filter: stopwords, short words, numbers
            if is_stop(token) or len(token) < min_chars or token.isnumeric():
                if current_candidate:
                    candidates.append(current_candidate)
                    current_candidate = []
            else:
                current_candidate.append(token)
        if current_candidate:
            candidates.append(current_candidate)
            
    # 3. Calculate word scores
    word_freq = Counter()
    word_degree = defaultdict(int)
    
    for candidate in candidates:
        list_len = len(candidate)
        # RAKE metric: degree(w) = sum of lengths of candidates containing w
        # (co-occurrence count + self-occurrence)
        for word in candidate:
            word_lower = word.lower()
            word_freq[word_lower] += 1
            word_degree[word_lower] += list_len
            
    # 4. Calculate candidate scores
    candidate_scores = {}
    for candidate in candidates:
        score = 0
        for word in candidate:
            w = word.lower()
            if word_freq[w] > 0:
                score += word_degree[w] / word_freq[w]
        
        cand_str = " ".join(candidate)
        candidate_scores[cand_str] = score
        
    # 5. Sort by score
    sorted_candidates = sorted(candidate_scores.items(), key=lambda x: x[1], reverse=True)
    
    # 6. Flatten to unique words preserving rank order
    final_words = []
    seen = set()
    for cand_str, score in sorted_candidates:
        # We want the original casing? RAKE usually works on lower, but we have tokens.
        # The tokens in candidates are original case from tokenize().
        for word in cand_str.split():
            if word.lower() not in seen:
                final_words.append(word)
                seen.add(word.lower())
                
    return final_words



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
