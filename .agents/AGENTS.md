# Rebuscada — Directrius del projecte

## Descripció

Rebuscada és un joc de paraules en català on els jugadors han d'endevinar una paraula objectiu provant paraules i veient com de properes estan en un rànquing de similitud semàntica. El projecte inclou un servidor de joc (API), una interfície web (React), un panell d'administració, i un sistema d'estadístiques.

## Arquitectura

| Component                    | Tecnologia                      | Fitxer(s) principal(s)                |
| ---------------------------- | ------------------------------- | ------------------------------------- |
| **Servidor de joc**          | FastAPI (Python)                | `server.py`                           |
| **Servidor d'administració** | FastAPI (Python)                | `server_admin.py`                     |
| **Frontend del joc**         | React + TypeScript              | `frontend/src/App.tsx`                |
| **Panell d'administració**   | HTML/JS/CSS vanilla + Bootstrap | `admin/`                              |
| **Estadístiques**            | SQLite via `stats.py`           | `stats.py`                            |
| **Diccionari**               | JSON + SQLite                   | `diccionari.py`, `diccionari_full.py` |
| **Generació de rànquings**   | FastText / OpenAI / SOTA        | `generate.py`, `proximitat*.py`       |

### Flux de dades principal

```
Usuari → frontend (React) → server.py (FastAPI)
                                ├── diccionari.py (validació de paraules)
                                ├── data/words/{paraula}.json (rànquing)
                                └── stats.py → data/stats.db (estadístiques)
```

## Idioma

El bon ús de la llengua catalana és una prioritat en el projecte. Tant com la funcionalitat de l'aplicació.

- **Textos d'interfície, missatges d'error, etiquetes, documentació**: Tot en **català**.
- Seguir la [guia d'estil de programari de Softcatalà](https://www.softcatala.org/guia-estil-programari/). Disponible com a skill [.agents/skills/catalan-style.md](.agents/skills/catalan-style.md) (versió resumida operacional) i [.agents/skills/catalan-style-referencia.md](.agents/skills/catalan-style-referencia.md) (referència completa amb exemples). Revisa els textos amb aquestes guies.
- **Codi** (variables, funcions, classes): En **català** tal com és ara (p.ex. `obtenir_forma_canonica`, `carregar_ranking`).
- **Comentaris al codi**: En català.

## Comandes principals

```bash
# Backend — servidor de joc (port 8000 per defecte)
python server.py

# Backend — servidor d'administració (port 5001 per defecte)
python server_admin.py

# Frontend — servidor de desenvolupament (port 3000)
cd frontend && npm start

# Tests backend
pytest tests/ -v

# Tests frontend
cd frontend && npm test

# Linting backend
ruff check .

# Generar rànquing per una paraula (requereix model FastText)
python generate.py --paraula "casa" --algorisme fasttext
```

## Convencions de codi

### Python (backend)

- Python 3.10+
- Formatació: `ruff` (configuració a `pyproject.toml`)
- Línies ≤ 120 caràcters
- Imports ordenats (stdlib → third-party → local)
- Tests amb `pytest`
- Tipatge amb type hints als paràmetres de funcions públiques

### TypeScript/React (frontend)

- TypeScript amb `strict: true`
- React 19+ amb hooks
- ESLint configurat amb `react-app`
- Tests amb Jest + React Testing Library

### HTML/JS (admin)

- JavaScript vanilla (sense framework)
- Bootstrap 5 per a la UI
- Chart.js per a gràfics

## Estructura de directoris

```
├── server.py              # API del joc (FastAPI)
├── server_admin.py        # API d'administració (FastAPI)
├── stats.py               # Sistema d'estadístiques (SQLite)
├── diccionari.py          # Diccionari reduït (freqüència alta)
├── diccionari_full.py     # Diccionari complet (SQLite)
├── generate.py            # Generació de rànquings
├── generateLLM.py         # Generació amb LLM
├── proximitat.py          # Similitud amb FastText
├── proximitatOpenAI.py    # Similitud amb OpenAI
├── proximitatSOTA.py      # Similitud amb Sentence Transformers
├── fast_ai.py             # Interfície multi-backend per LLM
├── ai.py                  # Mòdul IA (legacy)
├── tests/                 # Tests backend (pytest)
├── frontend/              # Aplicació React
│   └── src/
│       ├── App.tsx        # Component principal del joc
│       └── gameUtils.ts   # Utilitats (numerals romans, estat del joc)
├── admin/                 # Panell d'administració (HTML/JS/CSS)
├── scripts/               # Scripts de manteniment i generació
├── data/                  # Dades del joc (no versionades)
│   ├── words/             # Fitxers de rànquing per paraula
│   ├── games.json         # Calendari de jocs
│   ├── diccionari.json    # Diccionari reduït
│   ├── definicions.json   # Definicions del Wiktionary
│   └── stats.db           # Base de dades d'estadístiques
└── pyproject.toml         # Configuració Python (pytest, ruff)
```

## Dades

- `data/` **no es versiona** (exclòs al `.gitignore`). Conté el diccionari, rànquings, estadístiques i models.
- El model FastText (`data/cc.ca.300.bin`, ~7 GB) es descarrega automàticament quan es necessita.
- Els fitxers de rànquing (`data/words/*.json`) mapegen paraula → posició (0 = més propera).

## Variables d'entorn

Copiar `.env.example` a `.env` i ajustar. Variables principals:

| Variable            | Per defecte                    | Descripció                                      |
| ------------------- | ------------------------------ | ----------------------------------------------- |
| `PORT`              | `8000`                         | Port del servidor de joc                        |
| `ADMIN_PORT`        | `5001`                         | Port del servidor d'administració               |
| `ADMIN_PASSWORD`    | _(buit)_                       | Contrasenya d'admin (buit = sense autenticació) |
| `DICCIONARI_PATH`   | `data/diccionari.json`         | Ruta al diccionari reduït                       |
| `DEFAULT_REBUSCADA` | `paraula`                      | Paraula per defecte                             |
| `ALLOWED_ORIGINS`   | `localhost:3000,rebuscada.cat` | Orígens CORS permesos                           |

## Tests

- **Backend**: `pytest tests/ -v` — tests d'integració amb TestClient de FastAPI. No requereixen el model FastText (usen dades mock).
- **Frontend**: `cd frontend && npm test` — tests amb Jest + React Testing Library.
- **CI**: GitHub Actions executa tots els tests en cada push/PR a `main`.
- Abans de fer push, executar sempre: `pytest tests/ -v && cd frontend && npm test -- --watchAll=false`
