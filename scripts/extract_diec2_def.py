import sys
import re
import html
import requests
from typing import Optional, List, Dict, Any
from bs4 import BeautifulSoup


BASE_URL = "https://dlc.iec.cat/Results"

# Map DIEC2 bracket tags (e.g., [AGP]) to category names
DIEC_TAG_MAP = {
    'AD': 'llenguatge administratiu',
    'AF': 'arts gràfiques',
    'AGA': 'agricultura',
    'AGF': 'ciència forestal',
    'AGP': 'pesca',
    'AGR': 'explotació animal',
    'AN': 'antropologia',
    'AQ': 'arquitectura',
    'AR': 'art',
    'BB': 'biblioteconomia',
    'BI': 'biologia',
    'BO': 'botànica en general',
    'BOB': 'fongs i líquens',
    'BOC': 'col·lectius vegetals',
    'BOI': 'plantes inferiors',
    'BOS': 'plantes superiors',
    'BOT': 'botànica',
    'CO': 'comunicació',
    'DE': 'defensa',
    'DR': 'dret',
    'ECO': 'oficines',
    'ECT': 'teoria econòmica',
    'ED': 'economia domèstica',
    'EE': 'enginyeria elèctrica',
    'EG': 'ecologia',
    'EI': 'enginyeria industrial general',
    'EL': 'enginyeria electrònica',
    'ENG': 'enginyeries',
    'FIA': 'astronomia',
    'FIF': 'física en general',
    'FIM': 'metrologia',
    'FIN': 'física nuclear',
    'FL': 'filologia',
    'FLL': 'literatura',
    'FS': 'filosofia',
    'GEO': 'geologia',
    'GG': 'geografia',
    'GL': 'geologia en general',
    'GLG': 'mineralogia en general',
    'GLM': 'minerals',
    'GLP': 'paleontologia',
    'HIA': 'arqueologia',
    'HIG': 'genealogia i heràldica',
    'HIH': 'història en general',
    'HO': 'hoteleria',
    'IMF': 'indústria de la fusta',
    'IMI': 'indústries en general',
    'IN': 'informàtica',
    'IND': 'indústries',
    'IQ': 'indústria química',
    'IQA': 'adoberia',
    'ISL': 'islam',
    'IT': 'indústria tèxtil',
    'JE': 'jocs i espectacles',
    'LC': 'lèxic comú',
    'MD': 'medicina i farmàcia',
    'ME': 'meteorologia',
    'MI': 'mineria',
    'ML': 'metal·lúrgia',
    'MT': 'matemàtiques',
    'MU': 'música',
    'NU': 'numismàtica',
    'OP': 'obres públiques',
    'PE': 'pedagogia',
    'PO': 'política',
    'PR': 'professions',
    'PS': 'psicologia',
    'QU': 'química',
    'RE': 'religió',
    'SO': 'sociologia',
    'SP': 'esports',
    'TC': 'telecomunicació',
    'TRA': 'transports per aigua',
    'TRG': 'transports en general',
    'VE': 'veterinària',
    'ZO': 'zoologia',
    'ZOA': 'zoologia en general',
    'ZOI': 'invertebrats',
    'ZOM': 'mamífers',
    'ZOO': 'ocells',
    'ZOP': 'peixos',
    'ZOR': 'amfibis i rèptils',
}


def get_definition_ids(term: str) -> List[str]:
    url = f"{BASE_URL}?DecEntradaText={requests.utils.quote(term)}"
    r = requests.get(url, timeout=15)
    if r.status_code != 200:
        return []
    # Find all: GetDefinition('0045477') or with double quotes
    ids_single = re.findall(r"GetDefinition\(\s*'([0-9]+)'\s*\)", r.text)
    ids_double = re.findall(r"GetDefinition\(\s*\"([0-9]+)\"\s*\)", r.text)
    # Merge and deduplicate while preserving order
    seen = set()
    result: List[str] = []
    for x in ids_single + ids_double:
        if x not in seen:
            seen.add(x)
            result.append(x)
    return result


def fetch_definition_content(def_id: str) -> Optional[dict]:
    # POST to /Results/Accepcio with form field id=<ID>
    r = requests.post(f"{BASE_URL}/Accepcio", data={"id": def_id}, timeout=15)
    if r.status_code != 200:
        return None
    try:
        return r.json()
    except Exception:
        return None


def html_to_text(fragment: str) -> str:
    # Basic cleanup of IEC DLC HTML content -> plain text
    s = fragment
    # Unescape HTML entities
    s = html.unescape(s)
    # Remove tags while preserving text content
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.IGNORECASE)
    s = re.sub(r"</?[^>]+>", "", s, flags=re.DOTALL)
    # Collapse whitespace and numbered markers like I> 1
    s = re.sub(r"\s+", " ", s).strip()
    # Normalize "Ex.:" spacing
    s = s.replace("Ex.:", "Ex.:")
    return s


def split_entries_with_tags(text: str) -> List[dict]:
    # Detect bracket tags like [AGP] and split the text into entries tied to tags
    # Strategy: find all occurrences of [TAG] and capture text following until next [TAG] or end
    entries: List[dict] = []
    # Ensure consistent spacing around tags for splitting
    pattern = re.compile(r"\[([A-Z]{2,4})\]")
    pos = 0
    matches = list(pattern.finditer(text))
    if not matches:
        # No tags: single entry, default category unknown; assign LC if present
        entries.append({
            'text': text.strip(),
            'tags': [],
            'categories': []
        })
        return entries
    for i, m in enumerate(matches):
        tag = m.group(1)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        chunk = text[start:end].strip()
        if not chunk:
            continue
        cat = DIEC_TAG_MAP.get(tag)
        entries.append({
            'text': chunk,
            'tags': [tag],
            'categories': [cat] if cat else []
        })
    return entries


def parse_entries_from_html(html_fragment: str) -> List[dict]:
    # Debug HTML disabled in production; enable if needed
    def strip_sense_prefix(t: str) -> str:
        t = t.strip()
        t = re.sub(r"^(?:\d+\s*)+(?:[mf]\.)?\s*", "", t, flags=re.IGNORECASE)
        return t.strip()
    # Pre-clean noisy attributes and tags as requested
    cleaned = re.sub(r'xmlns:fo="http://www\.w3\.org/1999/XSL/Format"', '', html_fragment)
    cleaned = re.sub(r'onmouseover="doTooltip\(.*?\)"', '', cleaned, flags=re.IGNORECASE|re.DOTALL)
    cleaned = re.sub(r'onmouseout="hideTip\(\)"', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'class="body"', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<A href=.*?A>", "", cleaned, flags=re.IGNORECASE|re.DOTALL)
    cleaned = re.sub(r"<span\s+class=\"rodona\">\)\s*</span>", "", cleaned, flags=re.IGNORECASE)
    # Elimina h1-h6 tags and content
    cleaned = re.sub(r"<h[1-6][^>]*>.*?</h[1-6]>", "", cleaned, flags=re.IGNORECASE|re.DOTALL)
    # Esborra \n
    cleaned = re.sub(r"\n", " ", cleaned)
    # Simplifica espais
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    # Use BeautifulSoup for reliable HTML parsing and per-sense segmentation by <br>
    soup = BeautifulSoup(cleaned, 'html.parser')
    # Split into segments by top-level <br>
    segments: List[List] = []
    current: List = []
    for node in soup.contents:
        if getattr(node, 'name', None) == 'br':
            if current:
                segments.append(current)
                current = []
            continue
        current.append(node)
    if current:
        segments.append(current)
    entries: List[dict] = []
    for seg in segments:
        seg_soup = BeautifulSoup('', 'html.parser')
        for n in seg:
            seg_soup.append(n)
        # Gather tag codes and map to categories for this segment
        seg_tags: List[str] = []
        for tip in seg_soup.select('span.tip'):
            m = re.search(r"\[\s*([A-Z]{2,4})\s*\]", tip.get_text(" ", strip=True) or "")
            if m:
                seg_tags.append(m.group(1))
        seg_categories: List[str] = []
        for code in seg_tags:
            cat = DIEC_TAG_MAP.get(code)
            if cat and cat not in seg_categories:
                seg_categories.append(cat)
        # Extract morphology (tagline) if present in segment
        seg_tagline = None
        tl = seg_soup.select_one('span.tagline')
        if tl:
            seg_tagline = tl.get_text(' ', strip=True)
        # Remove tip and tagline spans before text extraction
        for tip in seg_soup.select('span.tip'):
            tip.decompose()
        for tln in seg_soup.select('span.tagline'):
            tln.decompose()
        # Collect examples from italic spans
        italic_nodes = seg_soup.select('span.italic')
        examples: List[str] = [n.get_text(' ', strip=True) for n in italic_nodes if n.get_text(' ', strip=True)]
        # Numbers and morphology order:
        # 1st <b> -> NUM, 1st <i> -> SUBNUM, 2nd <b> -> concat to SUBNUM, 2nd <i> -> morphology
        num = None
        subnum = None
        phrase_morfologia = None
        btags = seg_soup.find_all('b')
        itags = seg_soup.find_all('i')
        if btags:
            first_b = btags[0]
            bval = first_b.get_text(' ', strip=True)
            if bval:
                num = re.sub(r"[^0-9]", "", bval)
        if itags:
            first_i = itags[0]
            ival = first_i.get_text(' ', strip=True)
            if ival:
                subnum = re.sub(r"[^0-9]", "", ival)
        if len(btags) > 1:
            second_b = btags[1]
            b2val = second_b.get_text(' ', strip=True)
            # Expect a single letter; append to existing subnum
            m = re.match(r"^[A-Za-z]$", b2val)
            if m:
                letter = m.group(0)
                if subnum:
                    subnum = f"{subnum}{letter}"
                else:
                    subnum = letter
        if len(itags) > 1:
            second_i = itags[1]
            phrase_morfologia = second_i.get_text(' ', strip=True)
        # Remove all <b> tags; remove <i> only if single letter or number
        for t in btags:
            t.decompose()
        for t in itags:
            tval = t.get_text(' ', strip=True)
            if re.match(r"^[A-Za-z]$", tval) or re.match(r"^[0-9]+$", tval):
                t.decompose()
        # Phrase-made: capture text of span.bolditalic (phrase) and remove it
        phrase_made = None
        bi = seg_soup.select_one('span.bolditalic')
        if bi:
            phrase_made = bi.get_text(' ', strip=True)
            bi.decompose()
        # Remove spans we don't want in definition
        for sel in ['span.tip', 'span.tagline', 'span.italic']:
            for node in seg_soup.select(sel):
                node.decompose()
        # Also remove any other spans that have an unknown class (keep spans without class)
        allowed_classes = {"tip", "tagline", "italic", "bolditalic"}
        for node in seg_soup.select('span'):
            classes = node.get('class')
            if classes and not any(c in allowed_classes for c in classes):
                node.decompose()
        # Definition text is remaining text stripped
        text = strip_sense_prefix(seg_soup.get_text(' ', strip=True))
        if text:
            # Dedupe examples
            examples = [e for i, e in enumerate(examples) if e and e.strip() and e not in examples[:i]]
            # Use phrase-specific morphology when available, else segment tagline
            morph = phrase_morfologia if phrase_morfologia else seg_tagline
            entries.append({'text': text, 'tags': seg_tags, 'categories': seg_categories, 'examples': examples, 'num': num, 'subnum': subnum, 'morfologia': morph, 'phrase_made': phrase_made})
    if not entries:
        raw_text = soup.get_text(' ', strip=True)
        entries.append({'text': raw_text, 'tags': [], 'categories': [], 'examples': []})
    return entries


def extract_diec2_definitions(term: str) -> List[dict]:
    ids = get_definition_ids(term)
    if not ids:
        return []
    defs: List[dict] = []
    seen_texts = set()
    for def_id in ids:
        payload = fetch_definition_content(def_id)
        if not payload:
            continue
        mot = str(payload.get("mot", ""))
        if mot != term:
            continue
        content = payload.get("content", "")
        if not content:
            continue
        # Build entries directly from HTML to preserve examples
        entries = parse_entries_from_html(content)
        for e in entries:
            etxt = e['text']
            if etxt and etxt not in seen_texts:
                seen_texts.add(etxt)
                defs.append(e)
    return defs


def main2():
    v = '''<span><span class="bolditalic"> cap pelat </span>Cap sense cabells. </span><br><span><B>1 </B>
  <I>7 </I></span> <span><span class="tip"> [LC] </span> </span><span><span class="bolditalic"> de cap </span><I>loc.
    adv.
  </I><B>a</B><span class="rodona">) </span>Anant primerament el cap. <span class="italic">Tirar-se de cap al mar.
  </span></span><br><span><B>1 </B>
  <I>7 </I></span> <span><span class="tip"> [LC] </span> </span><span><span class="bolditalic"> de cap </span><I>loc.
    adv.
  </I><B>b</B><span class="rodona">) </span>Directament i sense torbar-se. <span class="italic">A cops i empentes el van
    portar de cap a
    les masmorres. </span></span><br><span><B>1 </B> <I>8 </I></span> <span><span class="tip"> [LC] </span>
</span>'''
    obj = (parse_entries_from_html(v))
    # to json
    import json
    print(json.dumps(obj, ensure_ascii=False, indent=2))

def main():
    if len(sys.argv) < 2:
        print("Ús: python scripts/extract_diec2_def.py <paraula> [--json]")
        print("Exemple: python scripts/extract_diec2_def.py aeroport --json")
        sys.exit(1)
    term = sys.argv[1]
    use_json = any(arg == "--json" for arg in sys.argv[2:])
    defs = extract_diec2_definitions(term)
    if not defs:
        print(f"No s'ha trobat definició per '{term}' al DIEC2.")
        sys.exit(2)
    if use_json:
        import json
        payload: Dict[str, Any] = {
            'entry': term,
            'definitions': [
                {
                    'text': d.get('text', ''),
                    'examples': d.get('examples', []),
                    'categories': d.get('categories', []),
                    'tags': d.get('tags', []),
                    'num': d.get('num'),
                    'subnum': d.get('subnum'),
                    'morfologia': d.get('morfologia'),
                    'phrase_made': d.get('phrase_made'),
                } for d in defs
            ]
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for i, d in enumerate(defs, start=1):
            cats = d.get('categories', [])
            num = d.get('num')
            subnum = d.get('subnum')
            prefix = ""
            if num:
                prefix += f"{num}"

                if subnum:
                    prefix += f".{subnum} "
                else:
                    prefix += " "
            phrase_made = d.get('phrase_made')

            if phrase_made:
                prefix += f"({phrase_made}) "

            morfologia = d.get('morfologia')

            if morfologia:
                prefix += f"<{morfologia}> "

            prefix += f"[{', '.join(cats)}] " if cats else ""
            print(f"{prefix}{d.get('text','')}")
            exs = d.get('examples', [])
            for ex in exs:
                print(f"Ex: {ex}")
            if i < len(defs):
                print("")


if __name__ == "__main__":
    main()
