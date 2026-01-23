#!/usr/bin/env python3
"""
Script de prova per validar que l'algorisme OpenAI funciona correctament.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Carregar variables d'entorn del fitxer .env
load_dotenv()

# Afegir el directori actual al path
import sys
sys.path.insert(0, str(Path(__file__).parent))

def test_openai_algorithm():
    """Prova l'algorisme OpenAI amb un petit conjunt de paraules."""
    
    # Verificar que la clau API està configurada
    if not os.getenv("OPENAI_API_KEY"):
        print("❌ Error: No s'ha trobat la variable d'entorn OPENAI_API_KEY")
        print("\nConfigura-la amb:")
        print("  export OPENAI_API_KEY='sk-proj-...'  # Linux/Mac")
        print("  $env:OPENAI_API_KEY='sk-proj-...'    # Windows PowerShell")
        return False
    
    print("✅ Clau API d'OpenAI trobada")
    
    # Importar el mòdul
    try:
        import proximitatOpenAI
        print("✅ Mòdul proximitatOpenAI importat correctament")
    except ImportError as e:
        print(f"❌ Error important el mòdul: {e}")
        return False
    
    # Provar amb un petit conjunt de paraules
    paraules_test = ["amor", "odi", "felicitat", "tristesa", "casa", "arbre", "cotxe"]
    paraula_objectiu = "amor"
    
    print(f"\n🧪 Provant amb paraula objectiu: '{paraula_objectiu}'")
    print(f"📝 Diccionari de prova: {paraules_test}")
    
    try:
        ranking = proximitatOpenAI.calcular_ranking_complet(
            paraula_objectiu,
            paraules_test,
            guardar_debug=False
        )
        
        print("\n✅ Ranking calculat correctament!")
        print("\nResultats:")
        for paraula, posicio in sorted(ranking.items(), key=lambda x: x[1]):
            print(f"  {posicio + 1}. {paraula}")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Error durant el càlcul: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("=" * 60)
    print("Test de l'algorisme OpenAI")
    print("=" * 60 + "\n")
    
    success = test_openai_algorithm()
    
    print("\n" + "=" * 60)
    if success:
        print("✅ Test completat amb èxit!")
        print("\nJa pots utilitzar l'algorisme OpenAI amb:")
        print("  python generate.py --paraula \"amor\" --algorisme openai")
    else:
        print("❌ El test ha fallat")
    print("=" * 60)
