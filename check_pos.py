import json

data = json.load(open('data/words/hora.json', encoding='utf-8'))

words = [
    'segon', 'període', 'calendari', 'interval', 'cita',
    'rellotge', 'segons', 'horària', 'puntual', 'cronòmetre',
    'trimestre', 'semestre', 'bienni', 'quinzena', 'dècada',
    'segle', 'despertador', 'alarma', 'campana',
    'deadline', 'termini', 'compte enrere', 'compàs',
    'freqüència', 'periodicitat', 'curs', 'cicle',
    'esmorzar', 'dinar', 'sopar', 'berenar',
    'puntualitat', 'retard', 'endarreriment', 'avançament',
    'matinal', 'nocturn', 'diürn', 'vespertí',
    'aniversari', 'efemèride', 'commemoració',
    'urgent', 'urgència', 'pressa', 'precipitació',
]

not_found = "NO TROBADA"
for w in words:
    pos = data.get(w, not_found)
    marker = ""
    if pos != not_found and pos > 200:
        marker = " ← MASSA LLUNY!"
    elif pos != not_found and pos <= 100:
        marker = " ✓"
    print(f"  {w}: {pos}{marker}")
