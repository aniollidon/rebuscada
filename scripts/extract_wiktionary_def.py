import sys
import json
import re
import xml.etree.ElementTree as ET
from typing import List, Optional, Dict, Any

# Minimal, streaming parser for Wikimedia pages-articles XML dumps (multistream works the same at the XML level).
# Given a page title, it extracts Catalan (== Català ==) definitions (# lines) from the latest revision text.

def tag_name(tag: str) -> str:
    """Return the local tag name without namespace."""
    return tag.split('}')[-1]

LANG_HEADER_PATTERN = re.compile(r"^==\s*(Català|\{\{-ca-\}\})\s*==\s*$", re.MULTILINE)
# Match exactly level-2 headers: '== ... ==' for language switches.
SECTION_HEADER_PATTERN = re.compile(r"^\s*==\s*(.*?)\s*==\s*$", re.MULTILINE)
# Match subsection headers on a line by themselves, allowing leading spaces
# and any level of '=' >= 3 (e.g., === Nom === or ==== Declinació ====).
SUBSECTION_HEADER_PATTERN = re.compile(r"^\s*={3,}\s*(.*?)\s*={3,}\s*$", re.MULTILINE)
# Treat only top-level definitions: lines starting with '#' but NOT '#*' or '#:'
DEFINITION_LINE_PATTERN = re.compile(r"^#(?![#:*])\s*(.+)")
# Examples may be marked as '#*' or '#:' in Wiktionary
EXAMPLE_LINE_PATTERN = re.compile(r"^#[:*]\s*(.+)")


def extract_catalan_section(wikitext: str) -> Optional[str]:
    """Return only the Catalan 'Nom' and 'Verb' subsections text.
    - Find the Catalan language block: from '== {{-ca-}} ==' (or '== Català ==')
      until the next level-2 header '== ... =='.
    - Inside that block, keep only subsections titled 'Nom' or 'Verb',
      discarding others.
    """
    match = LANG_HEADER_PATTERN.search(wikitext)
    if not match:
        return None
    start = match.end()
    # Find ALL level-2 headers and determine the next one after the Catalan header
    headers = list(SECTION_HEADER_PATTERN.finditer(wikitext))
    # Locate the matched header among headers by position
    end = len(wikitext)
    ca_block = wikitext[start:end]

    # Identify all subsections within Catalan and concatenate only Nom/Verb/Adjectiu/Adverbi
    parts: List[str] = []
    subs = list(SUBSECTION_HEADER_PATTERN.finditer(ca_block))
    if not subs:
        # If no subsections, nothing to keep
        return None
    for i, m in enumerate(subs):
        name = m.group(1).strip()
        norm = re.sub(r"\{\{.*?\}\}", "", name).strip()
        s = m.end()
        e = subs[i+1].start() if i+1 < len(subs) else len(ca_block)
        slice_text = ca_block[s:e]
        # Keep only Nom/Verb/Adjectiu/Adverbi with their specific Catalan templates
        nl = norm.lower()
        is_nom = ("nom" in nl) and re.search(r"\{\{\s*ca-nom\s*\|", slice_text)
        is_verb = ("verb" in nl) and re.search(r"\{\{\s*ca-verb\s*\|", slice_text)
        is_adj = ("adjectiu" in nl) and re.search(r"\{\{\s*ca-adj\s*\|", slice_text)
        is_adv = ("adverbi" in nl) and re.search(r"\{\{\s*entrada\s*\|\s*ca\s*\|\s*adv\s*\}\}", slice_text)
        if is_nom or is_verb or is_adj or is_adv:
            parts.append(slice_text)
    if not parts:
        return None
    return "\n".join(parts)


def iter_target_subsections(section_text: str, targets: List[str]) -> List[str]:
    """Return the text slices for requested third-level subsections within a language section.
    Example targets: ['Nom', 'Verb']
    """
    out_slices: List[str] = []
    # Find all subsection headers and their spans
    matches = list(SUBSECTION_HEADER_PATTERN.finditer(section_text))
    if not matches:
        return out_slices
    for i, m in enumerate(matches):
        name = m.group(1).strip()
        # Normalize header name: drop templates and trim
        norm = re.sub(r"\{\{.*?\}\}", "", name).strip()
        # Some pages may include extra info, so match if contains target word
        if any(t.lower() == norm.lower() or t.lower() in norm.lower() for t in targets):
            start = m.end()
            # next subsection or end of section
            end = matches[i+1].start() if i+1 < len(matches) else len(section_text)
            out_slices.append(section_text[start:end])
    return out_slices


def clean_markup(text: str) -> str:
    """Heuristic cleanup of basic wikitext markups for readability."""
    text = re.sub(r"\[\[(.*?)\|(.*?)\]\]", r"\2", text)
    text = re.sub(r"\[\[(.*?)\]\]", r"\1", text)
    # Drop generic templates, but leave example templates to be handled separately
    def _remove_templates(m: re.Match) -> str:
        inner = m.group(1)
        # keep ex-us|...|... intact for example-specific extraction
        if inner.strip().startswith('ex-us'):
            return '{{' + inner + '}}'
        return ''
    text = re.sub(r"\{\{(.*?)\}\}", _remove_templates, text)
    text = re.sub(r"<[^>]+>", r"", text)
    return text.strip()


def clean_example(text: str) -> str:
    """Extract readable example text, preserving content after '|ca|' in templates like {{ex-us|ca|...}}.
    If multiple args after '|ca|', join them with spaces.
    """
    # If template ex-us present, try to capture arguments after '|ca|'
    m = re.search(r"\{\{\s*ex-us\s*\|\s*ca\s*\|\s*(.*?)\}\}", text)
    if m:
        payload = m.group(1).strip()
        # Split on pipes that may separate args, then clean each
        parts = [p.strip() for p in re.split(r"\|", payload)]
        joined = ' '.join(parts)
        # Now resolve wiki links inside
        joined = re.sub(r"\[\[(.*?)\|(.*?)\]\]", r"\2", joined)
        joined = re.sub(r"\[\[(.*?)\]\]", r"\1", joined)
        return joined.strip()
    # Fallback to generic cleanup
    return clean_markup(text)


def trim_outer_quotes(text: str) -> str:
    """Remove leading/trailing quote characters (" or ') if present, then trim."""
    if not text:
        return text
    text = text.strip()
    # Remove wiki bold/italic markers inside text, e.g., '' and '''
    text = re.sub(r"''+", "", text)
    text = re.sub(r'^[\'\"]+', '', text)
    text = re.sub(r'[\'\"]+$', '', text)
    return text.strip()


def extract_definitions_from_section(section_text: str, with_examples: bool = False) -> List[Any]:
    """Extract definitions (and optionally examples) from the section.
    Returns:
        If with_examples=False: List[str]
        If with_examples=True: List[Dict[str, Any]] each {'def': str, 'examples': [str]}
    """
    if not with_examples:
        definitions: List[str] = []
        for line in section_text.splitlines():
            m = DEFINITION_LINE_PATTERN.match(line)
            if m:
                raw = m.group(1).strip()
                # Extract labels from {{marca|ca|...}} templates
                labels = []
                for lab in re.findall(r"\{\{\s*marca\s*\|\s*ca\s*\|(.*?)\}\}", raw):
                    # labels may be pipe-separated
                    labels.extend([p.strip() for p in lab.split('|') if p.strip()])
                # Remove marca templates from definition text
                raw = re.sub(r"\{\{\s*marca\s*\|\s*ca\s*\|.*?\}\}", "", raw)
                cleaned = clean_markup(raw)
                if cleaned:
                    if labels:
                        cleaned = f"({', '.join(labels)}) " + cleaned
                    definitions.append(trim_outer_quotes(cleaned))
        return definitions
    # With examples mode
    out: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    for line in section_text.splitlines():
        def_m = DEFINITION_LINE_PATTERN.match(line)
        if def_m:
            raw_def = def_m.group(1).strip()
            labels = []
            for lab in re.findall(r"\{\{\s*marca\s*\|\s*ca\s*\|(.*?)\}\}", raw_def):
                labels.extend([p.strip() for p in lab.split('|') if p.strip()])
            raw_def = re.sub(r"\{\{\s*marca\s*\|\s*ca\s*\|.*?\}\}", "", raw_def)
            raw_def = clean_markup(raw_def)
            if raw_def:
                if labels:
                    raw_def = f"({', '.join(labels)}) " + raw_def
                current = {"def": trim_outer_quotes(raw_def), "examples": []}
                out.append(current)
            continue
        ex_m = EXAMPLE_LINE_PATTERN.match(line)
        if ex_m and current is not None:
            raw_ex = clean_example(ex_m.group(1).strip())
            if raw_ex:
                current["examples"].append(trim_outer_quotes(raw_ex))
    return out


def extract_defs_and_synonyms(section_text: str, with_examples: bool = False) -> Dict[str, Any]:
    """Extract definitions and synonyms from a section slice.
    - Definitions: lines starting with a single '# ...' (same rule as before)
    - Examples: optional, tied to the last definition when with_examples=True
    - Synonyms: block starting at '{{-sin-}}' followed by bullet lines '* ...'
      until the next template '{{...}}' that is not a bullet line or end of section.
    Returns a dict: {'definitions': [...]} or {'definitions': [{'def': str, 'examples': [...]}], 'synonyms': [...]}
    """
    result: Dict[str, Any] = {"definitions": []}
    # Detect part of speech via Catalan templates
    if re.search(r"\{\{\s*ca-verb\s*\|", section_text):
        result["pos"] = "VERB"
    elif re.search(r"\{\{\s*ca-nom\s*\|", section_text):
        result["pos"] = "NOM"
    elif re.search(r"\{\{\s*ca-adj\s*\|", section_text):
        result["pos"] = "ADJECTIU"
    elif re.search(r"\{\{\s*entrada\s*\|\s*ca\s*\|\s*adv\s*\}\}", section_text):
        result["pos"] = "ADVERBI"
    # First, definitions (and optional examples)
    defs = extract_definitions_from_section(section_text, with_examples=with_examples)
    result["definitions"] = defs
    # Then, synonyms
    synonyms: List[str] = []
    lines = section_text.splitlines()
    i = 0
    in_syn = False
    while i < len(lines):
        line = lines[i]
        if not in_syn:
            # Enter synonyms block at the marker
            if re.match(r"\{\{\s*-sin-\s*\}\}", line):
                in_syn = True
                i += 1
                continue
        else:
            # Collect bullet lines as synonyms; stop at next template start that's not a bullet
            if re.match(r"^\*\s*(.+)", line):
                # extract all [[...]] tokens comma-separated
                text = line[1:].strip()
                # split by commas outside of links; simplest: split on ',' and clean
                # but better: extract wiki links
                links = re.findall(r"\[\[(.*?)\]\]", text)
                if links:
                    synonyms.extend([clean_markup(l) for l in links])
                else:
                    cleaned = clean_markup(text)
                    if cleaned:
                        # may contain multiple comma-separated items
                        for part in [p.strip() for p in cleaned.split(',')]:
                            if part:
                                synonyms.append(part)
                i += 1
                continue
            # Stop synonyms block at next template or blank line
            if re.match(r"\{\{", line) or line.strip() == "":
                in_syn = False
                # do not consume this line; next loop handles templates
            i += 1
            continue
        i += 1
    if synonyms:
        result["synonyms"] = synonyms
    return result


def iter_pages(xml_path: str):
    """Yield (title, latest_text) for each page, streaming via iterparse.
    This avoids loading the entire dump into memory.
    """
    # iterparse with 'end' events; clear elements to keep memory low
    context = ET.iterparse(xml_path, events=("end",))
    title = None
    latest_text = None
    for event, elem in context:
        tname = tag_name(elem.tag)
        if tname == "title":
            title = (elem.text or "").strip()
        elif tname == "text":
            # each revision's text; keep the last seen before </page>
            latest_text = elem.text or ""
        elif tname == "page":
            if title is not None:
                yield title, latest_text or ""
            elem.clear()
            title = None
            latest_text = None


def extract_definitions_for_title(xml_path: str, entry_title: str, with_examples: bool = False) -> List[Any]:
    entry_title_norm = entry_title.strip()
    for title, text in iter_pages(xml_path):
        if title == entry_title_norm:
            section = extract_catalan_section(text)
            if not section:
                return []
            # 'section' already contains only Catalan Nom/Verb content; parse directly
            combined = extract_defs_and_synonyms(section, with_examples=with_examples)
            return [combined]
    return []


def main():
    # Argument patterns supported:
    # 1) python extract_wiktionary_def.py <entrada>
    # 2) python extract_wiktionary_def.py <entrada> --examples
    # 3) python extract_wiktionary_def.py <dump.xml> <entrada> [--examples]
    # 4) python extract_wiktionary_def.py --dump <dump.xml> <entrada> [--examples]
    # Defaults to data/cawiktionary.xml if no dump specified.
    args = sys.argv[1:]
    if not args:
        print("Ús: python scripts/extract_wiktionary_def.py <entrada> [--examples] | <dump.xml> <entrada> [--examples] | --dump <dump.xml> <entrada> [--examples]")
        sys.exit(1)

    with_examples = any(a == "--examples" for a in args)
    debug = any(a == "--debug" for a in args)
    as_json = any(a == "--json" for a in args)
    filtered = [a for a in args if a not in ("--examples", "--debug", "--json")]

    dump_path = "data/cawiktionary.xml"  # default
    entry = None

    if filtered[0] == "--dump":
        if len(filtered) < 3:
            print("Error: cal indicar --dump <fitxer.xml> <entrada>")
            sys.exit(1)
        dump_path = filtered[1]
        entry = filtered[2]
    elif filtered[0].lower().endswith('.xml'):
        if len(filtered) < 2:
            print("Error: cal indicar <dump.xml> <entrada>")
            sys.exit(1)
        dump_path = filtered[0]
        entry = filtered[1]
    else:
        # First argument is entry directly
        entry = filtered[0]

    # Optional debug: print basic info when matching the page
    defs = extract_definitions_for_title(dump_path, entry, with_examples=with_examples)
    if not defs:
        if as_json:
            print(json.dumps({"entry": entry, "sections": []}, ensure_ascii=False))
            sys.exit(2)
        print(f"No s'han trobat definicions en català per '{entry}'.")
        sys.exit(2)
    if debug:
        print("[DEBUG] Entrada:", entry)
        print("[DEBUG] Dump:", dump_path)
        print("[DEBUG] Seccions processades:", len(defs))
    # JSON output if requested
    if as_json:
        sections_out = []
        for section_item in defs:
            pos = section_item.get("pos")
            defs_item = section_item.get("definitions", [])
            syns_item = section_item.get("synonyms", [])
            norm_defs = []
            if with_examples:
                for d in defs_item:
                    norm_defs.append({"text": d.get("def", ""), "examples": d.get("examples", [])})
            else:
                for d in defs_item:
                    norm_defs.append({"text": d})
            sections_out.append({"pos": pos, "definitions": norm_defs, "synonyms": syns_item})
        print(json.dumps({"entry": entry, "sections": sections_out}, ensure_ascii=False, indent=2))
        return
    # Print combined output: definitions and synonyms per kept subsection
    for si, section_item in enumerate(defs, 1):
        pos = section_item.get("pos")
        if pos:
            print(f"{si}. {pos}")
        defs_item = section_item.get("definitions", [])
        syns_item = section_item.get("synonyms", [])
        if with_examples:
            for i, d in enumerate(defs_item, 1):
                print(f"   {si}.{i}. {d['def']}")
                for ex in d.get('examples', []):
                    print(f"   \tEX: {ex}")
        else:
            for i, d in enumerate(defs_item, 1):
                print(f"   {si}.{i}. {d}")
        if syns_item:
            print(f"\nSINÒNIMS: {', '.join(syns_item)}")


if __name__ == "__main__":
    main()
