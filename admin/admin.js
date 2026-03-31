// Configuració
const PORT = 3000; // Port on corre el backend admin (uvicorn)
//const SERVER = `http://localhost:${PORT}`;
const SERVER = `http://5.250.190.223:${PORT}`;
// Bases d'API
const API_BASE = `${SERVER}/api`;
const RANKINGS_API = `${API_BASE}/rankings`;
const VALIDATIONS_API = `${API_BASE}/validations`;
const FAVORITES_API = `${API_BASE}/favorites`;
const DIFFICULTIES_API = `${API_BASE}/difficulties`;
const SYNONYMS_API = `${API_BASE}/synonyms`;
const AUTH_ENDPOINT = `${API_BASE}/auth`;
const GENERATE_ENDPOINT = `${API_BASE}/generate`; // alternatiu
const GENERATE_RANDOM_ENDPOINT = `${API_BASE}/generate-random`;
const AI_GENERATE_ENDPOINT = `${API_BASE}/ai-generate`;
const STATS_API = `${API_BASE}/stats`;
// Page size per a càrrega de fragments
const PAGE_SIZE = 300;
// Diccionari (obertura en nova pestanya). Substituïm [PARAULA]
const DICT_URL_TEMPLATE =
  "https://dlc.iec.cat/Results?DecEntradaText=[PARAULA]&AllInfoMorf=False&OperEntrada=0&OperDef=0&OperEx=0&OperSubEntrada=0&OperAreaTematica=0&InfoMorfType=0&OperCatGram=False&AccentSen=False&CurrentPage=0&refineSearch=0&Actualitzacions=False";

let adminToken = null; // guardem la contrasenya (x-admin-token)

async function ensureAuthenticated() {
  if (adminToken) return true;
  const pwd = prompt(
    "Contrasenya d'administració (abans, recordeu recarregar la pàgina amb Ctrl+R per tenir els últims canvis):",
    "",
  );
  if (pwd === null) return false;
  try {
    const res = await fetch(AUTH_ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password: pwd }),
    });
    if (!res.ok) throw new Error("Autenticació fallida");
    const data = await res.json();
    if (data.ok) {
      adminToken = pwd; // s'utilitza com a token simple
      return true;
    }
  } catch (_) {
    alert("Contrasenya incorrecta");
  }
  return ensureAuthenticated(); // reintenta fins cancel·lar
}

function authHeaders() {
  return adminToken ? { "x-admin-token": adminToken } : {};
}

// Estat global
let files = [];
let selected = null;
// Nou model: paraules carregades per posició absoluta (sparse)
let wordsByPos = {}; // pos -> {word,pos}
// offset ja no s'utilitza per la finestra lliscant, però el mantenim per compatibilitat amb codi antic (guardat)
let offset = 0; // sempre 0 per al fragment que desem
let total = 0;
let loading = false;
let dirty = false;
let menuIdx = null;
let menuAnchor = null;
let confirmDelete = null;
// Guarda informació de l'últim moviment
let lastMoveInfo = null; // {word, toPos}
let validations = {}; // filename -> 'validated' | 'approved' (empty means not validated)
let favorites = {}; // filename -> true
let difficulties = {}; // filename -> 'facil'|'mitja'|'dificil'
let comments = {}; // Estat dels comentaris del fitxer actual {global: "", words: {}}
let customSynonymsData = null; // Dades de test de sinònims personalitzat (temporal)
let customTextData = null; // Dades de test de text personalitzat (temporal)
let searchResultsData = null; // Dades de resultats de cerca avançada (temporal)
let regexModeActive = false; // estat del mode REGEX per a la cerca avançada
let showOnlyPending = false; // filtre de fitxers no validats
let showOnlyValidated = false; // filtre de fitxers validats
let showOnlyFavorites = false; // filtre de fitxers preferits
let showInCalendar = false; // filtre per mostrar fitxers ja assignats al calendari
let autoSaveTimer = null; // temporitzador per auto-desat
const AUTO_SAVE_DELAY = 800; // ms després de l'últim canvi de drag

// Gestió del calendari
let calendarGames = []; // llista de {id, name}
let calendarStartDate = "23-12-2025"; // data d'inici del calendari
let calendarFilterValidated = false;
let calendarFilterFavorites = false;
let calendarFilterUnique = true; // Activat per defecte per evitar repeticions

// Configuració general
let settings = {
  autoScroll: true, // per defecte activat
};

// Carrega configuració del localStorage
function loadSettings() {
  try {
    const saved = localStorage.getItem("rebuscada-admin-settings");
    if (saved) {
      settings = { ...settings, ...JSON.parse(saved) };
    }
  } catch (e) {
    console.warn("Error carregant configuració:", e);
  }
}

// Desa configuració al localStorage
function saveSettings() {
  try {
    localStorage.setItem("rebuscada-admin-settings", JSON.stringify(settings));
  } catch (e) {
    console.warn("Error desant configuració:", e);
  }
}

// --- Debug de moviments ---
const DEBUG_MOVE_LOGS = true; // posa a false per silenciar
function logMove(...args) {
  if (!DEBUG_MOVE_LOGS) return;
  try {
    console.debug(new Date().toISOString(), "[MOVE]", ...args);
  } catch (_) {}
}

// Highlight temporal helper (classe configurable)
function tempHighlightElement(el, ms = 1000, cls = "moved") {
  if (!el) return;
  el.classList.add(cls);
  setTimeout(() => {
    if (el.classList) el.classList.remove(cls);
  }, ms);
}

// Color segons posició
function colorPerPos(posicio) {
  if (posicio < 100) return "#4caf50"; // Verd
  if (posicio < 250) return "#ffc107"; // Groc
  if (posicio < 500) return "#ff9800"; // Taronja
  if (posicio < 2000) return "#f44336"; // Vermell
  return "#9e9e9e"; // Gris per la resta
}

// Genera etiqueta de dificultat amb color
function getDifficultyTag(difficulty) {
  const configs = {
    facil: { label: "Fàcil", color: "#28a745", bg: "#d4edda" },
    mitja: { label: "Mitjà", color: "#fd7e14", bg: "#fef3cd" },
    dificil: { label: "Difícil", color: "#dc3545", bg: "#f8d7da" },
  };
  const config = configs[difficulty];
  if (!config) return "";
  return `<span class="difficulty-tag" style="background:${config.bg}; color:${config.color}; font-size:10px; padding:2px 6px; border-radius:8px; margin-left:6px; border:1px solid ${config.color}">${config.label}</span>`;
}

// Obtenir l'estat de validació i configurar el checkbox
function getValidationState(filename) {
  const status = validations[filename] || "";
  if (status === "approved") {
    return {
      checked: true,
      indeterminate: false,
      className: "validated-approved",
      title: "Aprovat per l'Aniol - Feu clic per tornar a no validat",
    };
  } else if (status === "validated") {
    return {
      checked: true,
      indeterminate: false,
      className: "validated-yes",
      title: "Validat - Feu clic per aprovar",
    };
  } else {
    return {
      checked: false,
      indeterminate: false,
      className: "",
      title: "No validat - Feu clic per validar",
    };
  }
}

// Render inicial
document.addEventListener("DOMContentLoaded", async () => {
  loadSettings(); // Carrega la configuració al iniciar
  renderApp();
  const ok = await ensureAuthenticated();
  if (ok) {
    // Carrega el calendari primer per poder detectar assignacions
    await loadCalendarGames();
    fetchFiles();
  }
});

function renderApp() {
  const app = document.getElementById("app");
  app.innerHTML = `
    <div class="p-3 py-2">
      <div class="d-flex justify-content-between align-items-center mb-3">
        <h4 class="mb-0 rebuscada" >Rebuscada.cat - Gestió</h4>
        <div class="d-flex gap-2">
          <button class="btn btn-outline-secondary btn-sm" id="stats-btn" title="Estadístiques de joc">
            <i class="bi bi-bar-chart-line"></i>
          </button>
          <button class="btn btn-outline-secondary btn-sm" id="calendar-btn" title="Gestió del calendari de paraules">
            <i class="bi bi-calendar3"></i>
          </button>
          <button class="btn btn-outline-secondary btn-sm" id="settings-btn" title="Configuració general">
            <i class="bi bi-gear"></i>
          </button>
        </div>
      </div>
      <div class="row g-3" id="main-layout">
        <div class="col-auto" style="width: 300px;">
          <div class="paper">
            <h5 class="mb-2">Fitxers</h5>
              <div class="mb-2 small" style="display: flex;gap: 0 15px;flex-wrap: wrap;">
              <div class="d-flex align-items-center gap-2">
                <input type="checkbox" id="filter-pending" class="form-check-input" />
                <label for="filter-pending" id="filter-pending-label" class="form-check-label" style="cursor:pointer;">Pendents</label>
              </div>
              <div class="d-flex align-items-center gap-2">
                <input type="checkbox" id="filter-validated" class="form-check-input" />
                <label for="filter-validated" id="filter-validated-label" class="form-check-label" style="cursor:pointer;">Validats</label>
              </div>
              <div class="d-flex align-items-center gap-2">
                <input type="checkbox" id="filter-favorites" class="form-check-input" />
                <label for="filter-favorites" id="filter-favorites-label" class="form-check-label" style="cursor:pointer;">Preferits</label>
              </div>
              <div class="d-flex align-items-center gap-2">
                <input type="checkbox" id="hide-in-calendar" class="form-check-input" />
                <label for="hide-in-calendar" id="hide-in-calendar-label" class="form-check-label" style="cursor:pointer;">Mostra assignats</label>
              </div>
            </div>
            <div class="files-content">

              <ul class="file-list" id="file-list"></ul>
              <div class="d-grid mt-3 gap-2">
                <button class="btn btn-primary btn-sm" id="create-file" type="button">Crea un rànquing…</button>
                <button class="btn btn-outline-primary btn-sm" id="create-random" type="button" title="Genera 10 paraules aleatòries (pot trigar)">Genera 10 aleatòries…</button>
                <small id="random-status" class="text-muted" style="display:none;">Generant... pot trigar uns segons.</small>
              </div>
            </div>
          </div>
        </div>
        <div class="col" id="words-column">
          <div class="paper">
            <div class="d-flex align-items-center justify-content-between mb-2">
              <div class="d-flex align-items-center gap-2">
                <h5 class="mb-0" id="words-title">Paraules</h5>
                <select id="difficulty-selector" class="form-select form-select-sm" style="width:140px; display:none;" title="Dificultat del rànquing">
                  <option value="">No categoritzat</option>
                  <option value="facil">Fàcil</option>
                  <option value="mitja">Mitjà</option>
                  <option value="dificil">Difícil</option>
                </select>
              </div>
              <span id="autosave-status" class="text-muted small" style="display:none;">Desant…</span>
            </div>
            <div class="input-group input-group-sm mb-2">
              <div style="position: relative; flex: 1;">
                <input id="search-word" type="text" class="form-control" placeholder="Cerca paraula..." style="padding-right: 35px;" />
                <button id="regex-toggle-btn" type="button" title="Mode REGEX (clic per activar/desactivar)" style="position: absolute; right: 5px; top: 50%; transform: translateY(-50%); border: 1px solid #ccc; background: #f8f9fa; color: #666; border-radius: 3px; width: 24px; height: 24px; font-size: 12px; font-weight: bold; cursor: pointer; padding: 0; line-height: 1; transition: all 0.2s;">rx</button>
              </div>
              <button class="btn btn-outline-secondary" id="search-btn" type="button" title="Cerca exacta">Cerca</button>
              <button class="btn btn-outline-primary" id="search-plus-btn" type="button" title="Cerca avançada (conté text o regex)">Cerca+</button>
              <button class="btn btn-outline-success" id="add-new-word-btn" type="button" title="Afegeix una paraula nova al rànquing">+Nova</button>
              <button class="btn btn-outline-info" id="show-test" type="button" title="Mostra paraules test">Test</button>
              <button class="btn btn-outline-warning" id="show-ia-shortcuts" type="button" title="Dreçeres IA per tests personalitzats">IA</button>
            </div>
            <div id="words-area" style="min-height:79vh"></div>
          </div>
        </div>
        <div class="col-auto" id="test-column" style="width: 350px; display:none;">
          <div class="paper" style="height: 100%;">
            <h5 class="mb-2">Testos</h5>
            <div id="test-overlay" style="height: 84vh; overflow-y: auto; overflow-x: clip;"></div>
          </div>
        </div>
      </div>
      <div id="dialog-root"></div>
      <div id="menu-root"></div>
      <!-- Modal de configuració -->
      <div class="modal fade" id="settingsModal" tabindex="-1" aria-labelledby="settingsModalLabel" aria-hidden="true">
        <div class="modal-dialog">
          <div class="modal-content">
            <div class="modal-header">
              <h5 class="modal-title" id="settingsModalLabel">Configuració General</h5>
              <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Tanca"></button>
            </div>
            <div class="modal-body">
              <div class="form-check form-switch">
                <input class="form-check-input" type="checkbox" role="switch" id="autoScrollSwitch">
                <label class="form-check-label" for="autoScrollSwitch">
                  Moviment automàtic de la vista
                </label>
                <div class="form-text">
                  Quan està activat, la vista es mourà automàticament cap a la nova posició de les paraules que es mouen.
                </div>
              </div>
              <hr />
              <div class="d-flex align-items-center gap-2">
                <button type="button" class="btn btn-warning" id="clearCacheBtn" title="Neteja la memòria cau del servidor principal">
                  Neteja memòria cau del servidor
                </button>
                <small id="clearCacheStatus" class="text-muted" style="display:none;">Netejant…</small>
              </div>
              <div class="form-text mt-1">
                Buida les entrades de memòria cau dels rànquings carregats (LRU). Feu-ho si heu modificat els rànquings <code>*.json</code>. No afecta partides en curs; obliga a reobrir els fitxers quan es demanin de nou.
              </div>
            </div>
            <div class="modal-footer">
              <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Tanca</button>
              <button type="button" class="btn btn-primary" id="saveSettingsBtn">Desa</button>
            </div>
          </div>
        </div>
      </div>
      <!-- Modal del calendari de paraules -->
      <div class="modal fade" id="calendarModal" tabindex="-1" aria-labelledby="calendarModalLabel" aria-hidden="true">
        <div class="modal-dialog modal-lg">
          <div class="modal-content">
            <div class="modal-header">
              <h5 class="modal-title" id="calendarModalLabel">Gestió del calendari de paraules</h5>
              <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Tanca"></button>
            </div>
            <div class="modal-body">
              <div class="mb-3">
                <label class="form-label">Filtres:</label>
                <div class="btn-group btn-group-sm mb-2" role="group">
                  <input type="checkbox" class="btn-check" id="filter-cal-validated" autocomplete="off">
                  <label class="btn btn-outline-primary" for="filter-cal-validated">Validats</label>
                  
                  <input type="checkbox" class="btn-check" id="filter-cal-favorites" autocomplete="off">
                  <label class="btn btn-outline-primary" for="filter-cal-favorites">Preferits</label>
                  
                  <input type="checkbox" class="btn-check" id="filter-cal-unique" autocomplete="off">
                  <label class="btn btn-outline-primary" for="filter-cal-unique">Únics</label>
                </div>
              </div>
              <div id="calendar-list" style="max-height: 60vh; overflow-y: auto;">
                <!-- Llista dinàmica de paraules -->
              </div>
              <div class="mt-3">
                <button class="btn btn-success btn-sm" id="add-calendar-item">
                  <i class="bi bi-plus-circle"></i> Afegir paraula
                </button>
              </div>
            </div>
            <div class="modal-footer">
              <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Tanca</button>
              <button type="button" class="btn btn-primary" id="saveCalendarBtn">Desa canvis</button>
            </div>
          </div>
        </div>
      </div>
      <!-- Modal d'estadístiques -->
      <div class="modal fade" id="statsModal" tabindex="-1" aria-labelledby="statsModalLabel" aria-hidden="true">
        <div class="modal-dialog modal-xl">
          <div class="modal-content">
            <div class="modal-header">
              <h5 class="modal-title" id="statsModalLabel"><i class="bi bi-bar-chart-line"></i> Estadístiques</h5>
              <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Tanca"></button>
            </div>
            <div class="modal-body" id="stats-body" style="min-height:400px;">
              <div class="text-center py-5"><div class="spinner-border text-primary" role="status"></div><p class="mt-2 text-muted">Carregant estadístiques...</p></div>
            </div>
            <div class="modal-footer">
              <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Tanca</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  `;
  bindStaticEvents();
}

function bindStaticEvents() {
  document.getElementById("create-file").onclick = createFile;
  const searchBtn = document.getElementById("search-btn");
  const searchPlusBtn = document.getElementById("search-plus-btn");
  const searchInput = document.getElementById("search-word");
  const testBtn = document.getElementById("show-test");
  const addNewBtn = document.getElementById("add-new-word-btn");
  const filterChk = document.getElementById("filter-pending");
  const validatedChk = document.getElementById("filter-validated");
  const favoritesChk = document.getElementById("filter-favorites");
  const hideInCalendarChk = document.getElementById("hide-in-calendar");
  const settingsBtn = document.getElementById("settings-btn");
  const calendarBtn = document.getElementById("calendar-btn");
  const difficultySelector = document.getElementById("difficulty-selector");

  if (filterChk) {
    filterChk.checked = showOnlyPending;
    filterChk.onchange = () => {
      showOnlyPending = filterChk.checked;
      // Si activem pendents, desactivem validats
      if (showOnlyPending && validatedChk) {
        showOnlyValidated = false;
        validatedChk.checked = false;
      }
      renderFileList();
    };
  }
  if (validatedChk) {
    validatedChk.checked = showOnlyValidated;
    validatedChk.onchange = () => {
      showOnlyValidated = validatedChk.checked;
      // Si activem validats, desactivem pendents
      if (showOnlyValidated && filterChk) {
        showOnlyPending = false;
        filterChk.checked = false;
      }
      renderFileList();
    };
  }
  if (favoritesChk) {
    favoritesChk.checked = showOnlyFavorites;
    favoritesChk.onchange = () => {
      showOnlyFavorites = favoritesChk.checked;
      renderFileList();
    };
  }
  if (hideInCalendarChk) {
    hideInCalendarChk.checked = showInCalendar;
    hideInCalendarChk.onchange = () => {
      showInCalendar = hideInCalendarChk.checked;
      renderFileList();
    };
  }
  if (searchBtn) searchBtn.onclick = () => triggerSearch(searchInput.value);
  if (searchPlusBtn)
    searchPlusBtn.onclick = () => triggerAdvancedSearch(searchInput.value);
  if (searchInput) {
    searchInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") triggerSearch(searchInput.value);
    });
  }

  // Botó toggle de mode REGEX
  const regexToggleBtn = document.getElementById("regex-toggle-btn");
  if (regexToggleBtn) {
    // Aplica l'estat inicial
    updateRegexToggleUI(regexToggleBtn);

    regexToggleBtn.onclick = (e) => {
      e.preventDefault();
      e.stopPropagation();
      regexModeActive = !regexModeActive;
      updateRegexToggleUI(regexToggleBtn);
    };
  }

  if (testBtn) testBtn.onclick = toggleTestOverlay;
  if (addNewBtn) addNewBtn.onclick = promptAddNewWord;
  const iaShortcutsBtn = document.getElementById("show-ia-shortcuts");
  if (iaShortcutsBtn) iaShortcutsBtn.onclick = openIAShortcutsModal;
  if (settingsBtn) settingsBtn.onclick = openSettingsModal;
  if (calendarBtn) calendarBtn.onclick = openCalendarModal;
  const statsBtn = document.getElementById("stats-btn");
  if (statsBtn) statsBtn.onclick = openStatsModal;

  // Event per al selector de dificultat
  if (difficultySelector) {
    difficultySelector.onchange = () => {
      if (!selected) return;
      const newDifficulty = difficultySelector.value;
      fetch(`${DIFFICULTIES_API}/${selected}`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({ difficulty: newDifficulty }),
      })
        .then((r) => {
          if (!r.ok) throw new Error();
          if (newDifficulty) {
            difficulties[selected] = newDifficulty;
          } else {
            delete difficulties[selected];
          }
          renderFileList(); // Actualitza la llista per mostrar/amagar etiquetes
        })
        .catch(() => {
          alert("Error desant dificultat");
          updateDifficultySelector(); // Reverteix selector
        });
    };
  }
}

// Actualitza l'estil del botó toggle de REGEX segons l'estat
function updateRegexToggleUI(btn) {
  if (!btn) return;
  if (regexModeActive) {
    btn.style.background = "#0d6efd";
    btn.style.color = "#fff";
    btn.style.borderColor = "#0d6efd";
    btn.title = "Mode REGEX activat (clic per desactivar)";
  } else {
    btn.style.background = "#f8f9fa";
    btn.style.color = "#666";
    btn.style.borderColor = "#ccc";
    btn.title = "Mode REGEX (clic per activar/desactivar)";
  }
}

// Funcions per la configuració general
function openSettingsModal() {
  loadSettings(); // Carrega la configuració actual

  // Actualitza l'estat del switch
  const autoScrollSwitch = document.getElementById("autoScrollSwitch");
  if (autoScrollSwitch) {
    autoScrollSwitch.checked = settings.autoScroll;
  }

  // Obre el modal
  const settingsModal = new bootstrap.Modal(
    document.getElementById("settingsModal"),
  );
  settingsModal.show();

  // Assigna l'event del botó Desa
  const saveBtn = document.getElementById("saveSettingsBtn");
  if (saveBtn) {
    saveBtn.onclick = saveSettingsFromModal;
  }

  // Bind del botó de neteja de cache
  const clearBtn = document.getElementById("clearCacheBtn");
  const statusEl = document.getElementById("clearCacheStatus");
  if (clearBtn) {
    clearBtn.onclick = async () => {
      const ok = await ensureAuthenticated();
      if (!ok) return;
      if (!confirm("Segur que voleu netejar la memòria cau del servidor?"))
        return;
      try {
        clearBtn.disabled = true;
        if (statusEl) statusEl.style.display = "inline";
        const res = await fetch(`${API_BASE}/cache/clear`, {
          method: "POST",
          headers: { ...authHeaders() },
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({ detail: "Error" }));
          throw new Error(err.detail || "Error netejant la memòria cau");
        }
        const data = await res.json().catch(() => ({ ok: true }));
        const cleared =
          data && typeof data.cleared === "number" ? data.cleared : null;
        alert(
          cleared !== null
            ? `Memòria cau netejada (${cleared} entrades)`
            : "Memòria cau netejada",
        );
      } catch (e) {
        alert(e.message || "Error desconegut netejant la cache");
      } finally {
        clearBtn.disabled = false;
        if (statusEl) statusEl.style.display = "none";
      }
    };
  }
}

function saveSettingsFromModal() {
  // Actualitza la configuració amb els valors del modal
  const autoScrollSwitch = document.getElementById("autoScrollSwitch");
  if (autoScrollSwitch) {
    settings.autoScroll = autoScrollSwitch.checked;
  }

  // Desa la configuració
  saveSettings();

  // Tanca el modal
  const settingsModal = bootstrap.Modal.getInstance(
    document.getElementById("settingsModal"),
  );
  if (settingsModal) {
    settingsModal.hide();
  }

  // Mostra confirmació
  console.log("Configuració desada:", settings);
}

// Funcions per la gestió del calendari
async function loadCalendarGames() {
  try {
    const res = await fetch(`${API_BASE}/games`, {
      headers: { ...authHeaders() },
    });
    if (!res.ok) throw new Error("No s'ha pogut carregar games.json");
    const data = await res.json();
    calendarGames = data.games || [];
    calendarStartDate = data.startDate || "23-12-2025";
  } catch (e) {
    console.error("Error carregant games.json:", e);
    calendarGames = [];
    calendarStartDate = "23-12-2025";
  }
}

// Funció per calcular la data d'un joc segons el seu ID (usant camp 'dies' acumulat)
function getGameDate(gameId) {
  try {
    // Format de startDate: DD-MM-YYYY
    const [day, month, year] = calendarStartDate.split("-").map(Number);
    const startDate = new Date(year, month - 1, day);

    // Calcular dies acumulats fins al joc anterior
    const sortedGames = [...calendarGames].sort((a, b) => a.id - b.id);
    let cumulativeDays = 0;
    for (const game of sortedGames) {
      if (game.id === gameId) {
        break;
      }
      cumulativeDays += game.dies || 1;
    }

    const gameDate = new Date(startDate);
    gameDate.setDate(startDate.getDate() + cumulativeDays);

    // Formatar com DD-MM-YYYY
    const d = String(gameDate.getDate()).padStart(2, "0");
    const m = String(gameDate.getMonth() + 1).padStart(2, "0");
    const y = gameDate.getFullYear();

    return `${d}-${m}-${y}`;
  } catch (e) {
    console.error("Error calculant data del joc:", e);
    return "--";
  }
}

function getAvailableWords() {
  // Retorna llista de paraules disponibles al directori data/words/
  return files.map((f) => f.replace(".json", ""));
}

function getFilteredWords() {
  let words = getAvailableWords();

  if (calendarFilterValidated) {
    words = words.filter(
      (w) =>
        validations[w + ".json"] === "validated" ||
        validations[w + ".json"] === "approved",
    );
  }

  if (calendarFilterFavorites) {
    words = words.filter((w) => favorites[w + ".json"]);
  }

  if (calendarFilterUnique) {
    // Filtra paraules que ja estan a la llista
    const usedWords = new Set(calendarGames.map((g) => g.name));
    words = words.filter((w) => !usedWords.has(w));
  }

  return words.sort();
}

function renderCalendarList() {
  const container = document.getElementById("calendar-list");
  if (!container) return;

  // Desa l'índex del focus actual
  const focusedElement = document.activeElement;
  const focusedIdx = focusedElement?.dataset?.calIdx
    ? parseInt(focusedElement.dataset.calIdx)
    : null;

  const availableWords = getFilteredWords();
  const usedWords = new Map();

  // Detecta repeticions
  calendarGames.forEach((game, idx) => {
    if (!usedWords.has(game.name)) {
      usedWords.set(game.name, [idx]);
    } else {
      usedWords.get(game.name).push(idx);
    }
  });

  container.innerHTML = calendarGames
    .map((game, idx) => {
      const isDuplicate =
        usedWords.get(game.name).length > 1 &&
        usedWords.get(game.name)[0] !== idx;
      const isInvalid = game.name && !files.includes(game.name + ".json");
      const bgClass = isDuplicate
        ? "bg-warning bg-opacity-25"
        : isInvalid
          ? "bg-danger bg-opacity-25"
          : "";

      const gameDate = getGameDate(game.id);
      const dies = game.dies || 1;
      const diesBadgeColor =
        dies === 1
          ? "bg-secondary"
          : dies === 7
            ? "bg-info text-dark"
            : "bg-primary";
      const diesBadgeTitle = dies === 1 ? "Diari (1 dia)" : `${dies} dies`;
      const diesBadge = `<span class="badge ${diesBadgeColor}" style="font-size: 10px; padding: 2px 4px;" title="${diesBadgeTitle}">${dies}d</span>`;
      return `
      <div class="d-flex align-items-center gap-2 mb-2 p-2 border rounded ${bgClass}" data-cal-idx="${idx}">
        <span class="text-muted" style="min-width: 40px;">${game.id}.</span>
        <span class="text-muted" style="min-width: 90px; font-size: 11px;">${gameDate}</span>
        ${diesBadge}
        <input type="text" 
               class="form-control form-control-sm calendar-word-input" 
               data-cal-idx="${idx}"
               value="${game.name}" 
               list="words-datalist-${idx}"
               placeholder="Escriu o selecciona...">
        <datalist id="words-datalist-${idx}">
          ${availableWords.map((w) => `<option value="${w}">`).join("")}
        </datalist>
        <select class="form-select form-select-sm calendar-dies-select" data-cal-idx="${idx}" style="width: 60px; min-width: 60px;" title="Durada del joc en dies">
          ${[1, 2, 3, 4, 5, 6, 7].map((d) => `<option value="${d}" ${dies === d ? "selected" : ""}>${d}d</option>`).join("")}
        </select>
        ${
          isDuplicate
            ? '<small class="text-warning ms-1" title="Paraula repetida: aquesta paraula ja apareix a la llista"><i class="bi bi-exclamation-triangle"></i></small>'
            : ""
        }
        ${
          isInvalid
            ? '<small class="text-danger ms-1" title="Paraula no trobada: el fitxer /data/words/' +
              game.name +
              '.json no existeix"><i class="bi bi-x-circle"></i></small>'
            : ""
        }
        <button class="btn btn-sm btn-outline-danger calendar-remove-btn" data-cal-idx="${idx}">
          <i class="bi bi-trash"></i>
        </button>
      </div>
    `;
    })
    .join("");

  // Bind events
  container.querySelectorAll(".calendar-word-input").forEach((input) => {
    let updateTimeout;
    input.addEventListener("input", (e) => {
      const idx = parseInt(e.target.dataset.calIdx);
      calendarGames[idx].name = e.target.value.trim();

      // Actualitza només les validacions visuals sense re-renderitzar tot
      const parentDiv = e.target.closest("[data-cal-idx]");
      const currentWord = e.target.value.trim();
      const isDuplicate =
        calendarGames.filter((g) => g.name === currentWord).length > 1;
      const isInvalid = currentWord && !files.includes(currentWord + ".json");

      parentDiv.className = parentDiv.className.replace(/bg-\w+-\w+-\d+/g, "");
      if (isDuplicate) {
        parentDiv.classList.add("bg-warning", "bg-opacity-25");
      } else if (isInvalid) {
        parentDiv.classList.add("bg-danger", "bg-opacity-25");
      }
    });
  });

  // Bind events per selector de dies
  container.querySelectorAll(".calendar-dies-select").forEach((select) => {
    select.addEventListener("change", (e) => {
      const idx = parseInt(e.target.dataset.calIdx);
      calendarGames[idx].dies = parseInt(e.target.value);
      // Re-renderitzar per actualitzar les dates
      renderCalendarList();
    });
  });

  container.querySelectorAll(".calendar-remove-btn").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      const idx = parseInt(e.currentTarget.dataset.calIdx);
      if (
        confirm(
          `Segur que voleu eliminar la paraula ${calendarGames[idx].name}?`,
        )
      ) {
        calendarGames.splice(idx, 1);
        // Reassigna IDs (preservant 'dies')
        calendarGames.forEach((g, i) => (g.id = i + 1));
        renderCalendarList();
      }
    });
  });

  // Restaura el focus si hi havia
  if (focusedIdx !== null) {
    const newInput = container.querySelector(
      `input[data-cal-idx="${focusedIdx}"]`,
    );
    if (newInput) {
      newInput.focus();
    }
  }
}

async function openCalendarModal() {
  // Recarrega sempre el fitxer games.json per assegurar sincronització amb el servidor
  await loadCalendarGames();

  // Actualitza filtres
  const filterValidated = document.getElementById("filter-cal-validated");
  const filterFavorites = document.getElementById("filter-cal-favorites");
  const filterUnique = document.getElementById("filter-cal-unique");

  if (filterValidated) {
    filterValidated.checked = calendarFilterValidated;
    filterValidated.onchange = () => {
      calendarFilterValidated = filterValidated.checked;
      renderCalendarList();
    };
  }

  if (filterFavorites) {
    filterFavorites.checked = calendarFilterFavorites;
    filterFavorites.onchange = () => {
      calendarFilterFavorites = filterFavorites.checked;
      renderCalendarList();
    };
  }

  if (filterUnique) {
    filterUnique.checked = calendarFilterUnique;
    filterUnique.onchange = () => {
      calendarFilterUnique = filterUnique.checked;
      renderCalendarList();
    };
  }

  renderCalendarList();

  // Obre el modal
  const calendarModal = new bootstrap.Modal(
    document.getElementById("calendarModal"),
  );
  calendarModal.show();

  // Bind botó afegir
  const addBtn = document.getElementById("add-calendar-item");
  if (addBtn) {
    addBtn.onclick = () => {
      const newId =
        calendarGames.length > 0
          ? Math.max(...calendarGames.map((g) => g.id)) + 1
          : 1;
      const newIdx = calendarGames.length;
      calendarGames.push({ id: newId, name: "", dies: 7 });
      renderCalendarList();

      // Posa focus al nou input
      setTimeout(() => {
        const newInput = document.querySelector(
          `input[data-cal-idx="${newIdx}"]`,
        );
        if (newInput) {
          newInput.focus();
          // Scroll fins al final
          const container = document.getElementById("calendar-list");
          if (container) {
            container.scrollTop = container.scrollHeight;
          }
        }
      }, 0);
    };
  }

  // Bind botó desar
  const saveBtn = document.getElementById("saveCalendarBtn");
  if (saveBtn) {
    saveBtn.onclick = saveCalendarGames;
  }
}

async function saveCalendarGames() {
  // Valida que no hi hagi paraules buides
  const emptyWords = calendarGames.filter((g) => !g.name || !g.name.trim());
  if (emptyWords.length > 0) {
    alert(
      `No es pot desar: hi ha ${emptyWords.length} paraula(es) buida(es). Emplena-les o elimina-les.`,
    );
    return;
  }

  try {
    const res = await fetch(`${API_BASE}/save-games`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ games: calendarGames }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: "Error desant" }));
      alert(err.detail || "Error desant el calendari");
      return;
    }

    // Recarrega el fitxer games.json del servidor per assegurar sincronització
    await loadCalendarGames();

    // Actualitza la llista de fitxers per reflectir els canvis del calendari
    renderFileList();

    alert("Calendari desat correctament!");

    // Tanca el modal
    const calendarModal = bootstrap.Modal.getInstance(
      document.getElementById("calendarModal"),
    );
    if (calendarModal) {
      calendarModal.hide();
    }
  } catch (e) {
    console.error("Error desant calendari:", e);
    alert("Error de xarxa desant el calendari");
  }
}

async function addTestWordsPrompt() {
  const txt = prompt(
    "Paraules a afegir (separa per comes o salts de línia)",
    "",
  );
  if (txt === null) return;
  const parts = txt
    .split(/[\n,]/)
    .map((s) => s.trim())
    .filter((s) => s.length);
  if (!parts.length) return;
  try {
    const res = await fetch(`${API_BASE}/test-words`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ words: parts }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: "Error" }));
      alert(err.detail || "Error afegint");
      return;
    }
    const data = await res.json();
    alert(`Afegides ${data.added.length} (total ${data.total})`);
    refreshTestOverlayIfVisible();
  } catch (e) {
    alert("Error de xarxa");
  }
}

async function addSynonymsTestPrompt() {
  if (!selected) return;

  const word = prompt("Paraula base per obtenir sinònims:", "");
  if (!word || !word.trim()) return;

  const wordTrimmed = word.trim();

  try {
    // Obté els sinònims de la paraula
    const res = await fetch(
      `${RANKINGS_API}/${selected}/test-words-synonyms-custom/${encodeURIComponent(
        wordTrimmed,
      )}`,
      { headers: { ...authHeaders() } },
    );

    if (!res.ok) {
      alert("Error obtenint sinònims");
      return;
    }

    const data = await res.json();

    if (!data.groups || data.groups.length === 0) {
      alert(`No s'han trobat sinònims per "${wordTrimmed}"`);
      return;
    }

    // Guarda les dades de sinònims personalitzats
    customSynonymsData = data;

    // Refresca la vista del test i obre la pestanya del test acabat de crear
    refreshTestOverlayIfVisible("custom");
  } catch (e) {
    alert("Error de xarxa");
  }
}

// Funció per obrir modal de test personalitzat amb textbox
function openCustomTextTestModal() {
  if (!selected) return;

  const modalHtml = `
    <div class="modal fade" id="customTextModal" tabindex="-1" aria-labelledby="customTextModalLabel" aria-hidden="true">
      <div class="modal-dialog modal-lg">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title" id="customTextModalLabel">Test Personalitzat - Enganxa text</h5>
            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Tanca"></button>
          </div>
          <div class="modal-body">
            <p class="text-muted small">Enganxa text (es netejaran automàticament els caràcters no vàlids). Feu una línia per cada paraula.</p>
            <p class="text-muted small"> Podeu utilitzar aquest prompt: "llista 500 paraules úniques relacionades semànticament amb la paraula <b>PARAULA</b>. (només paraules simples singulars). Mostra el resultat en un bloc de codi."</p>
            <textarea class="form-control" id="custom-text-textarea" rows="15" placeholder="Enganxa aquí el text d'internet..."></textarea>
            <div class="mt-2">
              <small class="text-muted">Paraules: <span id="word-count">0</span></small>
            </div>
          </div>
          <div class="modal-footer">
            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel·la</button>
            <button type="button" class="btn btn-outline-primary" id="open-ai-search-btn">Cerca AI</button>
            <button type="button" class="btn btn-primary" id="create-custom-test-btn">Crear Test</button>
          </div>
        </div>
      </div>
    </div>
  `;

  // Elimina modal anterior si existeix
  const oldModal = document.getElementById("customTextModal");
  if (oldModal) oldModal.remove();

  // Afegeix modal al DOM
  document.body.insertAdjacentHTML("beforeend", modalHtml);

  const modalEl = document.getElementById("customTextModal");
  const modal = new bootstrap.Modal(modalEl);
  const textarea = document.getElementById("custom-text-textarea");
  const wordCountSpan = document.getElementById("word-count");

  // Event per netejar text automàticament quan canvia
  textarea.addEventListener("input", (e) => {
    const cursorPos = textarea.selectionStart;
    const textBefore = textarea.value.substring(0, cursorPos);
    const textAfter = textarea.value.substring(cursorPos);

    // Converteix comes en salts de línia
    let cleaned = textarea.value.replace(/,|;/g, "\n");

    // Neteja el text: manté només lletres catalanes i salts de línia
    cleaned = cleaned.replace(/[^a-zA-ZàèéíòóúÀÈÉÍÒÓÚïüÏÜçÇ·\s\n]/g, "");

    // Converteix múltiples salts de línia en un de sol
    cleaned = cleaned.replace(/\n{2,}/g, "\n");

    // Converteix espais múltiples en un de sol
    cleaned = cleaned.replace(/[ \t]+/g, " ");

    // Aplica el text netejat
    textarea.value = cleaned;

    // Calcula la nova posició del cursor després de netejar
    const cleanedBefore = textBefore
      .replace(/,/g, "\n")
      .replace(/[^a-zA-ZàèéíòóúÀÈÉÍÒÓÚïüÏÜçÇ·\s\n]/g, "")
      .replace(/\n{2,}/g, "\n")
      .replace(/[ \t]+/g, " ");
    const newCursorPos = cleanedBefore.length;

    // Restaura la posició del cursor
    textarea.setSelectionRange(newCursorPos, newCursorPos);

    // Actualitza contador de paraules
    const wordCount = cleaned
      ? cleaned.split("\n").filter((l) => l.trim()).length
      : 0;
    wordCountSpan.textContent = wordCount;
  });

  // Event per crear test
  document.getElementById("create-custom-test-btn").onclick = async () => {
    const text = textarea.value.trim();
    if (!text) {
      alert("El text està buit");
      return;
    }

    const words = text.split("\n").filter((w) => w.trim());
    if (words.length === 0) {
      alert("No hi ha paraules vàlides");
      return;
    }

    // Processa les paraules amb el rànquing actual
    const ranking = await getCurrentRanking();
    if (!ranking) {
      alert("Error carregant el rànquing");
      return;
    }

    const processedWords = words.map((word) => {
      const wordLower = word.toLowerCase().trim();
      if (wordLower in ranking) {
        return { word: word, found: true, pos: ranking[wordLower] };
      } else {
        return { word: word, found: false };
      }
    });

    customTextData = {
      words: processedWords,
      count: processedWords.length,
    };

    modal.hide();
    // Mostra la vista del test si no és visible i obre la pestanya del test personalitzat
    if (!testVisible) {
      testVisible = true;
      testState.activeTab = "text";
      await loadTestOverlayData();
      // Canvia a la pestanya de text personalitzat
      setTimeout(() => switchTestTab("text"), 50);
    } else {
      refreshTestOverlayIfVisible("text");
    }
  };

  // Botó per obrir el modal de cerca AI
  document.getElementById("open-ai-search-btn").onclick = () => {
    openAiSearchModal(textarea);
  };

  // Neteja el modal del DOM quan es tanca
  modalEl.addEventListener("hidden.bs.modal", () => {
    modalEl.remove();
  });

  modal.show();
}

// Modal de dreçeres IA per test personalitzat
function openIAShortcutsModal() {
  if (!selected) return;

  // Obtenim la paraula seleccionada (posició 0 del rànquing)
  const baseWord = wordsByPos[0] ? wordsByPos[0].word : "";

  const modalHtml = `
    <div class="modal fade" id="iaShortcutsModal" tabindex="-1" aria-labelledby="iaShortcutsModalLabel" aria-hidden="true">
      <div class="modal-dialog">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title" id="iaShortcutsModalLabel">Dreçeres IA - Test Personalitzat</h5>
            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Tanca"></button>
          </div>
          <div class="modal-body">
            <p class="text-muted small mb-3">Selecciona una opció per generar un prompt preparat per a la cerca IA.</p>
            <div class="d-grid gap-2">
              <button type="button" class="btn btn-outline-primary text-start" id="ia-100-similars">
                <strong>100 paraules similars</strong>
                <br><small class="text-muted">Genera 100 noms i verbs relacionats amb el concepte</small>
              </button>
              <button type="button" class="btn btn-outline-primary text-start" id="ia-eliminar-dissimilars">
                <strong>Eliminar dissimilars (300 primers)</strong>
                <br><small class="text-muted">Escull les 50 paraules menys relacionades del rànquing</small>
              </button>
              <button type="button" class="btn btn-outline-primary text-start" id="ia-sin-ant-hiper-hipo">
                <strong>SIN/ANT/HIPER/HIPO</strong>
                <br><small class="text-muted">Sinònims, antònims, hiperònims i hipònims</small>
              </button>
            </div>
          </div>
          <div class="modal-footer">
            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel·la</button>
          </div>
        </div>
      </div>
    </div>
  `;

  // Elimina modal anterior si existeix
  const oldModal = document.getElementById("iaShortcutsModal");
  if (oldModal) oldModal.remove();

  // Afegeix modal al DOM
  document.body.insertAdjacentHTML("beforeend", modalHtml);

  const modalEl = document.getElementById("iaShortcutsModal");
  const modal = new bootstrap.Modal(modalEl);

  // Event per "100 paraules similars"
  document.getElementById("ia-100-similars").onclick = () => {
    const prompt = `Genera una llista de 100 noms i verbs únics en català relacionades amb el concepte de ${baseWord}`;
    modal.hide();
    openIAShortcutWithPrompt(prompt);
  };

  // Event per "Eliminar dissimilars (300 primers)"
  document.getElementById("ia-eliminar-dissimilars").onclick = async () => {
    // Obtenim els primers 300 del rànquing
    const first300 = [];
    for (let i = 0; i < 300; i++) {
      if (wordsByPos[i] && wordsByPos[i].word) {
        first300.push(wordsByPos[i].word);
      }
    }

    if (first300.length === 0) {
      alert(
        "No hi ha prou paraules carregades al rànquing. Carrega més dades primer.",
      );
      return;
    }

    const llistaParaules = first300.join(", ");
    const prompt = `De la següent llista escull les 50 paraules semànticament menys relacionades amb la paraula ${baseWord}: \n${llistaParaules}`;
    modal.hide();
    openIAShortcutWithPrompt(prompt);
  };

  // Event per "SIN/ANT/HIPER/HIPO"
  document.getElementById("ia-sin-ant-hiper-hipo").onclick = () => {
    const prompt = `Fes una llista de paraules del diccionari català que siguin sinònims, antònims, hiperònims o hipònims de la paraula "${baseWord}". Usa paraules simples (no compostes). Només mostra les paraules.`;
    modal.hide();
    openIAShortcutWithPrompt(prompt);
  };

  // Neteja el modal del DOM quan es tanca
  modalEl.addEventListener("hidden.bs.modal", () => {
    modalEl.remove();
  });

  modal.show();
}

// Obre el modal de test personalitzat amb un prompt preparat per IA
function openIAShortcutWithPrompt(preparedPrompt) {
  if (!selected) return;

  const modalHtml = `
    <div class="modal fade" id="customTextModal" tabindex="-1" aria-labelledby="customTextModalLabel" aria-hidden="true">
      <div class="modal-dialog modal-lg">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title" id="customTextModalLabel">Test Personalitzat - Enganxa text</h5>
            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Tanca"></button>
          </div>
          <div class="modal-body">
            <p class="text-muted small">Enganxa text (es netejaran automàticament els caràcters no vàlids). Feu una línia per cada paraula.</p>
            <p class="text-muted small"> Podeu utilitzar aquest prompt: "llista 500 paraules úniques relacionades semànticament amb la paraula <b>PARAULA</b>. (només paraules simples singulars). Mostra el resultat en un bloc de codi."</p>
            <textarea class="form-control" id="custom-text-textarea" rows="15" placeholder="Enganxa aquí el text d'internet..."></textarea>
            <div class="mt-2">
              <small class="text-muted">Paraules: <span id="word-count">0</span></small>
            </div>
          </div>
          <div class="modal-footer">
            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel·la</button>
            <button type="button" class="btn btn-outline-primary" id="open-ai-search-btn">Cerca AI</button>
            <button type="button" class="btn btn-primary" id="create-custom-test-btn">Crear Test</button>
          </div>
        </div>
      </div>
    </div>
  `;

  // Elimina modal anterior si existeix
  const oldModal = document.getElementById("customTextModal");
  if (oldModal) oldModal.remove();

  // Afegeix modal al DOM
  document.body.insertAdjacentHTML("beforeend", modalHtml);

  const modalEl = document.getElementById("customTextModal");
  const modal = new bootstrap.Modal(modalEl);
  const textarea = document.getElementById("custom-text-textarea");
  const wordCountSpan = document.getElementById("word-count");

  // Event per netejar text automàticament quan canvia
  textarea.addEventListener("input", (e) => {
    const cursorPos = textarea.selectionStart;
    const textBefore = textarea.value.substring(0, cursorPos);
    const textAfter = textarea.value.substring(cursorPos);

    // Converteix comes en salts de línia
    let cleaned = textarea.value.replace(/,|;/g, "\n");

    // Neteja el text: manté només lletres catalanes i salts de línia
    cleaned = cleaned.replace(/[^a-zA-ZàèéíòóúÀÈÉÍÒÓÚïüÏÜçÇ·\s\n]/g, "");

    // Converteix múltiples salts de línia en un de sol
    cleaned = cleaned.replace(/\n{2,}/g, "\n");

    // Converteix espais múltiples en un de sol
    cleaned = cleaned.replace(/[ \t]+/g, " ");

    // Aplica el text netejat
    textarea.value = cleaned;

    // Calcula la nova posició del cursor després de netejar
    const cleanedBefore = textBefore
      .replace(/,/g, "\n")
      .replace(/[^a-zA-ZàèéíòóúÀÈÉÍÒÓÚïüÏÜçÇ·\s\n]/g, "")
      .replace(/\n{2,}/g, "\n")
      .replace(/[ \t]+/g, " ");
    const newCursorPos = cleanedBefore.length;

    // Restaura la posició del cursor
    textarea.setSelectionRange(newCursorPos, newCursorPos);

    // Actualitza contador de paraules
    const wordCount = cleaned
      ? cleaned.split("\n").filter((l) => l.trim()).length
      : 0;
    wordCountSpan.textContent = wordCount;
  });

  // Event per crear test
  document.getElementById("create-custom-test-btn").onclick = async () => {
    const text = textarea.value.trim();
    if (!text) {
      alert("El text està buit");
      return;
    }

    const words = text.split("\n").filter((w) => w.trim());
    if (words.length === 0) {
      alert("No hi ha paraules vàlides");
      return;
    }

    // Processa les paraules amb el rànquing actual
    const ranking = await getCurrentRanking();
    if (!ranking) {
      alert("Error carregant el rànquing");
      return;
    }

    const processedWords = words.map((word) => {
      const wordLower = word.toLowerCase().trim();
      if (wordLower in ranking) {
        return { word: word, found: true, pos: ranking[wordLower] };
      } else {
        return { word: word, found: false };
      }
    });

    customTextData = {
      words: processedWords,
      count: processedWords.length,
    };

    modal.hide();
    // Mostra la vista del test si no és visible i obre la pestanya del test personalitzat
    if (!testVisible) {
      testVisible = true;
      testState.activeTab = "text";
      await loadTestOverlayData();
      // Canvia a la pestanya de text personalitzat
      setTimeout(() => switchTestTab("text"), 50);
    } else {
      refreshTestOverlayIfVisible("text");
    }
  };

  // Botó per obrir el modal de cerca AI
  document.getElementById("open-ai-search-btn").onclick = () => {
    openAiSearchModal(textarea);
  };

  // Neteja el modal del DOM quan es tanca
  modalEl.addEventListener("hidden.bs.modal", () => {
    modalEl.remove();
  });

  modal.show();

  // Obre el modal de cerca AI amb el prompt preparat després que s'hagi mostrat el modal base
  setTimeout(() => {
    openAiSearchModalWithPrompt(textarea, preparedPrompt);
  }, 300);
}

// Modal flotant per fer una cerca AI i omplir el textarea del test personalitzat
function openAiSearchModal(targetTextarea) {
  const defaultPrompt =
    "Genera una llista de 100 noms i verbs únics en català relacionades amb el concepte de";

  const aiModalHtml = `
    <div class="modal fade" id="aiSearchModal" tabindex="-1" aria-labelledby="aiSearchModalLabel" aria-hidden="true">
      <div class="modal-dialog">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title" id="aiSearchModalLabel">Cerca AI</h5>
            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Tanca"></button>
          </div>
          <div class="modal-body">
            <label class="form-label">Backend AI</label>
            <select class="form-select mb-3" id="ai-backend-select">
              <option value="">Per defecte (servidor)</option>
              <option value="OPENAI">OpenAI</option>
              <option value="CHATANYWHERE">ChatAnywhere</option>
              <option value="GEMINI">Gemini</option>
            </select>
            <label class="form-label">Prompt</label>
            <textarea class="form-control" id="ai-prompt-input" rows="4">${defaultPrompt}</textarea>
            <div class="form-text">Modifica el prompt per especificar el concepte abans d'enviar.</div>
            <div id="ai-error" class="text-danger mt-2" style="display:none;"></div>
          </div>
          <div class="modal-footer">
            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Tanca</button>
            <button type="button" class="btn btn-primary" id="ai-send-btn">Executa</button>
          </div>
        </div>
      </div>
    </div>`;

  // Elimina si existeix
  const old = document.getElementById("aiSearchModal");
  if (old) old.remove();
  document.body.insertAdjacentHTML("beforeend", aiModalHtml);

  const aiEl = document.getElementById("aiSearchModal");
  const aiModal = new bootstrap.Modal(aiEl);
  const promptEl = document.getElementById("ai-prompt-input");
  const errorEl = document.getElementById("ai-error");
  const sendBtn = document.getElementById("ai-send-btn");

  let sending = false;
  const backendSelect = document.getElementById("ai-backend-select");

  sendBtn.onclick = async () => {
    if (sending) return;
    const prompt = (promptEl.value || "").trim();
    const backend = backendSelect.value || undefined;
    errorEl.style.display = "none";
    errorEl.textContent = "";

    // Comprova que s'ha modificat el prompt
    if (prompt === defaultPrompt) {
      errorEl.textContent = "Modifiqueu el prompt abans d'enviar.";
      errorEl.style.display = "block";
      return;
    }

    try {
      sending = true;
      sendBtn.disabled = true;
      sendBtn.textContent = "Enviant...";
      const res = await fetch(AI_GENERATE_ENDPOINT, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({ prompt, backend }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Error" }));
        throw new Error(err.detail || "Error en la generació AI");
      }
      const data = await res.json();
      const words = Array.isArray(data.paraules) ? data.paraules : [];
      if (!words.length) throw new Error("La resposta AI no conté paraules");

      // Omple el textarea amb les paraules (una per línia) i neteja qualsevol contingut anterior
      targetTextarea.value = words.join("\n");
      // Força l'actualització del comptador i la neteja
      targetTextarea.dispatchEvent(new Event("input"));

      aiModal.hide();
    } catch (e) {
      errorEl.textContent = e.message || "Error desconegut";
      errorEl.style.display = "block";
    } finally {
      sending = false;
      sendBtn.disabled = false;
      sendBtn.textContent = "ENVIA";
    }
  };

  aiEl.addEventListener("hidden.bs.modal", () => aiEl.remove());
  aiModal.show();
}

// Modal flotant per fer una cerca AI amb prompt preparat (per dreçeres IA)
function openAiSearchModalWithPrompt(targetTextarea, preparedPrompt) {
  const aiModalHtml = `
    <div class="modal fade" id="aiSearchModal" tabindex="-1" aria-labelledby="aiSearchModalLabel" aria-hidden="true">
      <div class="modal-dialog">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title" id="aiSearchModalLabel">Cerca AI</h5>
            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Tanca"></button>
          </div>
          <div class="modal-body">
            <label class="form-label">Backend AI</label>
            <select class="form-select mb-3" id="ai-backend-select">
              <option value="">Per defecte (servidor)</option>
              <option value="OPENAI">OpenAI</option>
              <option value="CHATANYWHERE">ChatAnywhere</option>
              <option value="GEMINI">Gemini</option>
            </select>
            <label class="form-label">Prompt</label>
            <textarea class="form-control" id="ai-prompt-input" rows="6">${preparedPrompt}</textarea>
            <div class="form-text">Podeu editar el prompt abans d'enviar.</div>
            <div id="ai-error" class="text-danger mt-2" style="display:none;"></div>
          </div>
          <div class="modal-footer">
            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Tanca</button>
            <button type="button" class="btn btn-primary" id="ai-send-btn">Executa</button>
          </div>
        </div>
      </div>
    </div>`;

  // Elimina si existeix
  const old = document.getElementById("aiSearchModal");
  if (old) old.remove();
  document.body.insertAdjacentHTML("beforeend", aiModalHtml);

  const aiEl = document.getElementById("aiSearchModal");
  const aiModal = new bootstrap.Modal(aiEl);
  const promptEl = document.getElementById("ai-prompt-input");
  const errorEl = document.getElementById("ai-error");
  const sendBtn = document.getElementById("ai-send-btn");

  const backendSelect = document.getElementById("ai-backend-select");

  let sending = false;
  sendBtn.onclick = async () => {
    if (sending) return;
    const prompt = (promptEl.value || "").trim();
    const backend = backendSelect.value || undefined;
    errorEl.style.display = "none";
    errorEl.textContent = "";

    if (!prompt) {
      errorEl.textContent = "El prompt no pot estar buit.";
      errorEl.style.display = "block";
      return;
    }

    try {
      sending = true;
      sendBtn.disabled = true;
      sendBtn.textContent = "Enviant...";
      const res = await fetch(AI_GENERATE_ENDPOINT, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({ prompt, backend }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Error" }));
        throw new Error(err.detail || "Error en la generació AI");
      }
      const data = await res.json();
      const words = Array.isArray(data.paraules) ? data.paraules : [];
      if (!words.length) throw new Error("La resposta AI no conté paraules");

      // Omple el textarea amb les paraules (una per línia) i neteja qualsevol contingut anterior
      targetTextarea.value = words.join("\n");
      // Força l'actualització del comptador i la neteja
      targetTextarea.dispatchEvent(new Event("input"));

      aiModal.hide();
    } catch (e) {
      errorEl.textContent = e.message || "Error desconegut";
      errorEl.style.display = "block";
    } finally {
      sending = false;
      sendBtn.disabled = false;
      sendBtn.textContent = "Executa";
    }
  };

  aiEl.addEventListener("hidden.bs.modal", () => aiEl.remove());
  aiModal.show();
}

// Funció auxiliar per obtenir el rànquing actual
async function getCurrentRanking() {
  if (!selected) return null;
  try {
    const res = await fetch(
      `${RANKINGS_API}/${selected}?offset=0&limit=999999`,
      {
        headers: { ...authHeaders() },
      },
    );
    if (!res.ok) return null;
    const data = await res.json();
    const ranking = {};
    data.words.forEach((w) => {
      ranking[w.word.toLowerCase()] = w.pos;
    });
    return ranking;
  } catch (e) {
    return null;
  }
}

let testVisible = false;
async function toggleTestOverlay() {
  if (!selected) return;
  if (testVisible) {
    hideTestOverlay();
  } else {
    testVisible = true;
    await loadTestOverlayData();
  }
}

function hideTestOverlay() {
  testVisible = false;
  customSynonymsData = null; // Neteja dades de sinònims personalitzats
  customTextData = null; // Neteja dades de text personalitzat
  searchResultsData = null; // Neteja dades de cerca avançada
  const overlay = document.getElementById("test-overlay");
  const testColumn = document.getElementById("test-column");
  if (overlay) {
    overlay.style.display = "none";
    overlay.innerHTML = "";
  }
  if (testColumn) {
    testColumn.style.display = "none";
  }
}

async function loadTestOverlayData() {
  if (!testVisible || !selected) return;
  const overlay = document.getElementById("test-overlay");
  const testColumn = document.getElementById("test-column");
  if (!overlay) return;

  // Mostra la columna del test
  if (testColumn) {
    testColumn.style.display = "block";
  }

  overlay.style.display = "block";
  overlay.innerHTML =
    '<div class="text-muted small">Carregant paraules test…</div>';

  try {
    // Carrega tots els tests en paral·lel
    const [commonResponse, aiResponse, synonymsResponse, dtResponse] =
      await Promise.all([
        fetch(`${RANKINGS_API}/${selected}/test-words`, {
          headers: { ...authHeaders() },
        }),
        fetch(`${RANKINGS_API}/${selected}/test-words-ai`, {
          headers: { ...authHeaders() },
        }).catch(() => null), // No fa error si no existeix el fitxer AI
        fetch(`${RANKINGS_API}/${selected}/test-words-synonyms`, {
          headers: { ...authHeaders() },
        }).catch(() => null), // No fa error si no hi ha sinònims
        fetch(`${RANKINGS_API}/${selected}/test-words-deftest`, {
          headers: { ...authHeaders() },
        }).catch(() => null), // No fa error si no hi ha deftest
      ]);

    if (!testVisible) return; // si s'ha tancat mentre carregava

    if (!commonResponse.ok) throw new Error("Error carregant test comú");
    const commonData = await commonResponse.json();

    let aiData = null;
    if (aiResponse && aiResponse.ok) {
      aiData = await aiResponse.json();
    }

    let synonymsData = null;
    if (synonymsResponse && synonymsResponse.ok) {
      synonymsData = await synonymsResponse.json();
    }

    let dtData = null;
    if (dtResponse && dtResponse.ok) {
      dtData = await dtResponse.json();
    }

    renderTestTabs(commonData, aiData, synonymsData, overlay, dtData);
  } catch (e) {
    overlay.innerHTML =
      '<div class="text-danger small">Error carregant test</div>';
  }
}

window.toggleDtSection = function (header) {
  const container = header.nextElementSibling;
  const icon = header.querySelector(".dt-toggle-icon");
  if (container) {
    if (container.style.display === "none") {
      container.style.display = "grid";
      if (icon) icon.innerHTML = "&#x25BC;";
    } else {
      container.style.display = "none";
      if (icon) icon.innerHTML = "&#x25B6;";
    }
  }
};

function renderTestTabs(commonData, aiData, synonymsData, overlay, dtData) {
  const hasAiTest = aiData && aiData.words && aiData.words.length > 0;
  const hasSynonymsTest =
    synonymsData && synonymsData.groups && synonymsData.groups.length > 0;
  const hasCustomSynonyms =
    customSynonymsData &&
    customSynonymsData.groups &&
    customSynonymsData.groups.length > 0;
  const hasCustomText =
    customTextData && customTextData.words && customTextData.words.length > 0;
  const hasSearchResults =
    searchResultsData &&
    searchResultsData.words &&
    searchResultsData.words.length > 0;

  let tabsHtml = `
    <div style="display:flex;flex-wrap:wrap;justify-content:space-between;align-items:flex-start;gap:8px;margin-bottom:8px;">
      <div style="display:flex;flex-wrap:wrap;gap:8px;flex:1;">
        <div class="btn-group btn-group-sm" role="group">
          <button class="btn btn-outline-primary active" id="tab-common" onclick="switchTestTab('common')" title="Test Comú (${
            commonData.count
          })">Cm</button>
          ${
            hasAiTest
              ? `<button class="btn btn-outline-primary" id="tab-ai" onclick="switchTestTab('ai')" title="Test IA (${aiData.count})">IA</button>`
              : ""
          }
          ${
            hasSynonymsTest
              ? `<button class="btn btn-outline-primary" id="tab-synonyms" onclick="switchTestTab('synonyms')" title="Sinònims ${wordsByPos[0].word} (${synonymsData.count})">SC</button>`
              : ""
          }
          ${
            dtData && dtData.items && dtData.items.length > 0
              ? `<button class="btn btn-outline-primary" id="tab-dt" onclick="switchTestTab('dt')" title="Test a partir de definicions DIEC2 (${dtData.items.length})">D2</button>`
              : ""
          }
          ${
            hasCustomSynonyms
              ? `<button class="btn btn-outline-primary" id="tab-custom" onclick="switchTestTab('custom')" title="Sinònims ${customSynonymsData.base_word} (${customSynonymsData.count})">+S<span id="close-custom-test" style="margin-left:4px; cursor:pointer;" title="Tanca test">✕</span></button>`
              : `<button class="btn btn-outline-info" id="add-synonyms-test" title="Crear test de sinònims d'una paraula">+S</button>`
          }
          ${
            hasCustomText
              ? `<button class="btn btn-outline-primary" id="tab-text" onclick="switchTestTab('text')" title="Text personalitzat (${customTextData.count})"> P <span id="close-custom-text" style="margin-left:4px; cursor:pointer;" title="Tanca test">✕</span></button>`
              : `<button class="btn btn-outline-success" id="add-text-test" title="Crear test de text personalitzat">+P</button>`
          }
          ${
            hasSearchResults
              ? `<button class="btn btn-outline-primary" id="tab-search" onclick="switchTestTab('search')" title="Resultats de cerca (${searchResultsData.count})">Rs<span id="close-search-test" style="margin-left:4px; cursor:pointer;" title="Tanca resultats">✕</span></button>`
              : ""
          }
        </div>
        <div class="btn-group btn-group-sm edit-test-tools-actions" role="group">
          <button class="btn btn-outline-success" id="add-test-inside" title="Afegeix paraules al test comú">+Add</button>
          <button class="btn btn-outline-secondary" id="toggle-test-select" title="Mode selecció">Sel</button>
          <button class="btn btn-outline-danger" id="delete-selected-test" style="display:none;" title="Elimina seleccionades">Del</button>
        </div>
      </div>
      <div class="btn-group btn-group-sm edit-test-tools-controls" role="group">
        <button class="btn btn-outline-secondary" id="reload-test-positions" title="Recarrega posicions dels tests">↻</button>
        <button class="btn btn-outline-secondary" id="close-test" title="Tanca">✕</button>
      </div>
    </div>
  `;

  // Contingut de les pestanyes
  const commonRows = commonData.words
    .map((w) => {
      if (w.found) {
        return `<div class="test-row" data-word="${w.word}" data-pos="${
          w.pos
        }" draggable="true" style="cursor: grab; display: flex; align-items: center; justify-content: space-between;">
          <span style="color:${colorPerPos(w.pos)}">${w.word}</span>
          <div style="display: flex; align-items: center; gap: 4px;">
            <a href="#" data-pos="${
              w.pos
            }" class="jump" title="Ves a posició"> (${w.pos})</a>
            <button class="test-word-menu-btn" data-word="${
              w.word
            }" data-pos="${
              w.pos
            }" title="Més opcions" style="border: none; background: transparent; cursor: pointer; padding: 2px 4px; font-size: 12px; color: #666;">⋮</button>
          </div>
        </div>`;
      }
      return `<div class="test-row" data-word="${w.word}"><span class="text-muted">${w.word}</span> <span class="jump" style="font-size:11px">(no)</span></div>`;
    })
    .join("");

  let aiRows = "";
  if (hasAiTest) {
    aiRows = aiData.words
      .map((w) => {
        if (w.found) {
          return `<div class="test-row-ai" data-word="${w.word}" data-pos="${
            w.pos
          }" draggable="true" style="cursor: grab; display: flex; align-items: center; justify-content: space-between;">
            <span style="color:${colorPerPos(w.pos)}">${w.word}</span>
            <div style="display: flex; align-items: center; gap: 4px;">
              <a href="#" data-pos="${
                w.pos
              }" class="jump" title="Ves a posició"> (${w.pos})</a>
              <button class="test-word-menu-btn" data-word="${
                w.word
              }" data-pos="${
                w.pos
              }" title="Més opcions" style="border: none; background: transparent; cursor: pointer; padding: 2px 4px; font-size: 12px; color: #666;">⋮</button>
            </div>
          </div>`;
        }
        return `<div class="test-row-ai"><span class="text-muted">${w.word}</span> <span class="jump" style="font-size:11px">(no)</span></div>`;
      })
      .join("");
  }

  let synonymsRows = "";
  if (hasSynonymsTest) {
    if (synonymsData.groups && synonymsData.groups.length > 0) {
      synonymsRows = synonymsData.groups
        .map((group) => {
          const groupWords = group.words
            .map((w) => {
              if (w.found) {
                return `<div class="test-row-synonyms" data-word="${
                  w.word
                }" data-pos="${
                  w.pos
                }" draggable="true" style="cursor: grab; display: flex; align-items: center; justify-content: space-between;">
                  <span style="color:${colorPerPos(w.pos)}">${w.word}</span>
                  <div style="display: flex; align-items: center; gap: 4px;">
                    <a href="#" data-pos="${
                      w.pos
                    }" class="jump" title="Ves a posició"> (${w.pos})</a>
                    <button class="test-word-menu-btn" data-word="${
                      w.word
                    }" data-pos="${
                      w.pos
                    }" title="Més opcions" style="border: none; background: transparent; cursor: pointer; padding: 2px 4px; font-size: 12px; color: #666;">⋮</button>
                  </div>
                </div>`;
              }
              return `<div class="test-row-synonyms"><span class="text-muted">${w.word}</span> <span class="jump" style="font-size:11px">(no)</span></div>`;
            })
            .join("");

          return `
            <div class="synonym-group" style="margin-bottom: 12px;">
              <div class="synonym-group-header" style="font-size: 11px; color: #666; margin-bottom: 4px; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" title="${group.original_line}">
                ${group.original_line}
              </div>
              <div style="font-size:13px;display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:4px;">
                ${groupWords}
              </div>
            </div>
          `;
        })
        .join("");
    } else {
      synonymsRows =
        '<div class="text-muted small">No s\'han trobat sinònims per aquesta paraula</div>';
    }
  }

  // Genera contingut de sinònims personalitzats
  let customSynonymsRows = "";
  if (hasCustomSynonyms) {
    customSynonymsRows = customSynonymsData.groups
      .map((group) => {
        const groupWords = group.words
          .map((w) => {
            if (w.found) {
              return `<div class="test-row-synonyms" data-word="${
                w.word
              }" data-pos="${
                w.pos
              }" draggable="true" style="cursor: grab; display: flex; align-items: center; justify-content: space-between;">
                <span style="color:${colorPerPos(w.pos)}">${w.word}</span>
                <div style="display: flex; align-items: center; gap: 4px;">
                  <a href="#" data-pos="${
                    w.pos
                  }" class="jump" title="Ves a posició"> (${w.pos})</a>
                  <button class="test-word-menu-btn" data-word="${
                    w.word
                  }" data-pos="${
                    w.pos
                  }" title="Més opcions" style="border: none; background: transparent; cursor: pointer; padding: 2px 4px; font-size: 12px; color: #666;">⋮</button>
                </div>
              </div>`;
            }
            return `<div class="test-row-synonyms"><span class="text-muted">${w.word}</span> <span class="jump" style="font-size:11px">(no)</span></div>`;
          })
          .join("");

        return `
          <div class="synonym-group" style="margin-bottom: 12px;">
            <div class="synonym-group-header" style="font-size: 11px; color: #666; margin-bottom: 4px; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" title="${group.original_line}">
              ${group.original_line}
            </div>
            <div style="font-size:13px;display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:4px;">
              ${groupWords}
            </div>
          </div>
        `;
      })
      .join("");
  }

  // Genera contingut de text personalitzat
  let customTextRows = "";
  if (hasCustomText) {
    customTextRows = customTextData.words
      .map((w) => {
        if (w.found) {
          return `<div class="test-row" data-word="${w.word}" data-pos="${
            w.pos
          }" draggable="true" style="cursor: grab; display: flex; align-items: center; justify-content: space-between;">
            <span style="color:${colorPerPos(w.pos)}">${w.word}</span>
            <div style="display: flex; align-items: center; gap: 4px;">
              <a href="#" data-pos="${
                w.pos
              }" class="jump" title="Ves a posició"> (${w.pos})</a>
              <button class="test-word-menu-btn" data-word="${
                w.word
              }" data-pos="${
                w.pos
              }" title="Més opcions" style="border: none; background: transparent; cursor: pointer; padding: 2px 4px; font-size: 12px; color: #666;">⋮</button>
            </div>
          </div>`;
        }
        return `<div class="test-row"><span class="text-muted">${w.word}</span> <span class="jump" style="font-size:11px">(no)</span></div>`;
      })
      .join("");
  }

  // Genera contingut de resultats de cerca
  let searchRows = "";
  if (hasSearchResults) {
    searchRows = searchResultsData.words
      .map((w) => {
        return `<div class="test-row-search" data-word="${w.word}" data-pos="${
          w.pos
        }" draggable="true" style="cursor: grab; display: flex; align-items: center; justify-content: space-between; padding: 4px 6px; border: 1px solid #e0e0e0; border-radius: 4px; min-height: 28px;">
          <span style="color:${colorPerPos(w.pos)}">${w.word}</span>
          <div style="display: flex; align-items: center; gap: 4px;">
            <a href="#" data-pos="${
              w.pos
            }" class="jump" title="Ves a posició"> (${w.pos})</a>
            <button class="test-word-menu-btn" data-word="${
              w.word
            }" data-pos="${
              w.pos
            }" title="Més opcions" style="border: none; background: transparent; cursor: pointer; padding: 2px 4px; font-size: 12px; color: #666;">⋮</button>
          </div>
        </div>`;
      })
      .join("");
  }

  overlay.innerHTML = `
    ${tabsHtml}
    <div id="test-common-content" class="test-tab-content" style="display:block;">
      <div class="test-body" id="test-body" style="font-size:13px;display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:4px;">${commonRows}</div>
    </div>
    ${
      hasAiTest
        ? `
    <div id="test-ai-content" class="test-tab-content" style="display:none;">
      <div class="test-body-ai" id="test-body-ai" style="font-size:13px;display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:4px;">${aiRows}</div>
    </div>`
        : ""
    }
    ${
      hasSynonymsTest
        ? `
    <div id="test-synonyms-content" class="test-tab-content" style="display:none;">
      <div class="test-body-synonyms" id="test-body-synonyms" style="font-size:13px;">${synonymsRows}</div>
    </div>`
        : ""
    }
    ${
      dtData && dtData.items && dtData.items.length > 0
        ? `
    <div id="test-dt-content" class="test-tab-content" style="display:none;">
      <div class="test-body-dt" id="test-body-dt" style="font-size:13px;">
        ${dtData.items
          .map((item) => {
            const defHtml = `<div class="synonym-group-header" onclick="toggleDtSection(this)" style="cursor:pointer; font-size: 11px; color: #666; margin-bottom: 4px; font-weight: 500; white-space: normal;"><span class="dt-toggle-icon" style="display:inline-block; width:12px;font-family: initial;">▶</span> ${
              item.definition || ""
            }</div>`;
            const wordsHtml = (item.words || [])
              .map((w) => {
                if (w.found) {
                  return `<div class="test-row-synonyms" data-word="${
                    w.word
                  }" data-pos="${
                    w.pos
                  }" draggable="true" style="cursor: grab; display: flex; align-items: center; justify-content: space-between;">
                    <span style="color:${colorPerPos(w.pos)}">${w.word}</span>
                    <div style="display: flex; align-items: center; gap: 4px;">
                      <a href="#" data-pos="${
                        w.pos
                      }" class="jump" title="Ves a posició"> (${w.pos})</a>
                      <button class="test-word-menu-btn" data-word="${
                        w.word
                      }" data-pos="${
                        w.pos
                      }" title="Més opcions" style="border: none; background: transparent; cursor: pointer; padding: 2px 4px; font-size: 12px; color: #666;">⋮</button>
                    </div>
                  </div>`;
                }
                return `<div class="test-row-synonyms"><span class="text-muted">${w.word}</span> <span class="jump" style="font-size:11px">(no)</span></div>`;
              })
              .join("");
            return `<div class="synonym-group" style="margin-bottom: 12px;">${defHtml}<div class="dt-words" style="font-size:13px;display:none;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:4px;">${wordsHtml}</div></div>`;
          })
          .join("")}
      </div>
    </div>`
        : ""
    }
    ${
      hasCustomSynonyms
        ? `
    <div id="test-custom-content" class="test-tab-content" style="display:none;">
      <div class="test-body-custom" id="test-body-custom" style="font-size:13px;">${customSynonymsRows}</div>
    </div>`
        : ""
    }
    ${
      hasCustomText
        ? `
    <div id="test-text-content" class="test-tab-content" style="display:none;">
      <div class="test-body-text" id="test-body-text" style="font-size:13px;display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:4px;">${customTextRows}</div>
    </div>`
        : ""
    }
    ${
      hasSearchResults
        ? `
    <div id="test-search-content" class="test-tab-content" style="display:none;">
      <div style="font-size: 11px;color: #666;margin-bottom: 8px;">
        Cerca: <strong>${searchResultsData.query}</strong> (${
          searchResultsData.is_regex ? "REGEX" : "conté"
        }) - ${searchResultsData.count} resultats
      </div>
      <div class="test-body-search" id="test-body-search" style="font-size:13px;display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:4px;">${searchRows}</div>
    </div>`
        : ""
    }
  `;

  // Assigna events
  // Events DT: clic i menú per botons de paraula
  const dtContainer = document.getElementById("test-body-dt");
  if (dtContainer) {
    dtContainer.querySelectorAll(".word-btn").forEach((btn) => {
      const w = btn.getAttribute("data-word");
      btn.addEventListener("click", async () => {
        const currentTop = 0;
        await unifiedInsertOrMove(w, currentTop, {
          highlight: true,
          special: true,
          forceScroll: true,
          fromTest: true,
        });
      });
      btn.addEventListener("contextmenu", (e) => {
        e.preventDefault();
        showTestWordMenu(
          e,
          w,
          (wordsByPos[w] && wordsByPos[w].pos) || null,
          btn,
        );
      });
    });
  }
  const closeBtn = document.getElementById("close-test");
  if (closeBtn) closeBtn.onclick = () => hideTestOverlay();

  const addInside = document.getElementById("add-test-inside");
  if (addInside) addInside.onclick = addTestWordsPrompt;

  const addSynonymsBtn = document.getElementById("add-synonyms-test");
  if (addSynonymsBtn) addSynonymsBtn.onclick = addSynonymsTestPrompt;

  const modifySynonymsBtn = document.getElementById("modify-synonyms-test");
  if (modifySynonymsBtn) modifySynonymsBtn.onclick = addSynonymsTestPrompt;

  const closeCustomBtn = document.getElementById("close-custom-test");
  if (closeCustomBtn) {
    closeCustomBtn.onclick = (e) => {
      e.stopPropagation(); // Evita que es canviï a la pestanya custom
      customSynonymsData = null;
      // Després de tancar la pestanya custom, torna a 'common'
      refreshTestOverlayIfVisible("common");
    };
  }

  const addTextBtn = document.getElementById("add-text-test");
  if (addTextBtn) addTextBtn.onclick = openCustomTextTestModal;

  const modifyTextBtn = document.getElementById("modify-text-test");
  if (modifyTextBtn) modifyTextBtn.onclick = openCustomTextTestModal;

  const closeCustomTextBtn = document.getElementById("close-custom-text");
  if (closeCustomTextBtn) {
    closeCustomTextBtn.onclick = (e) => {
      e.stopPropagation(); // Evita que es canviï a la pestanya text
      customTextData = null;
      // Després de tancar la pestanya de text, torna a 'common'
      refreshTestOverlayIfVisible("common");
    };
  }

  const closeSearchBtn = document.getElementById("close-search-test");
  if (closeSearchBtn) {
    closeSearchBtn.onclick = (e) => {
      e.stopPropagation(); // Evita que es canviï a la pestanya search
      searchResultsData = null;
      // Després de tancar la pestanya de cerca, torna a 'common'
      refreshTestOverlayIfVisible("common");
    };
  }

  const reloadTestBtn = document.getElementById("reload-test-positions");
  if (reloadTestBtn) {
    reloadTestBtn.onclick = () => {
      saveTestState(); // Guarda l'estat actual (pestanya activa, scroll)
      loadTestOverlayData(); // Recarrega totes les dades
    };
  }

  initTestWordSelection();

  // Assigna events per saltar a posicions
  overlay.querySelectorAll("a.jump").forEach((a) => {
    a.addEventListener("click", async (e) => {
      e.preventDefault();
      const p = parseInt(a.getAttribute("data-pos"), 10);
      await ensureVisible(p, {
        highlight: true,
        special: true,
        force: p >= PAGE_SIZE,
        forceScroll: true,
      });
    });
  });

  // Assigna events de drag & drop per paraules del test amb posició
  overlay.querySelectorAll("[draggable='true']").forEach((draggableEl) => {
    draggableEl.addEventListener("dragstart", (e) => {
      const word = draggableEl.getAttribute("data-word");
      e.dataTransfer.setData("text/plain", word);
      e.dataTransfer.setData("application/x-test-word", word);
      draggableEl.style.opacity = "0.5";
    });

    draggableEl.addEventListener("dragend", (e) => {
      draggableEl.style.opacity = "1";
    });
  });

  // Assigna events per als botons de menú de paraules del test
  overlay.querySelectorAll(".test-word-menu-btn").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      const word = btn.getAttribute("data-word");
      const pos = parseInt(btn.getAttribute("data-pos"), 10);
      showTestWordMenu(e, word, pos, btn);
    });
  });
}

// Canvia entre pestanyes del test
window.switchTestTab = function (tabName) {
  // Guarda scroll actual de l'overlay per al tab actiu
  const overlay = document.getElementById("test-overlay");
  if (overlay) {
    const activeBtn = document.querySelector(
      "#test-overlay .btn-group button.active",
    );
    let currentTab = testState.activeTab;
    if (activeBtn) {
      const id = activeBtn.id;
      if (id === "tab-common") currentTab = "common";
      else if (id === "tab-ai") currentTab = "ai";
      else if (id === "tab-synonyms") currentTab = "synonyms";
      else if (id === "tab-dt") currentTab = "dt";
      else if (id === "tab-custom") currentTab = "custom";
      else if (id === "tab-text") currentTab = "text";
      else if (id === "tab-search") currentTab = "search";
    }
    testState.scrollPositions[currentTab] = overlay.scrollTop || 0;
  }

  // Actualitza botons de pestanya
  document
    .querySelectorAll('#test-overlay .btn-group button[id^="tab-"]')
    .forEach((btn) => {
      btn.classList.remove("active");
    });
  let targetBtn = document.getElementById(`tab-${tabName}`);
  if (!targetBtn) {
    // Si la pestanya no existeix (p.ex. s'ha tancat la custom), fem fallback a 'common'
    tabName = "common";
    targetBtn = document.getElementById("tab-common");
  }
  if (targetBtn) targetBtn.classList.add("active");

  // Mostra/amaga contingut (reset de display dels contenidors)
  document.querySelectorAll(".test-tab-content").forEach((content) => {
    content.style.display = "none";
  });
  const targetContent = document.getElementById(`test-${tabName}-content`);
  if (targetContent) targetContent.style.display = "block";
  // Restaura overlay.scrollTop per aquest tab
  if (overlay) {
    const saved = testState.scrollPositions[tabName];
    if (saved != null) overlay.scrollTop = saved;
  }

  // Actualitza l'estat
  testState.activeTab = tabName;

  // Actualitza botons d'acció (només per test comú)
  const addBtn = document.getElementById("add-test-inside");
  const selectBtn = document.getElementById("toggle-test-select");
  const deleteBtn = document.getElementById("delete-selected-test");

  const isCommonTab = tabName === "common";
  if (addBtn) addBtn.style.display = isCommonTab ? "inline-block" : "none";
  if (selectBtn)
    selectBtn.style.display = isCommonTab ? "inline-block" : "none";
  if (deleteBtn && tabName !== "common") deleteBtn.style.display = "none";

  // Reinicia la selecció si canviem de pestanya
  if (tabName !== "common") {
    testSelectMode = false;
    selectedTestWords.clear();
    updateTestSelectionUI();
  }
};

// Variables per mantenir l'estat del test durant recarregues
let testState = {
  activeTab: "common",
  // scrollPositions guarda el scroll vertical de l'overlay per cada tab
  scrollPositions: {},
  lastScroll: 0,
};
// Config restauració scroll
const TEST_SCROLL_RESTORE_MAX_ATTEMPTS = 30;
const TEST_SCROLL_RESTORE_INTERVAL = 50; // ms
function attemptOverlayScroll(desired, attempt = 1) {
  const overlay = document.getElementById("test-overlay");
  if (!overlay) return;

  // Força scroll abans de comprovar
  overlay.scrollTop = desired;

  // Comprova si hem arribat a la posició desitjada (amb marge de 5px)
  const current = overlay.scrollTop || 0;
  const done = Math.abs(current - desired) < 5;

  // Si està lluny del desitjat i encara tenim intents, continua
  if (!done && attempt < TEST_SCROLL_RESTORE_MAX_ATTEMPTS) {
    // Comprova que el contenidor tingui prou alçada per fer scroll
    const hasContent = overlay.scrollHeight > overlay.clientHeight;
    if (hasContent || attempt < 10) {
      setTimeout(
        () => attemptOverlayScroll(desired, attempt + 1),
        TEST_SCROLL_RESTORE_INTERVAL,
      );
    }
  }
}

// Guarda l'estat actual del test abans de recarregar
function saveTestState() {
  if (!testVisible) return;
  const overlay = document.getElementById("test-overlay");
  const activeTabBtn = document.querySelector(
    "#test-overlay .btn-group button.active",
  );
  if (activeTabBtn) {
    const tabId = activeTabBtn.id;
    if (tabId === "tab-common") testState.activeTab = "common";
    else if (tabId === "tab-ai") testState.activeTab = "ai";
    else if (tabId === "tab-synonyms") testState.activeTab = "synonyms";
    else if (tabId === "tab-dt") testState.activeTab = "dt";
    else if (tabId === "tab-custom") testState.activeTab = "custom";
    else if (tabId === "tab-text") testState.activeTab = "text";
  }
  if (overlay) {
    const current = overlay.scrollTop || 0;
    testState.scrollPositions[testState.activeTab] = current;
    testState.lastScroll = current;
  }
}

// Restaura l'estat del test després de recarregar
function restoreTestState(desiredOverride) {
  if (!testVisible || !testState.activeTab) return;
  const desired =
    desiredOverride ??
    testState.scrollPositions[testState.activeTab] ??
    testState.lastScroll ??
    0;
  switchTestTab(testState.activeTab); // això rehidrata contingut de la pestanya
  // Cadena d'intents: rAF + setTimeout + loop controlat
  requestAnimationFrame(() => {
    attemptOverlayScroll(desired, 1);
  });
}

function refreshTestOverlayIfVisible(desiredActiveTab) {
  if (!testVisible) return;
  saveTestState();
  const prevActive = testState.activeTab;
  const prevScroll = testState.scrollPositions[prevActive];
  const chosenActive = desiredActiveTab || prevActive;
  // Afegim classe de placeholder mentre carrega per evitar salt visual
  const overlay = document.getElementById("test-overlay");
  if (overlay) overlay.classList.add("loading-test-refresh");
  loadTestOverlayData().then(() => {
    if (overlay) overlay.classList.remove("loading-test-refresh");
    testState.activeTab = chosenActive;
    if (desiredActiveTab) {
      // Si forcem nova pestanya, inicialitza scroll a 0 si no hi ha estat guardat
      if (testState.scrollPositions[chosenActive] == null) {
        testState.scrollPositions[chosenActive] = 0;
      }
    } else if (prevScroll != null) {
      testState.scrollPositions[prevActive] = prevScroll;
    }
    // Petit delay per assegurar que el DOM està completament renderitzat
    setTimeout(() => {
      restoreTestState(
        desiredActiveTab ? testState.scrollPositions[chosenActive] : prevScroll,
      );
    }, 10);
  });
}

// Actualitza només els atributs d'una paraula dins dels tests visibles per evitar perdre l'scroll
function updateTestWordAttributes(word, newPos) {
  if (!testVisible) return;
  const overlay = document.getElementById("test-overlay");
  if (!overlay) return;

  const rows = Array.from(
    overlay.querySelectorAll(
      ".test-row[data-word], .test-row-ai[data-word], .test-row-synonyms[data-word], .test-row-search[data-word]",
    ),
  ).filter(
    (el) =>
      (el.getAttribute("data-word") || "").toLowerCase() === word.toLowerCase(),
  );

  if (!rows.length) {
    logMove("updateTestWordAttributes:rows=0", { word, newPos });
    return; // res a actualitzar
  }
  logMove("updateTestWordAttributes", { word, newPos, rows: rows.length });

  const makeFoundMarkup = (cls, w, pos) => {
    const color = colorPerPos(pos);
    return `
      <span style="color:${color}">${w}</span>
      <div style="display: flex; align-items: center; gap: 4px;">
        <a href="#" data-pos="${pos}" class="jump" title="Ves a posició"> (${pos})</a>
        <button class="test-word-menu-btn" data-word="${w}" data-pos="${pos}" title="Més opcions" style="border: none; background: transparent; cursor: pointer; padding: 2px 4px; font-size: 12px; color: #666;">⋮</button>
      </div>`;
  };

  const makeNotFoundMarkup = (w) => {
    return `<span class="text-muted">${w}</span> <span class="jump" style="font-size:11px">(no)</span>`;
  };

  const attachRowEvents = (rowEl) => {
    // jump link
    const a = rowEl.querySelector("a.jump");
    if (a) {
      a.addEventListener("click", async (e) => {
        e.preventDefault();
        const p = parseInt(a.getAttribute("data-pos"), 10);
        if (isNaN(p)) return;
        await ensureVisible(p, {
          highlight: true,
          special: true,
          force: p >= PAGE_SIZE,
          forceScroll: true,
        });
      });
    }
    // menu button
    const btn = rowEl.querySelector(".test-word-menu-btn");
    if (btn) {
      btn.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        const w = btn.getAttribute("data-word");
        const p = parseInt(btn.getAttribute("data-pos"), 10);
        showTestWordMenu(e, w, p, btn);
      });
    }
    // draggable
    if (rowEl.getAttribute("draggable") === "true") {
      rowEl.addEventListener("dragstart", (e) => {
        const w = rowEl.getAttribute("data-word");
        e.dataTransfer.setData("text/plain", w);
        e.dataTransfer.setData("application/x-test-word", w);
        rowEl.style.opacity = "0.5";
      });
      rowEl.addEventListener("dragend", () => {
        rowEl.style.opacity = "1";
      });
    }
  };

  rows.forEach((row) => {
    const clsTestRow = row.classList.contains("test-row")
      ? "test-row"
      : row.classList.contains("test-row-ai")
        ? "test-row-ai"
        : "test-row-synonyms";
    const w = row.getAttribute("data-word");
    if (newPos !== null && newPos !== undefined) {
      // estat TROBADA
      row.setAttribute("data-pos", String(newPos));
      row.setAttribute("draggable", "true");
      row.style.cursor = "grab";
      row.style.display = "flex";
      row.style.alignItems = "center";
      row.style.justifyContent = "space-between";
      row.innerHTML = makeFoundMarkup(clsTestRow, w, newPos);
    } else {
      // estat NO TROBADA
      row.removeAttribute("data-pos");
      row.removeAttribute("draggable");
      row.style.cursor = "default";
      row.style.display = "";
      row.style.alignItems = "";
      row.style.justifyContent = "";
      row.innerHTML = makeNotFoundMarkup(w);
    }
    attachRowEvents(row);
  });
}

// --- Selecció discreta per eliminar paraules test ---
let testSelectMode = false;
let selectedTestWords = new Set();
function initTestWordSelection() {
  const toggleBtn = document.getElementById("toggle-test-select");
  const delBtn = document.getElementById("delete-selected-test");
  const body = document.getElementById("test-body");
  if (!toggleBtn || !delBtn || !body) return;
  toggleBtn.onclick = () => {
    testSelectMode = !testSelectMode;
    selectedTestWords.clear();
    updateTestSelectionUI();
  };
  delBtn.onclick = async () => {
    if (!selectedTestWords.size) return;
    if (
      !confirm(
        `Eliminar ${selectedTestWords.size} paraules del test? s'esborraran per totes les paraules`,
      )
    )
      return;
    try {
      const res = await fetch(`${API_BASE}/test-words/delete`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({ words: Array.from(selectedTestWords) }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Error" }));
        alert(err.detail || "Error eliminant");
        return;
      }
      selectedTestWords.clear();
      testSelectMode = false;
      await loadTestOverlayData();
    } catch (e) {
      alert("Error de xarxa");
    }
  };
  body.querySelectorAll(".test-row").forEach((row) => {
    row.addEventListener("click", (e) => {
      if (!testSelectMode) return;
      const text = row.querySelector("span");
      if (!text) return;
      const raw = text.textContent.trim();
      const w = raw.split(/\s+/)[0].replace(/\.$/, "");
      if (selectedTestWords.has(w)) selectedTestWords.delete(w);
      else selectedTestWords.add(w);
      updateTestSelectionUI();
    });
  });
  updateTestSelectionUI();
}
function updateTestSelectionUI() {
  const body = document.getElementById("test-body");
  const toggleBtn = document.getElementById("toggle-test-select");
  const delBtn = document.getElementById("delete-selected-test");
  if (!body || !toggleBtn || !delBtn) return;
  if (!testSelectMode) {
    body.classList.remove("select-mode");
    delBtn.style.display = "none";
    toggleBtn.classList.remove("active");
    body
      .querySelectorAll(".test-row")
      .forEach((r) => r.classList.remove("selected"));
    return;
  }
  toggleBtn.classList.add("active");
  body.classList.add("select-mode");
  delBtn.style.display = selectedTestWords.size ? "inline-block" : "none";
  body.querySelectorAll(".test-row").forEach((r) => {
    const text = r.querySelector("span");
    if (!text) return;
    const w = text.textContent.trim().split(/\s+/)[0].replace(/\.$/, "");
    if (selectedTestWords.has(w)) r.classList.add("selected");
    else r.classList.remove("selected");
  });
}

function fetchFiles() {
  // Carrega llistat, validacions, preferits i dificultats en paral·lel
  Promise.all([
    fetch(RANKINGS_API, { headers: { ...authHeaders() } }).then((r) =>
      r.json(),
    ),
    fetch(VALIDATIONS_API, {
      headers: { ...authHeaders() },
    }).then((r) => r.json()),
    fetch(FAVORITES_API, {
      headers: { ...authHeaders() },
    }).then((r) => r.json()),
    fetch(DIFFICULTIES_API, {
      headers: { ...authHeaders() },
    }).then((r) => r.json()),
  ]).then(([flist, vals, favs, diffs]) => {
    files = flist;
    validations = vals || {};
    favorites = favs || {};
    difficulties = diffs || {};
    renderFileList();
  });
}

function renderFileList() {
  const ul = document.getElementById("file-list");
  ul.innerHTML = "";
  files.forEach((f) => {
    const validationStatus = validations[f] || "";
    const isValidated = !!validationStatus; // true if 'validated' or 'approved'
    const isFavorite = !!favorites[f];
    const wordName = f.replace(".json", "");
    const isInCalendar = calendarGames.some((g) => g.name === wordName);
    if (showOnlyPending && isValidated) return;
    if (showOnlyValidated && !isValidated) return;
    if (showOnlyFavorites && !isFavorite) return;
    if (!showInCalendar && isInCalendar) return; // Oculta assignats per defecte
    const li = document.createElement("li");
    li.className =
      "list-item" +
      (selected === f ? " selected" : "") +
      (isInCalendar ? " in-calendar" : "");
    // Nom del fitxer
    const span = document.createElement("span");
    span.style.flex = "1";
    const chkId = `val-${f}`;
    const starId = `fav-${f}`;
    const valState = getValidationState(f);
    const difficulty = difficulties[f] || "";
    const difficultyTag = difficulty ? getDifficultyTag(difficulty) : "";
    span.innerHTML = `
      <input type="checkbox" class="form-check-input me-2 validate-chk ${
        valState.className
      }" id="${chkId}" ${valState.checked ? "checked" : ""} title="${
        valState.title
      }" />
      <button class="star-btn ${
        isFavorite ? "favorite" : ""
      }" id="${starId}" title="Marca com a preferit" type="button">
        <i class="bi ${isFavorite ? "bi-star-fill" : "bi-star"}"></i>
      </button>
      <label for="${chkId}" class="form-check-label" style="cursor:pointer;">${f}</label>
      ${difficultyTag}
    `;
    li.appendChild(span);
    li.onclick = () => loadFile(f);
    // Checkbox toggle amb tres estats (aturar propagació per no carregar el fitxer automàticament)
    const chk = span.querySelector("input");
    chk.addEventListener("click", (e) => {
      e.stopPropagation();
      e.preventDefault(); // Prevenim el comportament per defecte per controlar manualment els estats

      const currentStatus = validations[f] || "";
      let newStatus = "";

      // Cicle dels tres estats: no validat -> validat -> aprovat -> no validat
      if (currentStatus === "") {
        newStatus = "validated";
      } else if (currentStatus === "validated") {
        newStatus = "approved";
      } else if (currentStatus === "approved") {
        newStatus = "";
      }

      fetch(`${VALIDATIONS_API}/${f}`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({ validated: newStatus }),
      })
        .then((r) => {
          if (!r.ok) throw new Error();
          if (newStatus) {
            validations[f] = newStatus;
          } else {
            delete validations[f];
          }
          // Re-renderitza la llista per actualitzar l'aparença
          renderFileList();
          // Si estem filtrant 'Pendents' i ara s'ha validat, pot desaparèixer
          if (showOnlyPending && newStatus) renderFileList();
          // Si estem filtrant 'Validats' i ara ha passat a no validat, pot desaparèixer
          if (showOnlyValidated && !newStatus) renderFileList();
        })
        .catch(() => {
          alert("Error desant validació");
          renderFileList(); // Reverteix en cas d'error
        });
    });

    // Star button toggle (aturar propagació per no carregar el fitxer automàticament)
    const starBtn = span.querySelector(".star-btn");
    starBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      const newVal = !favorites[f];
      fetch(`${FAVORITES_API}/${f}`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({ favorite: newVal }),
      })
        .then((r) => {
          if (!r.ok) throw new Error();
          if (newVal) {
            favorites[f] = true;
            starBtn.classList.add("favorite");
            starBtn.querySelector("i").className = "bi bi-star-fill";
          } else {
            delete favorites[f];
            starBtn.classList.remove("favorite");
            starBtn.querySelector("i").className = "bi bi-star";
          }
        })
        .catch(() => {
          alert("Error desant preferit");
        });
    });

    // Play button amb icona Bootstrap
    const play = document.createElement("button");
    play.className = "icon-btn";
    play.title = "Juga amb aquesta paraula";
    play.innerHTML = '<i class="bi bi-play-circle"></i>';
    play.onclick = (e) => {
      e.stopPropagation();
      // Extreu la paraula sense l'extensió .json i la codifica en Base64
      const word = f.replace(/\.json$/, "");
      const wordBase64 = btoa(encodeURIComponent(word));
      const gameUrl = `https://rebuscada.cat/?word=${wordBase64}`;
      window.open(gameUrl, "_blank", "noopener");
    };
    li.appendChild(play);

    // Delete button amb icona Bootstrap
    const del = document.createElement("button");
    del.className = "icon-btn";
    del.title = "Esborra";
    del.innerHTML = '<i class="bi bi-trash"></i>';
    del.onclick = (e) => {
      e.stopPropagation();
      showDeleteDialog(f);
    };
    li.appendChild(del);
    ul.appendChild(li);
  });
}

// ==================== FUNCIONS DE COMENTARIS ====================

// Carrega els comentaris d'un fitxer
async function loadComments(filename) {
  try {
    const res = await fetch(`${RANKINGS_API}/${filename}/comments`, {
      headers: { ...authHeaders() },
    });
    if (!res.ok) throw new Error();
    comments = await res.json();
  } catch (e) {
    comments = { global: "", words: {} };
  }
  updateCommentIndicators();
}

// Actualitza els indicadors de comentaris a la UI
function updateCommentIndicators() {
  updateGlobalCommentIcon();
  renderWordsArea(); // Re-renderitza per mostrar indicadors de paraules
}

// Actualitza la icona de comentari global
function updateGlobalCommentIcon() {
  const selector = document.getElementById("difficulty-selector");
  if (!selector) return;

  // Elimina icona existent si n'hi ha
  let icon = document.getElementById("global-comment-icon");
  if (icon) icon.remove();

  if (!selected) return;

  // Comprova si hi ha qualsevol comentari (global o de paraules)
  const hasGlobalComment = comments.global && comments.global.trim() !== "";
  const hasWordComments =
    comments.words && Object.keys(comments.words).length > 0;
  const hasAnyComment = hasGlobalComment || hasWordComments;

  // Crea la icona
  icon = document.createElement("button");
  icon.id = "global-comment-icon";
  icon.className = "icon-btn comment-icon-btn";

  // Actualitza el títol segons el tipus de comentaris
  if (hasGlobalComment && hasWordComments) {
    icon.title = "Comentari global i comentaris de paraules (clic per veure)";
  } else if (hasGlobalComment) {
    icon.title = "Comentari global (clic per editar)";
  } else if (hasWordComments) {
    icon.title = "Comentaris de paraules (clic per veure)";
  } else {
    icon.title = "Afegir comentari global";
  }

  icon.innerHTML = hasAnyComment
    ? '<i class="bi bi-chat-left-text-fill" style="color:#ff6800;"></i>'
    : '<i class="bi bi-chat-left"><span class="plus-sign">+</span></i>';

  icon.onclick = (e) => {
    e.preventDefault();
    e.stopPropagation();
    openCommentModal("global", null);
  };

  // Insereix després del selector
  selector.parentNode.insertBefore(icon, selector.nextSibling);
}

// Obre el modal de comentaris
function openCommentModal(type, word = null) {
  const isGlobal = type === "global";
  const currentComment = isGlobal
    ? comments.global
    : (comments.words && comments.words[word]) || "";
  const title = isGlobal ? "Comentari Global del Fitxer" : `Comentari: ${word}`;

  // Genera el resum de comentaris de paraules (només per al modal global)
  let wordCommentsSection = "";
  if (isGlobal && comments.words && Object.keys(comments.words).length > 0) {
    const wordCommentsHtml = Object.entries(comments.words)
      .map(([wordKey, commentText]) => {
        // Troba la posició de la paraula en wordsByPos
        let pos = null;
        for (const [p, w] of Object.entries(wordsByPos)) {
          if (w.word === wordKey) {
            pos = parseInt(p);
            break;
          }
        }

        const color = pos !== null ? colorPerPos(pos) : "#999";
        const posLabel = pos !== null ? `${pos}. ` : "";

        return `
          <div class="word-comment-item" data-word="${wordKey}">
            <span class="word-comment-label" style="color: ${color}; font-weight: 500; cursor: pointer;">
              ${posLabel}${wordKey}
            </span>
            <span class="word-comment-text" style="cursor: pointer;">
              ${commentText}
            </span>
          </div>
        `;
      })
      .join("");

    wordCommentsSection = `
      <div class="word-comments-summary">
        <h6 class="word-comments-title">Comentaris a les paraules</h6>
        <div class="word-comments-list">
          ${wordCommentsHtml}
        </div>
      </div>
    `;
  }

  const modalHtml = `
    <div class="modal fade" id="commentModal" tabindex="-1" aria-labelledby="commentModalLabel" aria-hidden="true">
      <div class="modal-dialog">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title" id="commentModalLabel">${title}</h5>
            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Tanca"></button>
          </div>
          <div class="modal-body">
            <textarea class="form-control" id="comment-textarea" rows="5" placeholder="Escriu el comentari aquí...">${currentComment}</textarea>
          </div>
          <div class="modal-footer">
            ${
              currentComment
                ? '<button type="button" class="btn btn-danger me-auto" id="delete-comment-btn">Esborra</button>'
                : ""
            }
            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel·la</button>
            <button type="button" class="btn btn-primary" id="save-comment-btn">Desa</button>
          </div>
          ${wordCommentsSection}
        </div>
      </div>
    </div>
  `;

  // Elimina modal anterior si existeix
  const oldModal = document.getElementById("commentModal");
  if (oldModal) oldModal.remove();

  // Afegeix modal al DOM
  document.body.insertAdjacentHTML("beforeend", modalHtml);

  const modalEl = document.getElementById("commentModal");
  const modal = new bootstrap.Modal(modalEl);

  // Event per desar
  document.getElementById("save-comment-btn").onclick = async () => {
    const textarea = document.getElementById("comment-textarea");
    const newComment = textarea.value.trim();
    await saveComment(isGlobal, word, newComment);
    modal.hide();
  };

  // Event per esborrar (si hi ha comentari)
  const deleteBtn = document.getElementById("delete-comment-btn");
  if (deleteBtn) {
    deleteBtn.onclick = async () => {
      if (!confirm("Segur que voleu esborrar aquest comentari?")) return;
      await deleteComment(isGlobal, word);
      modal.hide();
    };
  }

  // Event listeners per als comentaris de paraules (només en modal global)
  if (isGlobal) {
    const wordCommentItems = modalEl.querySelectorAll(".word-comment-item");
    wordCommentItems.forEach((item) => {
      item.addEventListener("click", (e) => {
        e.preventDefault();
        const wordKey = item.getAttribute("data-word");
        modal.hide(); // Tanca el modal actual
        // Espera a que el modal es tanqui abans d'obrir el nou
        setTimeout(() => {
          openCommentModal("word", wordKey);
        }, 300);
      });
    });
  }

  // Neteja el modal del DOM quan es tanca
  modalEl.addEventListener("hidden.bs.modal", () => {
    modalEl.remove();
  });

  modal.show();
}

// Desa un comentari (global o de paraula)
async function saveComment(isGlobal, word, comment) {
  if (!selected) return;

  try {
    let endpoint, body;
    if (isGlobal) {
      endpoint = `${RANKINGS_API}/${selected}/comments/global`;
      body = { comment };
    } else {
      endpoint = `${RANKINGS_API}/${selected}/comments/word`;
      body = { word, comment };
    }

    const res = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify(body),
    });

    if (!res.ok) throw new Error();

    // Actualitza l'estat local
    if (isGlobal) {
      comments.global = comment;
    } else {
      if (!comments.words) comments.words = {};
      if (comment) {
        comments.words[word] = comment;
      } else {
        delete comments.words[word];
      }
    }

    updateCommentIndicators();
  } catch (e) {
    alert("Error desant el comentari");
  }
}

// Esborra un comentari (global o de paraula)
async function deleteComment(isGlobal, word) {
  if (!selected) return;

  try {
    let endpoint;
    if (isGlobal) {
      endpoint = `${RANKINGS_API}/${selected}/comments/global`;
    } else {
      endpoint = `${RANKINGS_API}/${selected}/comments/word/${encodeURIComponent(
        word,
      )}`;
    }

    const res = await fetch(endpoint, {
      method: "DELETE",
      headers: { ...authHeaders() },
    });

    if (!res.ok) throw new Error();

    // Actualitza l'estat local
    if (isGlobal) {
      comments.global = "";
    } else {
      if (comments.words) {
        delete comments.words[word];
      }
    }

    updateCommentIndicators();
  } catch (e) {
    alert("Error esborrant el comentari");
  }
}

// ==================== FI FUNCIONS DE COMENTARIS ====================

function loadFile(filename) {
  selected = filename;
  wordsByPos = {};
  dirty = false;
  loading = true;
  lastMoveInfo = null;
  customSynonymsData = null; // Neteja dades de sinònims personalitzats quan canvia de fitxer
  customTextData = null; // Neteja dades de text personalitzat quan canvia de fitxer
  renderFileList();
  renderWordsArea();
  updateWordsTitle(); // Actualitza títol en carregar fitxer
  updateDifficultySelector(); // Actualitza selector de dificultat
  loadComments(filename); // Carrega comentaris del fitxer
  fetch(`${RANKINGS_API}/${filename}?offset=0&limit=${PAGE_SIZE}`, {
    headers: { ...authHeaders() },
  })
    .then((res) => res.json())
    .then((data) => {
      data.words.forEach((w) => (wordsByPos[w.pos] = w));
      total = data.total;
      loading = false;
      renderWordsArea();
      updateWordsTitle(); // Actualitza títol després de carregar dades
      updateDifficultySelector(); // Actualitza selector després de carregar dades
      refreshTestOverlayIfVisible();
    });
}

// Actualitza el títul amb la paraula en posició 0
function updateWordsTitle() {
  const titleEl = document.getElementById("words-title");
  if (!titleEl) return;

  if (!selected) {
    titleEl.textContent = "Paraules";
    return;
  }

  // Si tenim la paraula en posició 0 carregada, l'utilitzem
  if (wordsByPos[0] && wordsByPos[0].word) {
    titleEl.textContent = `Paraules - ${wordsByPos[0].word}`;
  } else {
    titleEl.textContent = "Paraules";
  }
}

// Actualitza el selector de dificultat
function updateDifficultySelector() {
  const selector = document.getElementById("difficulty-selector");
  if (!selector) return;

  if (!selected) {
    selector.style.display = "none";
    return;
  }

  selector.style.display = "block";
  const currentDifficulty = difficulties[selected] || "";
  selector.value = currentDifficulty;
}

function renderWordsArea() {
  const area = document.getElementById("words-area");
  // Guarda scroll actual (si existeix llista) per evitar saltar a l'esquerra en re-render
  let prevScrollLeft = 0;
  let prevScrollTop = 0;
  const existingList = area.querySelector(".word-list");
  if (existingList) {
    prevScrollLeft = existingList.scrollLeft;
    prevScrollTop = existingList.scrollTop;
  }
  area.innerHTML = "";
  updateWordsTitle(); // Actualitza títol sempre que es renderitza
  updateDifficultySelector(); // Actualitza selector sempre que es renderitza
  if (!selected) {
    area.innerHTML =
      '<div style="color:#888">Selecciona un fitxer per veure les paraules.</div>';
    return;
  }
  if (loading) {
    area.innerHTML =
      '<div style="text-align:center;padding:32px"><span>Carregant...</span></div>';
    return;
  }
  const wordList = document.createElement("div");
  wordList.className = "word-list";
  const positions = Object.keys(wordsByPos)
    .map(Number)
    .sort((a, b) => a - b);
  let contiguousEnd = 0; // primer index no carregat començant per 0
  while (wordsByPos[contiguousEnd]) contiguousEnd++;

  const createWordItem = (pos) => {
    const w = wordsByPos[pos];
    const item = document.createElement("div");
    const isFirst = pos === 0;
    const draggableAllowed = !isFirst && pos < contiguousEnd;
    item.className = "word-item" + (draggableAllowed ? " draggable" : "");
    const txt = document.createElement("span");
    txt.className = "word-text";
    txt.textContent = `${pos}. ${w.word}`;
    txt.title = `${pos}. ${w.word}`;
    txt.style.color = colorPerPos(pos);
    item.appendChild(txt);

    if (!isFirst) {
      const menuBtn = document.createElement("button");
      menuBtn.className = "icon-btn";

      // Afegeix indicador de comentari si la paraula té comentari
      const hasWordComment = comments.words && comments.words[w.word];
      let menuBtnHtml = "";

      if (hasWordComment) {
        menuBtnHtml =
          '<span class="word-comment-indicator" title="Aquesta paraula té comentari"><i class="bi bi-chat-left-text-fill" style="color: #818181;font-size:10px;"></i></span> ';
      }

      menuBtnHtml += '<i class="bi bi-three-dots-vertical"></i>';
      menuBtn.innerHTML = menuBtnHtml;

      menuBtn.onclick = (e) => {
        e.preventDefault();
        e.stopPropagation();
        showMenu(e, pos);
      };
      menuBtn.onmousedown = (e) => e.stopPropagation();
      item.appendChild(menuBtn);
    }
    if (draggableAllowed) {
      item.draggable = true;
      item.addEventListener("dragstart", (e) => onDragStart(e, pos, item));
      item.addEventListener("dragend", (e) => onDragEnd(e, item));
      item.addEventListener("dragover", (e) => onDragOver(e, pos, item));
      item.addEventListener("drop", (e) => onDrop(e, pos, item));
    } else if (isFirst) {
      item.style.height = "38px";
      item.style.minHeight = "38px";
      item.style.display = "flex";
    }
    return item;
  };
  const appendGapButton = (start, endKnown) => {
    const item = document.createElement("div");
    item.className = "word-item";
    const btn = document.createElement("button");
    btn.className = "btn btn-outline-secondary btn-sm w-100";
    btn.textContent =
      endKnown !== null ? `més [${start}-${endKnown}]` : `més [${start}...]`;
    btn.onclick = (e) => {
      e.preventDefault();
      loadMoreGap(start, endKnown);
    };
    item.appendChild(btn);
    wordList.appendChild(item);
  };
  let cursor = 0;
  while (cursor < total) {
    if (wordsByPos[cursor]) {
      wordList.appendChild(createWordItem(cursor));
      cursor++;
      continue;
    }
    let nextLoaded = null;
    for (let p of positions) {
      if (p > cursor) {
        nextLoaded = p;
        break;
      }
    }
    const endKnown = nextLoaded !== null ? nextLoaded - 1 : null;
    appendGapButton(cursor, endKnown);
    if (nextLoaded === null) break;
    cursor = nextLoaded;
  }
  area.appendChild(wordList);
  // Restaura scroll
  wordList.scrollLeft = prevScrollLeft;
  wordList.scrollTop = prevScrollTop;
  // Indicador d'últim moviment si la posició no està carregada
  if (lastMoveInfo && selected && !wordsByPos[lastMoveInfo.toPos]) {
    const indicator = document.createElement("div");
    indicator.className = "move-indicator";
    indicator.innerHTML = `
      <div class="alert alert-info p-2 mt-2 mb-0" style="cursor:pointer;">
        Paraula moguda a posició ${lastMoveInfo.toPos}. Fes clic per mostrar-la.
      </div>`;
    indicator.onclick = () =>
      ensureVisible(lastMoveInfo.toPos, { highlight: true, special: true });
    area.appendChild(indicator);
  }
  // Botó de desar
  // ja no cal botó; auto-save
}

// Drag & drop
let dragIdx = null;
function onDragStart(e, pos, item) {
  dragIdx = pos;
  e.dataTransfer.effectAllowed = "move";
  try {
    const w = wordsByPos[pos] ? wordsByPos[pos].word : undefined;
    logMove("dragstart", { fromPos: pos, word: w });
  } catch (_) {}
  setTimeout(() => item.classList.add("dragging"), 0);
}
function onDragEnd(e, item) {
  dragIdx = null;
  item.classList.remove("dragging");
  // Eliminar qualsevol drag-over restant
  document
    .querySelectorAll(".word-item.drag-over")
    .forEach((el) => el.classList.remove("drag-over"));
}
function onDragOver(e, pos, item) {
  e.preventDefault();

  // Permet drop de paraules del test o drag & drop normal
  const testWord = e.dataTransfer.getData("application/x-test-word");
  if (
    testWord ||
    (dragIdx !== null && dragIdx !== 0 && pos !== 0 && dragIdx !== pos)
  ) {
    document
      .querySelectorAll(".word-item.drag-over")
      .forEach((el) => el.classList.remove("drag-over"));
    item.classList.add("drag-over");
  }
}
function onDrop(e, pos, item) {
  e.preventDefault();

  // Comprova si és una paraula del test
  const testWord = e.dataTransfer.getData("application/x-test-word");
  if (testWord) {
    // És una paraula arrossegada des d'un test
    logMove("drop-from-test", { word: testWord, toPos: pos });
    insertWordFromTest(testWord, pos);
    return;
  }

  // Drag & drop normal dins de la llista
  if (dragIdx === null || dragIdx === 0 || pos === 0 || dragIdx === pos) return;

  const fromIndex = dragIdx;
  const toIndex = pos;
  dragIdx = null;

  try {
    const w = wordsByPos[fromIndex] ? wordsByPos[fromIndex].word : undefined;
    logMove("drop-in-list", { word: w, fromPos: fromIndex, toPos: toIndex });
  } catch (_) {}

  // Paraula a moure (pot no estar carregada si s'ha mogut prèviament), obtenim del bloc si existeix
  const wObj = wordsByPos[fromIndex];
  if (!wObj) {
    // Fallback: recarrega bloc inicial i surt
    logMove("drop-miss-word", {
      fromPos: fromIndex,
      toPos: toIndex,
      note: "reloadInitialBlock fallback",
    });
    reloadInitialBlock();
    return;
  }
  // L'estat del test es guarda dins unifiedInsertOrMove
  unifiedInsertOrMove(wObj.word, toIndex, {
    highlight: true,
    fromPos: fromIndex,
  });
}

// Insereix una paraula del test a una posició específica
async function insertWordFromTest(word, targetPos) {
  if (!word || targetPos === 0) return;
  logMove("insertWordFromTest", { word, toPos: targetPos });
  // No cal saveTestState aquí, ja es fa dins unifiedInsertOrMove
  await unifiedInsertOrMove(word, targetPos, {
    highlight: true,
    fromTest: true,
  });
}

// Funció unificada per inserir o moure una paraula al rànquing
async function unifiedInsertOrMove(word, toPos, options = {}) {
  if (!selected) return;
  const { highlight = false, fromPos = null, fromTest = false } = options;

  // Guarda l'estat del test només si ve del test (per preservar scroll)
  if (fromTest && testVisible) {
    saveTestState();
  }

  try {
    logMove("insert-or-move:request", {
      file: selected,
      word,
      fromPos,
      toPos,
      fromTest,
    });
    const res = await fetch(`${RANKINGS_API}/${selected}/insert-or-move`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ word, to_pos: toPos }),
    });
    if (!res.ok) throw new Error("Error inserint/movent");
    const data = await res.json();
    logMove("insert-or-move:response", {
      action: data.action,
      word: data.word,
      to: data.to,
      total: data.total,
    });
    total = data.total;
    // Recarrega bloc inicial per mantenir coherència (no marquem dirty: backend ja és font de veritat)
    const changedPos = fromPos != null ? Math.min(fromPos, data.to) : data.to;
    await reloadInitialBlock();
    // Recarrega les posicions carregades afectades pel desplaçament
    let startRefresh = changedPos;
    if (startRefresh < PAGE_SIZE) startRefresh = PAGE_SIZE; // evita repetir el bloc inicial
    await refreshLoadedAfter(startRefresh);
    if (highlight) highlightMovedWord(data.to, data.action === "inserted");
    // Actualitza només els atributs de la paraula dins dels tests (evitem recarregar i perdre l'scroll)
    updateTestWordAttributes(word, data.to);
  } catch (e) {
    console.error("unifiedInsertOrMove error", e);
    alert("No s'ha pogut actualitzar el rànquing");
  }
}

function highlightMovedWord(pos, special) {
  setTimeout(() => {
    const wordItems = document.querySelectorAll(".word-item");
    wordItems.forEach((el) => {
      if (
        el.firstChild &&
        el.firstChild.textContent &&
        el.firstChild.textContent.startsWith(`${pos}.`)
      ) {
        tempHighlightElement(el, 1500, special ? "moved-special" : "moved");
        el.scrollIntoView({ behavior: "smooth", block: "center" });
      }
    });
  }, 0);
}

// Recarrega (refetch) els trams contigus ja carregats amb posició >= startPos
async function refreshLoadedAfter(startPos) {
  logMove("refreshLoadedAfter:start", { file: selected, startPos });
  // Detecta rangs contigus de posicions carregades >= startPos (excloent les < PAGE_SIZE perquè ja s'han refrescat)
  const loaded = Object.keys(wordsByPos)
    .map(Number)
    .filter((p) => p >= startPos)
    .sort((a, b) => a - b);
  if (!loaded.length) return;
  const ranges = [];
  let rangeStart = loaded[0];
  let prev = loaded[0];
  for (let i = 1; i < loaded.length; i++) {
    const p = loaded[i];
    if (p === prev + 1) {
      prev = p;
      continue;
    }
    ranges.push([rangeStart, prev]);
    rangeStart = p;
    prev = p;
  }
  ranges.push([rangeStart, prev]);
  for (const [a, b] of ranges) {
    const len = b - a + 1;
    logMove("refreshLoadedAfter:range", { from: a, to: b, len });
    try {
      const res = await fetch(
        `${RANKINGS_API}/${selected}?offset=${a}&limit=${len}`,
        { headers: { ...authHeaders() } },
      );
      const data = await res.json();
      if (data.words) data.words.forEach((w) => (wordsByPos[w.pos] = w));
    } catch (_) {
      // ignore errors individuals
    }
  }
  logMove("refreshLoadedAfter:done", { ranges: ranges.length });
  renderWordsArea();
}

// Funció helper per posicionar menús flotants dins de la pantalla
function positionMenu(menu, x, y) {
  // Posició inicial (fora de pantalla per mesurar)
  menu.style.left = "-9999px";
  menu.style.top = "-9999px";
  menu.style.visibility = "hidden";
  menu.style.display = "block";

  // Obté dimensions del menú
  const rect = menu.getBoundingClientRect();
  const menuWidth = rect.width;
  const menuHeight = rect.height;
  const viewportWidth = window.innerWidth;
  const viewportHeight = window.innerHeight;

  let finalX = x;
  let finalY = y;

  // Comprova si surt per la dreta
  if (x + menuWidth > viewportWidth) {
    finalX = Math.max(0, x - menuWidth);
  }

  // Comprova si surt per l'esquerra
  if (finalX < 0) {
    finalX = 0;
  }

  // Comprova si surt per baix
  if (y + menuHeight > viewportHeight) {
    finalY = Math.max(0, y - menuHeight);
  }

  // Comprova si surt per dalt
  if (finalY < 0) {
    finalY = 0;
  }

  // Aplica posició final
  menu.style.left = finalX + "px";
  menu.style.top = finalY + "px";
  menu.style.visibility = "visible";
}

function bindSubmenuEvents(menu) {
  menu.querySelectorAll(".menu-item.has-submenu").forEach((item) => {
    item.addEventListener("mouseenter", () => {
      const submenu = item.querySelector(".submenu");
      if (!submenu) return;

      // Reset styles
      submenu.style.left = "100%";
      submenu.style.right = "auto";
      submenu.style.top = "-5px";

      const rect = submenu.getBoundingClientRect();
      const viewportWidth = window.innerWidth;
      const viewportHeight = window.innerHeight;

      // Check horizontal overflow
      if (rect.right > viewportWidth) {
        submenu.style.left = "auto";
        submenu.style.right = "100%";
      }

      // Check vertical overflow
      if (rect.bottom > viewportHeight) {
        const overflowY = rect.bottom - viewportHeight;
        submenu.style.top = `-${overflowY + 10}px`;
      }
    });
  });
}

// Menú contextual per paraules del test
function showTestWordMenu(e, word, pos, btn) {
  e.preventDefault();
  e.stopPropagation();
  closeMenu();

  menuAnchor = { x: e.clientX, y: e.clientY };
  const menuRoot = document.getElementById("menu-root");
  const menu = document.createElement("div");
  menu.className = "menu";

  // Helper per generar items de moviment ràpid
  const genQuickMoves = (targets) => {
    return targets
      .filter((t) => total > t)
      .map(
        (t) =>
          `<div class="menu-item quick-move" data-target="${t}">${t}</div>`,
      )
      .join("");
  };

  let html = `
    <div class="menu-item has-submenu">
      Mou
      <div class="submenu">
        <div class="menu-item" id="test-move-to-pos">Mou a la posició...</div>
        
        <div class="menu-item has-submenu">
          Mou <300
          <div class="submenu">
            ${genQuickMoves([10, 50, 100, 200, 300])}
          </div>
        </div>
        
        <div class="menu-item has-submenu">
          Mou <1000
          <div class="submenu">
            ${genQuickMoves([400, 500, 600, 800, 1000])}
          </div>
        </div>
        
        <div class="menu-item has-submenu">
          Mou lluny
          <div class="submenu">
            ${genQuickMoves([2000, 3000, 5000, 8000])}
            <div class="menu-item" id="test-move-end">Al final</div>
          </div>
        </div>
      </div>
    </div>
    <div class="menu-item" id="test-open-dict">Cerca al diccionari</div>
  `;

  menu.innerHTML = html;
  menuRoot.appendChild(menu);

  // Posiciona el menú dins de la pantalla
  positionMenu(menu, menuAnchor.x, menuAnchor.y);

  // Bind submenu events for overflow handling
  bindSubmenuEvents(menu);

  // Event per moure a una nova posició (obre prompt)
  document.getElementById("test-move-to-pos").onclick = async (ev) => {
    ev.preventDefault();
    ev.stopPropagation();
    closeMenu();

    const newPosStr = prompt(
      `Mou "${word}" a quina posició? (actual: ${pos})`,
      "",
    );
    if (newPosStr === null) return;
    const newPos = parseInt(newPosStr, 10);
    if (isNaN(newPos) || newPos < 0) {
      alert("Posició no vàlida");
      return;
    }

    if (!selected) return;
    try {
      logMove("test-menu:move-to-pos", {
        file: selected,
        word,
        fromPos: pos,
        toPos: newPos,
      });
      const res = await fetch(`${RANKINGS_API}/${selected}/insert-or-move`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({ word, to_pos: newPos }),
      });
      if (!res.ok) throw new Error("Error movent paraula");
      const data = await res.json();
      await reloadInitialBlock();
      // Refresca qualsevol bloc carregat afectat pel canvi (incloent > PAGE_SIZE)
      try {
        let startRefresh = Math.min(pos, data.to);
        if (startRefresh < PAGE_SIZE) startRefresh = PAGE_SIZE;
        await refreshLoadedAfter(startRefresh);
      } catch (_) {}
      updateTestWordAttributes(word, data.to);
    } catch (e) {
      alert("No s'ha pogut moure la paraula");
    }
  };

  // Event per moure al final
  document.getElementById("test-move-end").onclick = async (ev) => {
    ev.preventDefault();
    ev.stopPropagation();
    closeMenu();
    if (!selected) return;
    try {
      logMove("test-menu:move-to-end", {
        file: selected,
        word,
        fromPos: pos,
        toPos: total,
      });
      const res = await fetch(`${RANKINGS_API}/${selected}/insert-or-move`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({ word, to_pos: total }),
      });
      if (!res.ok) throw new Error("Error movent al final");
      const data = await res.json();
      await reloadInitialBlock();
      try {
        let startRefresh = Math.min(pos, data.to);
        if (startRefresh < PAGE_SIZE) startRefresh = PAGE_SIZE;
        await refreshLoadedAfter(startRefresh);
      } catch (_) {}
      updateTestWordAttributes(word, data.to);
    } catch (e) {
      alert("No s'ha pogut moure la paraula al final");
    }
  };

  // Event per cercar al diccionari
  document.getElementById("test-open-dict").onclick = (ev) => {
    ev.preventDefault();
    ev.stopPropagation();
    closeMenu();
    const url = DICT_URL_TEMPLATE.replace(
      "[PARAULA]",
      encodeURIComponent(word),
    );
    window.open(url, "_blank", "noopener");
  };

  // Enllaça moviments ràpids (igual que al menú principal però adaptat al test)
  menu.querySelectorAll(".quick-move").forEach((el) => {
    el.addEventListener("click", async (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      const targetRaw = parseInt(el.getAttribute("data-target"), 10);
      const target = Math.min(total - 1, targetRaw);

      closeMenu();

      if (!selected) return;
      try {
        logMove("test-menu:quick-move", {
          file: selected,
          word,
          fromPos: pos,
          toPos: target,
        });
        const res = await fetch(`${RANKINGS_API}/${selected}/insert-or-move`, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...authHeaders() },
          body: JSON.stringify({ word, to_pos: target }),
        });
        if (!res.ok) throw new Error("Error movent paraula");
        const data = await res.json();
        await reloadInitialBlock();
        try {
          let startRefresh = Math.min(pos, data.to);
          if (startRefresh < PAGE_SIZE) startRefresh = PAGE_SIZE;
          await refreshLoadedAfter(startRefresh);
        } catch (_) {}
        updateTestWordAttributes(word, data.to);
      } catch (e) {
        alert("No s'ha pogut moure la paraula");
      }
    });
  });

  // Tanca el menú si es clica fora
  const closeHandler = (ev) => {
    if (!menu.contains(ev.target)) {
      closeMenu();
      document.removeEventListener("click", closeHandler);
    }
  };
  setTimeout(() => {
    document.addEventListener("click", closeHandler);
  }, 10);
}

// Menú contextual
function showMenu(e, pos) {
  e.preventDefault();
  closeMenu();
  menuIdx = pos; // posició absoluta
  menuAnchor = { x: e.clientX, y: e.clientY };
  const menuRoot = document.getElementById("menu-root");
  const menu = document.createElement("div");
  menu.className = "menu";

  const w = wordsByPos[pos];
  const hasComment = w && comments.words && comments.words[w.word];

  // Helper per generar items de moviment ràpid
  const genQuickMoves = (targets) => {
    return targets
      .filter((t) => total > t)
      .map(
        (t) =>
          `<div class="menu-item quick-move" data-target="${t}">${t}</div>`,
      )
      .join("");
  };

  let html = `
    <div class="menu-item" id="comment-word">${
      hasComment ? "Comentar-ho amb el company" : "Afegir comentari"
    }</div>
    
    <div class="menu-item has-submenu">
      Mou
      <div class="submenu">
        <div class="menu-item" id="move-to">Mou a la posició…</div>
        
        <div class="menu-item has-submenu">
          Mou <300
          <div class="submenu">
            ${genQuickMoves([10, 50, 100, 200, 300])}
          </div>
        </div>
        
        <div class="menu-item has-submenu">
          Mou <1000
          <div class="submenu">
            ${genQuickMoves([400, 500, 600, 800, 1000])}
          </div>
        </div>
        
        <div class="menu-item has-submenu">
          Mou lluny
          <div class="submenu">
            ${genQuickMoves([2000, 3000, 5000, 8000])}
            <div class="menu-item" id="move-end">Al final</div>
          </div>
        </div>
      </div>
    </div>

    <div class="menu-item" id="open-dict">Cerca al diccionari</div>
    <div class="menu-item" id="delete-word" style="color:#c62828;">Elimina paraula…</div>
  `;

  menu.innerHTML = html;
  menuRoot.appendChild(menu);

  // Posiciona el menú dins de la pantalla
  positionMenu(menu, menuAnchor.x, menuAnchor.y);

  // Bind submenu events for overflow handling
  bindSubmenuEvents(menu);

  document.getElementById("comment-word").onclick = (ev) => {
    ev.preventDefault();
    ev.stopPropagation();
    if (menuIdx != null) {
      const wObj = wordsByPos[menuIdx];
      if (wObj && wObj.word) {
        openCommentModal("word", wObj.word);
      }
    }
    closeMenu();
  };

  document.getElementById("move-to").onclick = (ev) => {
    ev.preventDefault();
    ev.stopPropagation();
    handleMoveToPrompt();
    closeMenu();
  };
  document.getElementById("move-end").onclick = (ev) => {
    ev.preventDefault();
    ev.stopPropagation();
    handleSendToEndMenu();
    closeMenu();
  };
  document.getElementById("delete-word").onclick = (ev) => {
    ev.preventDefault();
    ev.stopPropagation();
    handleDeleteWord();
    closeMenu();
  };
  const openDict = document.getElementById("open-dict");
  if (openDict) {
    openDict.onclick = (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      if (menuIdx != null) {
        const wObj = wordsByPos[menuIdx];
        if (wObj && wObj.word) {
          const url = DICT_URL_TEMPLATE.replace(
            "[PARAULA]",
            encodeURIComponent(wObj.word),
          );
          window.open(url, "_blank", "noopener");
        }
      }
      closeMenu();
    };
  }
  // Enllaça moviments ràpids
  menu.querySelectorAll(".quick-move").forEach((el) => {
    el.addEventListener("click", async (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      const targetRaw = parseInt(el.getAttribute("data-target"), 10);
      const target = Math.min(total - 1, targetRaw);
      if (menuIdx === null || target === menuIdx) {
        closeMenu();
        return;
      }
      logMove("quick-move", {
        file: selected,
        fromPos: menuIdx,
        toPos: target,
      });
      const fromPos = menuIdx;
      const data = await moveAbsolute(fromPos, target);
      closeMenu();
      await reloadInitialBlock();
      try {
        let startRefresh = Math.min(fromPos, target);
        if (startRefresh < PAGE_SIZE) startRefresh = PAGE_SIZE;
        await refreshLoadedAfter(startRefresh);
      } catch (_) {}
      await ensureVisible(target, {
        highlight: true,
        special: true,
        force: target >= PAGE_SIZE,
      });
      if (data && data.word !== undefined && data.to !== undefined) {
        updateTestWordAttributes(data.word, data.to);
      }
    });
  });
  // Només tanca el menú si es fa clic fora
  setTimeout(() => {
    // Abans era 'mousedown' i es tancava el menú abans que es disparessin els onClick dels ítems.
    // Amb 'click' el listener del document s'executa DESPRÉS del click sobre l'element de menú,
    // permetent que les accions (moure / enviar al final) funcionin.
    document.addEventListener("click", closeMenu, { once: true });
  }, 0);
}
function closeMenu() {
  const menuRoot = document.getElementById("menu-root");
  menuRoot.innerHTML = "";
  menuIdx = null;
  menuAnchor = null;
}
async function handleMoveToPrompt() {
  if (menuIdx === null) return closeMenu();
  const absoluteFrom = menuIdx;
  let posStr = prompt(
    `A quina posició vols moure aquesta paraula? (0 - ${total - 1})`,
    "",
  );
  if (posStr === null) return closeMenu();
  let target = parseInt(posStr, 10);
  if (isNaN(target) || target < 0) target = 0;
  if (target >= total) target = total - 1;
  if (target === absoluteFrom) return closeMenu();
  const data = await moveAbsolute(absoluteFrom, target);
  closeMenu();
  await reloadInitialBlock();
  try {
    let startRefresh = Math.min(absoluteFrom, target);
    if (startRefresh < PAGE_SIZE) startRefresh = PAGE_SIZE;
    await refreshLoadedAfter(startRefresh);
  } catch (_) {}
  await ensureVisible(target, {
    highlight: true,
    special: true,
    force: target >= PAGE_SIZE,
  });
  if (data && data.word !== undefined && data.to !== undefined) {
    updateTestWordAttributes(data.word, data.to);
  }
}
async function handleSendToEndMenu() {
  if (menuIdx === null) return closeMenu();
  const absoluteFrom = menuIdx;
  const target = total - 1;
  if (target === absoluteFrom) return closeMenu();
  const data = await moveAbsolute(absoluteFrom, target);
  closeMenu();
  await reloadInitialBlock();
  try {
    let startRefresh = Math.min(absoluteFrom, target);
    if (startRefresh < PAGE_SIZE) startRefresh = PAGE_SIZE;
    await refreshLoadedAfter(startRefresh);
  } catch (_) {}
  await ensureVisible(target, {
    highlight: true,
    special: true,
    force: target >= PAGE_SIZE,
  });
  if (data && data.word !== undefined && data.to !== undefined) {
    updateTestWordAttributes(data.word, data.to);
  }
}

async function handleDeleteWord() {
  if (menuIdx === null) return;
  const pos = menuIdx;
  if (!selected) return;
  const wordObj = wordsByPos[pos];
  const wordLabel = wordObj ? wordObj.word : `posició ${pos}`;
  const confirmMsg = `Segur que voleu eliminar la paraula «${wordLabel}» de la llista? En cercar aquesta paraula, aquell dia sortirà com a no present al diccionari.`;
  if (!confirm(confirmMsg)) return;
  try {
    const res = await fetch(`${RANKINGS_API}/${selected}/word/${pos}`, {
      method: "DELETE",
      headers: { ...authHeaders() },
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Error eliminant paraula");
    }
    const data = await res.json();
    // Actualitza estat local: elimina la paraula i reindexa si cal el bloc inicial carregat
    // Eliminem totes les posicions carregades >= pos fins trobar un forat i refetch fragment inicial
    // Estratègia simple: recarregar bloc inicial i mantenir la resta (es podria optimitzar)
    await reloadInitialBlock();
    // Refresca qualsevol bloc carregat a partir de la posició esborrada (evitant el bloc inicial)
    try {
      let startRefresh = pos;
      if (startRefresh < PAGE_SIZE) startRefresh = PAGE_SIZE;
      await refreshLoadedAfter(startRefresh);
    } catch (_) {}
    total = data.total;
    // Si la paraula eliminada era part de lastMoveInfo, neteja
    if (lastMoveInfo && lastMoveInfo.toPos === pos) lastMoveInfo = null;
    renderWordsArea();
    // Una eliminació no necessita desat addicional (ja està persistit), però marquem estat
    showAutoSaveDone();
    // Actualitza els tests només per aquesta paraula (ara ja no està trobada)
    if (wordObj && wordObj.word) {
      updateTestWordAttributes(wordObj.word, null);
    }
  } catch (e) {
    alert(e.message);
  }
}

async function moveAbsolute(fromPos, toPos) {
  logMove("moveAbsolute:request", { file: selected, fromPos, toPos });
  const res = await fetch(`${RANKINGS_API}/${selected}/move`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ from_pos: fromPos, to_pos: toPos }),
  });
  let data = null;
  try {
    data = await res.json();
    if (data && data.word !== undefined && data.to !== undefined) {
      lastMoveInfo = { word: data.word, toPos: data.to };
    }
    logMove("moveAbsolute:response", {
      word: data && data.word,
      to: data && data.to,
      total: data && data.total,
    });
  } catch (_) {
    // ignore JSON parse errors
  }
  // Elimina la paraula de la posició antiga si la tenim carregada per evitar duplicats visuals
  if (fromPos !== toPos && wordsByPos[fromPos]) {
    delete wordsByPos[fromPos];
  }
  // El moviment ja s'ha desat al backend; no cal marcar dirty.
  return data;
}

async function reloadInitialBlock() {
  logMove("reloadInitialBlock", {
    file: selected,
    range: `0..${PAGE_SIZE - 1}`,
  });
  const res = await fetch(
    `${RANKINGS_API}/${selected}?offset=0&limit=${PAGE_SIZE}`,
    {
      headers: { ...authHeaders() },
    },
  );
  const data = await res.json();
  // REFRESH PARCIAL: Només actualitzem el primer bloc (0..PAGE_SIZE-1)
  // Abans eliminàvem TOT el tram contigu començant per 0 fins trobar un forat, cosa que
  // podia incloure posicions > PAGE_SIZE si l'usuari havia carregat més blocs (ex: 0..599).
  // Això feia desaparèixer les paraules >300 després de moure'n una i forçar reload.
  // Ara només eliminem i substituïm les posicions < PAGE_SIZE i preservem la resta.
  Object.keys(wordsByPos).forEach((k) => {
    const p = parseInt(k, 10);
    if (p < PAGE_SIZE) delete wordsByPos[p];
  });
  data.words.forEach((w) => (wordsByPos[w.pos] = w));
  total = data.total;
  renderWordsArea();
  updateWordsTitle(); // Actualitza títol després de recarregar
}

// options: {highlight, force, special, forceScroll}
async function ensureVisible(pos, options = {}) {
  const {
    highlight = false,
    force = false,
    special = false,
    forceScroll = false,
  } = options;

  // Comprova si el moviment automàtic està desactivat, però permet forceScroll
  if (!settings.autoScroll && !forceScroll) {
    return; // No fa res si el moviment automàtic està desactivat i no és un forceScroll
  }

  if (force && wordsByPos[pos]) delete wordsByPos[pos];
  const applyHighlight = () => {
    if (!highlight) return;
    setTimeout(() => {
      const wordItems = document.querySelectorAll(".word-item");
      wordItems.forEach((el) => {
        if (
          el.firstChild &&
          el.firstChild.textContent &&
          el.firstChild.textContent.startsWith(`${pos}.`)
        ) {
          tempHighlightElement(el, 1500, special ? "moved-special" : "moved");
          el.scrollIntoView({ behavior: "smooth", block: "center" });
        }
      });
    }, 0);
  };
  if (wordsByPos[pos]) {
    applyHighlight();
    return;
  }
  const res = await fetch(`${RANKINGS_API}/${selected}?offset=${pos}&limit=1`, {
    headers: { ...authHeaders() },
  });
  const data = await res.json();
  if (data.words && data.words[0])
    wordsByPos[data.words[0].pos] = data.words[0];
  renderWordsArea();
  if (highlight && !force)
    await ensureVisible(pos, { highlight: true, special, forceScroll });
  else applyHighlight();
}

// Crear fitxer
function createFile() {
  const paraula = prompt(
    "Paraula per generar rànquing (pot tardar una estona):",
    "",
  );
  if (paraula === null) return; // cancel·lat

  // Desactivat el server per falta de ram
  alert("Uoops... ara mateix no és possible parla amb l'Aniol");
  return;

  const cleaned = paraula.trim().toLowerCase();
  if (!cleaned) return;
  // Crida endpoint de generació
  // Fem servir endpoint alternatiu per evitar confusions amb path params
  fetch(GENERATE_ENDPOINT, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ word: cleaned }),
  })
    .then(async (res) => {
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Error generant rànquing");
      }
      return res.json();
    })
    .then((data) => {
      const filename = data.filename;
      if (!files.includes(filename)) files.push(filename);
      renderFileList();
    })
    .catch((e) => alert(e.message));
}

function createRandom() {
  if (
    !confirm(
      "Generar 10 rànquings pot trigar força (fastText). Vols continuar?",
    )
  )
    return;

  // Desactivat el server per falta de ram
  alert("Uoops... ara mateix no és possible parla amb l'Aniol");
  return;

  const statusEl = document.getElementById("random-status");
  statusEl.style.display = "block";
  statusEl.textContent = "Generant 10 paraules aleatòries...";
  fetch(GENERATE_RANDOM_ENDPOINT, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ count: 10 }),
  })
    .then(async (res) => {
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Error generant rànquings aleatoris");
      }
      return res.json();
    })
    .then((data) => {
      data.generated.forEach((g) => {
        if (!files.includes(g.filename)) files.push(g.filename);
      });
      renderFileList();
      statusEl.textContent = `Generats ${data.count} fitxers.`;
      setTimeout(() => (statusEl.style.display = "none"), 4000);
    })
    .catch((e) => {
      statusEl.textContent = e.message;
      setTimeout(() => (statusEl.style.display = "none"), 4000);
    });
}

// Assignem l'event després de renderitzar
document.addEventListener("DOMContentLoaded", () => {
  const rndBtn = document.getElementById("create-random");
  if (rndBtn) rndBtn.onclick = createRandom;
  const searchBtn = document.getElementById("search-btn");
  const searchInput = document.getElementById("search-word");
  if (searchBtn && searchInput)
    searchBtn.onclick = () => triggerSearch(searchInput.value);
  if (searchInput) {
    searchInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") triggerSearch(searchInput.value);
    });
  }
});

// Esborrar fitxer
function showDeleteDialog(filename) {
  confirmDelete = filename;
  renderDialog();
}
function renderDialog() {
  const root = document.getElementById("dialog-root");
  if (!confirmDelete) {
    root.innerHTML = "";
    return;
  }
  root.innerHTML = `
		<div class="dialog-backdrop">
			<div class="dialog">
        <div style="margin-bottom:16px;">Segur que voleu esborrar el fitxer?</div>
				<div style="display:flex;justify-content:flex-end;gap:8px;">
					<button class="button" id="cancel-del">Cancel·la</button>
					<button class="button warning" id="confirm-del">Esborra</button>
				</div>
			</div>
		</div>
	`;
  document.getElementById("cancel-del").onclick = () => {
    confirmDelete = null;
    renderDialog();
  };
  document.getElementById("confirm-del").onclick = () =>
    deleteFile(confirmDelete);
}
function deleteFile(filename) {
  fetch(`${RANKINGS_API}/${filename}`, {
    method: "DELETE",
    headers: { ...authHeaders() },
  }).then(() => {
    files = files.filter((f) => f !== filename);
    if (selected === filename) {
      selected = null;
      words = [];
    }
    confirmDelete = null;
    renderFileList();
    renderWordsArea();
    renderDialog();
  });
}

// Guardar fitxer
function saveFile() {
  // NOMÉS desa si hi ha canvis i un fitxer seleccionat
  if (!selected || !dirty) return;

  // Detecta el bloc contigu inicial carregat (0..contiguousEnd-1)
  let contiguousEnd = 0;
  while (wordsByPos[contiguousEnd]) contiguousEnd++;

  // IMPORTANT: No podem sobreescriure tot el fitxer només amb aquest bloc
  // perquè perdríem la resta de paraules. Usem el mode "fragment" del backend
  // que actualitza només aquest tram mantenint la resta intacta.
  // L'endpoint interpreta l'ordre de les CLAUS del fragment; els valors s'ignoren.
  const fragment = {};
  for (let i = 0; i < contiguousEnd; i++) {
    fragment[wordsByPos[i].word] = i; // valor informatiu (no utilitzat pel backend)
  }

  const status = document.getElementById("autosave-status");
  if (status) {
    status.style.display = "inline";
    status.textContent = "Desant…";
  }

  fetch(`${RANKINGS_API}/${selected}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ fragment, offset: 0 }),
  })
    .then((r) => {
      if (!r.ok) throw new Error();
      dirty = false;
      showAutoSaveDone();
      // No recarreguem els tests automàticament per no perdre l'scroll
    })
    .catch(() => {
      if (status) {
        status.style.display = "inline";
        status.textContent = "Error desant";
      }
    });
}

function scheduleAutoSave() {
  if (!dirty) return; // res a desar
  if (autoSaveTimer) clearTimeout(autoSaveTimer);
  autoSaveTimer = setTimeout(() => {
    saveFile();
  }, AUTO_SAVE_DELAY);
  const status = document.getElementById("autosave-status");
  if (status) {
    status.style.display = "inline";
    status.textContent = "Pendents de desar…";
  }
}

function showAutoSaveDone() {
  const status = document.getElementById("autosave-status");
  if (status) {
    status.style.display = "inline";
    status.textContent = "Desat";
    setTimeout(() => {
      if (status.textContent === "Desat") status.style.display = "none";
    }, 2000);
  }
}

// Carregar més paraules
function loadMoreGap(start, endKnown) {
  if (!selected) return;
  let limit = PAGE_SIZE;
  if (endKnown !== null) {
    const gapSize = endKnown - start + 1;
    if (gapSize > 0 && gapSize < PAGE_SIZE) limit = gapSize; // només carrega el necessari
  }
  // Registra fins on arribava el bloc contigu abans de carregar
  let oldContiguousEnd = 0;
  while (wordsByPos[oldContiguousEnd]) oldContiguousEnd++;
  fetch(`${RANKINGS_API}/${selected}?offset=${start}&limit=${limit}`, {
    headers: { ...authHeaders() },
  })
    .then((res) => res.json())
    .then((data) => {
      data.words.forEach((w) => {
        if (!wordsByPos[w.pos]) wordsByPos[w.pos] = w;
      });
      total = data.total;
      renderWordsArea();
      // Actualitza títol si s'ha carregat la posició 0
      if (start === 0 && data.words.some((w) => w.pos === 0)) {
        updateWordsTitle();
      }
      // Després de renderitzar, calculem nou límit contigu i marquem nous ítems
      let newContiguousEnd = 0;
      while (wordsByPos[newContiguousEnd]) newContiguousEnd++;
      if (newContiguousEnd > oldContiguousEnd) {
        setTimeout(() => {
          const wordItems = document.querySelectorAll(".word-item");
          for (let pos = oldContiguousEnd; pos < newContiguousEnd; pos++) {
            wordItems.forEach((el) => {
              if (
                el.firstChild &&
                el.firstChild.textContent &&
                el.firstChild.textContent.startsWith(`${pos}.`)
              ) {
                tempHighlightElement(el);
              }
            });
          }
        }, 0);
      }
    });
  // No cal recarregar els tests aquí; només estem carregant més paraules per a la llista
}

function triggerSearch(term) {
  if (!selected) return;
  const t = term.trim().toLowerCase();
  if (!t) return;
  fetch(`${RANKINGS_API}/${selected}/find?word=${encodeURIComponent(t)}`, {
    headers: { ...authHeaders() },
  })
    .then((r) => r.json())
    .then(async (res) => {
      if (!res.found) {
        alert("No trobada");
        return;
      }
      await ensureVisible(res.pos, { highlight: true, forceScroll: true });
    })
    .catch(() => alert("Error en la cerca"));
}

// Cerca avançada (conté text o regex)
async function triggerAdvancedSearch(term) {
  if (!selected) return;
  const t = term.trim();
  if (!t) return;

  const isRegex = regexModeActive;

  try {
    const response = await fetch(
      `${RANKINGS_API}/${selected}/search?query=${encodeURIComponent(
        t,
      )}&is_regex=${isRegex}`,
      { headers: { ...authHeaders() } },
    );

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      alert(errorData.detail || "Error en la cerca");
      return;
    }

    const data = await response.json();

    if (!data.words || data.words.length === 0) {
      alert(`No s'han trobat resultats per: "${t}"`);
      return;
    }

    // Guarda els resultats per mostrar-los als tests
    searchResultsData = {
      query: t,
      is_regex: isRegex,
      count: data.count,
      words: data.words,
    };

    // Mostra els tests amb els resultats
    if (!testVisible) {
      await toggleTestOverlay();
    } else {
      await refreshTestOverlayIfVisible("search");
    }
  } catch (e) {
    console.error("Error en cerca avançada:", e);
    alert("Error en la cerca");
  }
}

// --- Afegir paraula nova al rànquing ---
async function promptAddNewWord() {
  if (!selected) return alert("Cal seleccionar un rànquing");
  const raw = prompt(
    "Escriu la paraula (nom o verb en forma canònica, sense flexió).\nAbans d'afegir recorda: només lemes (ex: 'anar', 'casa', no 'anant', 'cases').",
    "",
  );
  if (raw === null) return; // cancel·lat
  const word = (raw || "").trim().toLowerCase();
  if (!word) return;
  // Consulta info de lema
  let lemmaInfo = null;
  try {
    const r = await fetch(
      `${API_BASE}/lemma-info/${encodeURIComponent(word)}`,
      {
        headers: { ...authHeaders() },
      },
    );
    if (r.ok) lemmaInfo = await r.json();
  } catch (_) {}
  let warning = "Segur que voleu afegir «" + word + "»?\n";
  if (lemmaInfo) {
    if (!lemmaInfo.is_known) {
      warning +=
        "No s'ha trobat al diccionari; comprova bé que sigui un lema.\n";
    } else if (lemmaInfo.is_inflection) {
      warning += `ATENCIÓ: sembla una flexió del lema '${lemmaInfo.lemma}'.\n`;
    } else if (lemmaInfo.lemma && lemmaInfo.lemma === word) {
      warning += "Detectat com a lema vàlid.\n";
    }
  }
  warning +=
    "Confirma per afegir-la al final (o escriu una posició concreta).\n\nIntrodueix posició numèrica o deixa en blanc per posar-la al final.";
  const posStr = prompt(warning, "");
  if (posStr === null) return; // cancel
  let toPos = null;
  if (posStr.trim()) {
    const n = parseInt(posStr.trim(), 10);
    if (!isNaN(n) && n >= 0) toPos = n;
  }
  try {
    const res = await fetch(`${RANKINGS_API}/${selected}/add-new`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ word, to_pos: toPos }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: "Error" }));
      alert(err.detail || "Error afegint paraula");
      return;
    }
    const data = await res.json();
    // Recarrega primer bloc i assegura visibilitat de la nova posició
    await reloadInitialBlock();
    await ensureVisible(data.to, {
      highlight: true,
      special: true,
      force: data.to >= PAGE_SIZE,
    });
    // Reflecteix el canvi als tests sense recarregar-los (per mantenir l'scroll)
    updateTestWordAttributes(data.word, data.to);
    alert(
      `Afegida '${data.word}' a posició ${data.to}.` +
        (data.is_inflection
          ? `\nNota: sembla flexió del lema '${data.lemma}'.`
          : data.lemma
            ? "\nConfirmat com a lema."
            : ""),
    );
  } catch (e) {
    alert("Error de xarxa");
  }
}

// ==================== ESTADÍSTIQUES ====================

// Estat dels gràfics (per poder destruir-los quan es recarreguen)
let statsCharts = {};

function destroyStatsCharts() {
  Object.values(statsCharts).forEach((c) => {
    try {
      c.destroy();
    } catch (_) {}
  });
  statsCharts = {};
}

async function openStatsModal() {
  const modal = bootstrap.Modal.getOrCreateInstance(
    document.getElementById("statsModal"),
  );
  modal.show();

  const body = document.getElementById("stats-body");
  body.innerHTML =
    '<div class="text-center py-5"><div class="spinner-border text-primary" role="status"></div><p class="mt-2 text-muted">Carregant estadístiques...</p></div>';

  destroyStatsCharts();

  try {
    // Carregar totes les dades en paral·lel
    const [overviewRes, dailyRes, perGameRes, completionsRes, hintsRes] =
      await Promise.all([
        fetch(`${STATS_API}/overview`, { headers: authHeaders() }),
        fetch(`${STATS_API}/daily?days=30`, { headers: authHeaders() }),
        fetch(`${STATS_API}/per-game`, { headers: authHeaders() }),
        fetch(`${STATS_API}/completions`, { headers: authHeaders() }),
        fetch(`${STATS_API}/hints`, { headers: authHeaders() }),
      ]);

    if (!overviewRes.ok) throw new Error("Error carregant estadístiques");

    const overview = await overviewRes.json();
    const daily = await dailyRes.json();
    const perGame = await perGameRes.json();
    const completions = await completionsRes.json();
    const hints = await hintsRes.json();

    renderStatsContent(body, overview, daily, perGame, completions, hints);
  } catch (e) {
    body.innerHTML = `<div class="alert alert-warning"><i class="bi bi-exclamation-triangle"></i> ${e.message || "Error carregant estadístiques"}</div>
    <p class="text-muted">Les estadístiques es comencen a recollir quan els jugadors accedeixen al joc. Si la base de dades és buida, és normal.</p>`;
  }
}

function renderStatsContent(
  container,
  overview,
  daily,
  perGame,
  completions,
  hints,
) {
  // Formatadors
  const pct = (a, b) => (b > 0 ? Math.round((a / b) * 100) : 0);

  container.innerHTML = `
    <!-- RESUM -->
    <div class="row g-3 mb-4">
      <div class="col-md-3"><div class="stats-card stats-card-blue">
        <div class="stats-card-number">${overview.visits_today}</div>
        <div class="stats-card-label">Visites avui</div>
        <div class="stats-card-sub">${overview.total_visits} totals</div>
      </div></div>
      <div class="col-md-3"><div class="stats-card stats-card-green">
        <div class="stats-card-number">${overview.players_today}</div>
        <div class="stats-card-label">Jugadors avui</div>
        <div class="stats-card-sub">${overview.total_players} totals</div>
      </div></div>
      <div class="col-md-3"><div class="stats-card stats-card-purple">
        <div class="stats-card-number">${overview.returning_players}</div>
        <div class="stats-card-label">Jugadors recurrents</div>
        <div class="stats-card-sub">${pct(overview.returning_players, overview.total_players)}% del total</div>
      </div></div>
      <div class="col-md-3"><div class="stats-card stats-card-orange">
        <div class="stats-card-number">${overview.completions_today}</div>
        <div class="stats-card-label">Completats avui</div>
        <div class="stats-card-sub">${overview.total_completions} totals · ${overview.total_surrenders} rendicions</div>
      </div></div>
    </div>
    <div class="row g-3 mb-4">
      <div class="col-md-3"><div class="stats-card stats-card-teal">
        <div class="stats-card-number">${overview.avg_intents_per_completion}</div>
        <div class="stats-card-label">Mitjana d'intents per completar</div>
      </div></div>
      <div class="col-md-3"><div class="stats-card stats-card-pink">
        <div class="stats-card-number">${overview.total_hints}</div>
        <div class="stats-card-label">Pistes demanades (total)</div>
      </div></div>
      <div class="col-md-3"><div class="stats-card stats-card-blue">
        <div class="stats-card-number">${overview.players_used_simple_mode || 0}</div>
        <div class="stats-card-label">Jugadors que han usat SIMPLE</div>
        <div class="stats-card-sub">${overview.games_used_simple_mode || 0} jocs amb SIMPLE</div>
      </div></div>
      <div class="col-md-3"><div class="stats-card stats-card-gray">
        <div class="stats-card-number">${pct(overview.total_completions, overview.total_completions + overview.total_surrenders)}%</div>
        <div class="stats-card-label">Taxa de completació</div>
        <div class="stats-card-sub">(completats vs completats+rendicions)</div>
      </div></div>
    </div>
    
    <!-- GRÀFICS -->
    <div class="row g-3 mb-4">
      <div class="col-md-8">
        <div class="stats-chart-container">
          <h6 class="mb-2"><i class="bi bi-graph-up"></i> Activitat diària (últims 30 dies)</h6>
          <div style="position:relative;height:250px"><canvas id="stats-daily-chart"></canvas></div>
        </div>
      </div>
      <div class="col-md-4">
        <div class="stats-chart-container">
          <h6 class="mb-2"><i class="bi bi-pie-chart"></i> Distribució d'intents</h6>
          <div style="position:relative;height:250px"><canvas id="stats-completion-chart"></canvas></div>
        </div>
      </div>
    </div>
    
    <!-- TAULA PER JOC -->
    <div class="row g-3 mb-4">
      <div class="col-12">
        <div class="stats-chart-container">
          <h6 class="mb-2"><i class="bi bi-table"></i> Estadístiques per joc</h6>
          <div style="max-height:350px; overflow-y:auto;">
            <table class="table table-sm table-hover mb-0">
              <thead class="table-light sticky-top">
                <tr>
                  <th>Paraula</th>
                  <th class="text-center">Jugadors</th>
                  <th class="text-center">Intents</th>
                  <th class="text-center">Completats</th>
                  <th class="text-center">Rendicions</th>
                  <th class="text-center">Pistes</th>
                  <th class="text-center">Jugadors SIMPLE</th>
                  <th class="text-center">% SIMPLE</th>
                  <th class="text-center">Avg intents</th>
                  <th class="text-center">% Completació</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                ${
                  perGame.length === 0
                    ? '<tr><td colspan="11" class="text-muted text-center">Encara no hi ha dades</td></tr>'
                    : perGame
                        .map(
                          (g) => `
                    <tr>
                      <td><strong>${g.rebuscada}</strong>${g.game_id ? ` <small class="text-muted">#${g.game_id}</small>` : ""}</td>
                      <td class="text-center">${g.jugadors}</td>
                      <td class="text-center">${g.total_intents}</td>
                      <td class="text-center"><span class="badge bg-success">${g.completions}</span></td>
                      <td class="text-center"><span class="badge bg-danger">${g.surrenders}</span></td>
                      <td class="text-center">${g.hints}</td>
                      <td class="text-center">${g.simple_mode_players || 0}</td>
                      <td class="text-center">${g.simple_mode_rate ? g.simple_mode_rate + "%" : "0%"}</td>
                      <td class="text-center">${g.avg_intents ? Math.round(g.avg_intents * 10) / 10 : "-"}</td>
                      <td class="text-center">${g.completion_rate ? g.completion_rate + "%" : "-"}</td>
                      <td><button class="btn btn-outline-primary btn-sm py-0 px-1" onclick="loadWordsForGame('${g.rebuscada}')" title="Veure paraules jugades"><i class="bi bi-eye"></i></button></td>
                    </tr>
                  `,
                        )
                        .join("")
                }
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
    
    <!-- PARAULES JUGADES (dinàmic) -->
    <div id="stats-words-detail" class="mb-4" style="display:none;">
      <div class="stats-chart-container">
        <h6 class="mb-2"><i class="bi bi-chat-dots"></i> Paraules jugades per: <strong id="stats-words-title"></strong></h6>
        <div class="row g-3">
          <div class="col-md-7">
            <div style="position:relative;height:300px"><canvas id="stats-words-chart"></canvas></div>
          </div>
          <div class="col-md-5">
            <div id="stats-words-table" style="max-height:300px; overflow-y:auto;"></div>
          </div>
        </div>
        <!-- Llista de jugadors -->
        <hr class="my-3">
        <h6 class="mb-2"><i class="bi bi-people"></i> Partides individuals</h6>
        <div id="stats-players-list"></div>
        <div id="stats-player-session" style="display:none;" class="mt-3"></div>
      </div>
    </div>
  `;

  // Renderitzar gràfics
  renderDailyChart(daily);
  renderCompletionChart(completions);
}

function renderDailyChart(daily) {
  const ctx = document.getElementById("stats-daily-chart");
  if (!ctx || !daily.length) return;

  const labels = daily.map((d) => {
    const parts = d.data.split("-");
    return parts[2] + "/" + parts[1];
  });

  statsCharts.daily = new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: "Visites",
          data: daily.map((d) => d.visits),
          borderColor: "#4285f4",
          backgroundColor: "rgba(66,133,244,0.1)",
          fill: true,
          tension: 0.3,
        },
        {
          label: "Jugadors",
          data: daily.map((d) => d.players),
          borderColor: "#34a853",
          backgroundColor: "rgba(52,168,83,0.1)",
          fill: true,
          tension: 0.3,
        },
        {
          label: "Completats",
          data: daily.map((d) => d.completions),
          borderColor: "#fbbc04",
          backgroundColor: "rgba(251,188,4,0.1)",
          fill: true,
          tension: 0.3,
        },
        {
          label: "Rendicions",
          data: daily.map((d) => d.surrenders),
          borderColor: "#ea4335",
          backgroundColor: "rgba(234,67,53,0.05)",
          fill: false,
          tension: 0.3,
          borderDash: [5, 5],
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          position: "top",
          labels: { usePointStyle: true, boxWidth: 8 },
        },
      },
      scales: {
        y: { beginAtZero: true, ticks: { precision: 0 } },
        x: { ticks: { maxRotation: 45 } },
      },
      interaction: { intersect: false, mode: "index" },
    },
  });
}

function renderCompletionChart(completions) {
  const ctx = document.getElementById("stats-completion-chart");
  if (!ctx || !completions.length) return;

  const colors = [
    "#34a853",
    "#4285f4",
    "#fbbc04",
    "#ff6d01",
    "#ea4335",
    "#9334e6",
  ];

  statsCharts.completions = new Chart(ctx, {
    type: "doughnut",
    data: {
      labels: completions.map((c) => c.rang + " intents"),
      datasets: [
        {
          data: completions.map((c) => c.jugadors),
          backgroundColor: colors.slice(0, completions.length),
          borderWidth: 2,
          borderColor: "#fff",
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          position: "bottom",
          labels: { usePointStyle: true, boxWidth: 8, font: { size: 11 } },
        },
      },
    },
  });
}

async function loadWordsForGame(rebuscada) {
  const detail = document.getElementById("stats-words-detail");
  const title = document.getElementById("stats-words-title");
  const tableDiv = document.getElementById("stats-words-table");

  if (!detail) return;

  detail.style.display = "block";
  title.textContent = rebuscada;
  tableDiv.innerHTML =
    '<div class="text-center py-3"><div class="spinner-border spinner-border-sm text-primary"></div></div>';

  // Destruir gràfic anterior si existeix
  if (statsCharts.words) {
    statsCharts.words.destroy();
    delete statsCharts.words;
  }

  try {
    const res = await fetch(
      `${STATS_API}/words/${encodeURIComponent(rebuscada)}`,
      { headers: authHeaders() },
    );
    if (!res.ok) throw new Error();
    const words = await res.json();

    if (!words.length) {
      tableDiv.innerHTML = '<p class="text-muted">Sense dades</p>';
      return;
    }

    // Gràfic de barres amb les top 20 paraules
    const top = words.slice(0, 20);
    const ctx = document.getElementById("stats-words-chart");

    statsCharts.words = new Chart(ctx, {
      type: "bar",
      data: {
        labels: top.map((w) => w.paraula),
        datasets: [
          {
            label: "Vegades jugada",
            data: top.map((w) => w.vegades),
            backgroundColor: top.map((w) => {
              const p = w.millor_posicio;
              if (p < 100) return "rgba(52,168,83,0.7)";
              if (p < 250) return "rgba(251,188,4,0.7)";
              if (p < 500) return "rgba(255,109,1,0.7)";
              return "rgba(234,67,53,0.7)";
            }),
            borderRadius: 3,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        indexAxis: "y",
        plugins: { legend: { display: false } },
        scales: {
          x: { beginAtZero: true, ticks: { precision: 0 } },
          y: { ticks: { font: { size: 11 } } },
        },
      },
    });

    // Taula completa
    tableDiv.innerHTML = `
      <table class="table table-sm table-hover mb-0" style="font-size:12px;">
        <thead class="table-light sticky-top"><tr>
          <th>Paraula</th><th class="text-center">Vegades</th><th class="text-center">Millor pos.</th>
        </tr></thead>
        <tbody>
          ${words
            .map(
              (w) => `<tr>
            <td>${w.paraula}</td>
            <td class="text-center">${w.vegades}</td>
            <td class="text-center" style="color:${colorPerPos(w.millor_posicio)}">${w.millor_posicio}</td>
          </tr>`,
            )
            .join("")}
        </tbody>
      </table>`;

    // Carregar jugadors
    loadPlayersForGame(rebuscada);

    // Scroll a la secció
    detail.scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch (e) {
    tableDiv.innerHTML = '<p class="text-danger">Error carregant dades</p>';
  }
}

async function loadPlayersForGame(rebuscada) {
  const container = document.getElementById("stats-players-list");
  if (!container) return;
  container.innerHTML =
    '<div class="text-center py-2"><div class="spinner-border spinner-border-sm text-primary"></div></div>';
  // Amagar detall de sessió anterior
  const sessionDiv = document.getElementById("stats-player-session");
  if (sessionDiv) sessionDiv.style.display = "none";

  try {
    const res = await fetch(
      `${STATS_API}/players/${encodeURIComponent(rebuscada)}`,
      { headers: authHeaders() },
    );
    if (!res.ok) throw new Error();
    const players = await res.json();

    if (!players.length) {
      container.innerHTML =
        '<p class="text-muted small">Cap jugador registrat</p>';
      return;
    }

    // Agrupar jugadors per dia (a partir de primer_intent)
    const grouped = {};
    const dayOrder = [];
    players.forEach((p) => {
      let dayKey = "Desconegut";
      if (p.primer_intent) {
        try {
          const d = new Date(p.primer_intent);
          dayKey = d.toLocaleDateString("ca", {
            weekday: "short",
            day: "2-digit",
            month: "2-digit",
            year: "numeric",
          });
        } catch {
          dayKey = p.primer_intent.substring(0, 10);
        }
      }
      if (!grouped[dayKey]) {
        grouped[dayKey] = [];
        dayOrder.push(dayKey);
      }
      grouped[dayKey].push(p);
    });

    // Selector de dia + contenidor de jugadors
    let html = `<div class="d-flex align-items-center gap-2 mb-2">
      <select id="stats-day-select" class="form-select form-select-sm" style="width:auto;min-width:180px;">
        ${dayOrder.map((day) => `<option value="${day}">${day} (${grouped[day].length})</option>`).join("")}
      </select>
      <span id="stats-day-summary" class="text-muted small"></span>
    </div>
    <div id="stats-day-players" class="d-flex flex-wrap gap-2"></div>`;
    container.innerHTML = html;

    const daySelect = document.getElementById("stats-day-select");
    const playersDiv = document.getElementById("stats-day-players");
    const summarySpan = document.getElementById("stats-day-summary");

    function renderDayPlayers(dayKey) {
      const dayPlayers = grouped[dayKey] || [];
      const completed = dayPlayers.filter((p) => p.ha_completat).length;
      const surrendered = dayPlayers.filter((p) => p.es_rendicio).length;
      const simpleUsers = dayPlayers.filter((p) => p.simple_mode_used).length;
      summarySpan.innerHTML = `<span class="badge bg-success">${completed} <i class="bi bi-check-circle"></i></span> <span class="badge bg-danger">${surrendered} <i class="bi bi-x-circle"></i></span> <span class="badge bg-secondary">${dayPlayers.length - completed - surrendered} <i class="bi bi-hourglass-split"></i></span> <span class="badge bg-info text-dark" title="Han usat el mode simple en aquest joc">SIMPLE ${simpleUsers}</span>`;

      playersDiv.innerHTML = dayPlayers
        .map((p) => {
          const badge = p.ha_completat
            ? "bg-success"
            : p.es_rendicio
              ? "bg-danger"
              : "bg-secondary";
          const icon = p.ha_completat
            ? "check-circle"
            : p.es_rendicio
              ? "x-circle"
              : "hourglass-split";
          const simpleBadge = p.simple_mode_used ? '<span class="badge bg-info text-dark ms-1" title="Mode simple utilitzat">S</span>' : "";
          return `<button class="btn btn-sm btn-outline-secondary player-session-btn" 
            data-session="${p.session_id}" data-rebuscada="${rebuscada}"
            title="${p.short_id} — ${p.num_intents} intents, ${p.num_pistes} pistes${p.simple_mode_used ? ', mode simple' : ''}">
            <i class="bi bi-${icon} text-${p.ha_completat ? "success" : p.es_rendicio ? "danger" : "warning"}"></i>
            ${p.label}
            <span class="badge ${badge} ms-1">${p.num_intents}</span>
            ${simpleBadge}
          </button>`;
        })
        .join("");

      // Bind clicks als botons del dia
      playersDiv.querySelectorAll(".player-session-btn").forEach((btn) => {
        btn.addEventListener("click", () => {
          playersDiv
            .querySelectorAll(".player-session-btn")
            .forEach((b) => b.classList.remove("active"));
          btn.classList.add("active");
          loadPlayerSession(
            btn.dataset.rebuscada,
            btn.dataset.session,
            btn.textContent.trim().split("\n")[0],
          );
        });
      });
    }

    // Seleccionar l'últim dia per defecte
    daySelect.value = dayOrder[dayOrder.length - 1];
    renderDayPlayers(daySelect.value);

    daySelect.addEventListener("change", () => {
      renderDayPlayers(daySelect.value);
      const sessionDiv = document.getElementById("stats-player-session");
      if (sessionDiv) sessionDiv.style.display = "none";
    });
  } catch (e) {
    container.innerHTML =
      '<p class="text-danger small">Error carregant jugadors</p>';
  }
}

async function loadPlayerSession(rebuscada, sessionId, playerLabel) {
  const container = document.getElementById("stats-player-session");
  if (!container) return;
  container.style.display = "block";
  container.innerHTML =
    '<div class="text-center py-2"><div class="spinner-border spinner-border-sm text-primary"></div></div>';

  try {
    const res = await fetch(
      `${STATS_API}/player-session/${encodeURIComponent(rebuscada)}/${encodeURIComponent(sessionId)}`,
      { headers: authHeaders() },
    );
    if (!res.ok) throw new Error();
    const data = await res.json();

    // Combinar guesses i hints en una timeline
    const timeline = [];
    data.guesses.forEach((g) =>
      timeline.push({ ...g, type: "guess", ts: g.timestamp }),
    );
    data.hints.forEach((h) =>
      timeline.push({ ...h, type: "hint", ts: h.timestamp }),
    );
    if (data.surrendered)
      timeline.push({ type: "surrender", ts: data.surrender_time });
    timeline.sort((a, b) => a.ts.localeCompare(b.ts));

    if (!timeline.length) {
      container.innerHTML =
        '<p class="text-muted small">Sense dades per aquest jugador</p>';
      return;
    }

    // Format data i hora
    const fmtTime = (ts) => {
      if (!ts) return "";
      try {
        const d = new Date(ts);
        return (
          d.toLocaleDateString("ca", {
            day: "2-digit",
            month: "2-digit",
            year: "numeric",
          }) +
          " " +
          d.toLocaleTimeString("ca", {
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit",
          })
        );
      } catch {
        return ts.replace("T", " ").substring(0, 19) || "";
      }
    };

    let html = `<h6 class="mb-2 text-primary"><i class="bi bi-person"></i> ${playerLabel}</h6>`;
    html += '<div style="max-height:300px; overflow-y:auto;">';
    html +=
      '<table class="table table-sm mb-0" style="font-size:12px;"><thead class="table-light sticky-top"><tr>';
    html +=
      '<th style="width:30px">#</th><th>Acció</th><th>Paraula</th><th class="text-center">Posició</th><th>Data i hora</th></tr></thead><tbody>';

    let guessNum = 0;
    timeline.forEach((ev) => {
      if (ev.type === "guess") {
        guessNum++;
        const word = ev.forma_canonica
          ? `${ev.paraula} <small class="text-muted">(${ev.forma_canonica})</small>`
          : ev.paraula;
        const posColor = colorPerPos(ev.posicio);
        if (ev.es_correcta) {
          html += `<tr class="table-success"><td>${guessNum}</td><td><span class="badge bg-success">✓ Encert!</span></td><td><strong>${word}</strong></td><td class="text-center" style="color:${posColor}">${ev.posicio}</td><td class="text-muted">${fmtTime(ev.ts)}</td></tr>`;
        } else {
          html += `<tr><td>${guessNum}</td><td><span class="badge bg-light text-dark">Intent</span></td><td>${word}</td><td class="text-center" style="color:${posColor}">${ev.posicio}</td><td class="text-muted">${fmtTime(ev.ts)}</td></tr>`;
        }
      } else if (ev.type === "hint") {
        html += `<tr class="table-warning"><td></td><td><span class="badge bg-warning text-dark"><i class="bi bi-lightbulb"></i> Pista</span></td><td>${ev.paraula_pista}</td><td class="text-center" style="color:${colorPerPos(ev.posicio)}">${ev.posicio}</td><td class="text-muted">${fmtTime(ev.ts)}</td></tr>`;
      } else if (ev.type === "surrender") {
        html += `<tr class="table-danger"><td></td><td colspan="3"><span class="badge bg-danger"><i class="bi bi-flag"></i> S'ha rendit</span></td><td class="text-muted">${fmtTime(ev.ts)}</td></tr>`;
      }
    });

    html += "</tbody></table></div>";
    container.innerHTML = html;
    container.scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch (e) {
    container.innerHTML =
      '<p class="text-danger small">Error carregant la partida</p>';
  }
}

// ==================== FI ESTADÍSTIQUES ====================
