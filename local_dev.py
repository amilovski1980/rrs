import os
import sys
import subprocess
from pathlib import Path

# Configuration des chemins
BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR / "rrs"

def setup_env():
    """Configure l'environnement pour permettre les tests et modifications."""
    # 1. Ajout du dossier rrs au PYTHONPATH pour résoudre les imports
    if str(PROJECT_DIR) not in sys.path:
        sys.path.insert(0, str(PROJECT_DIR))
    
    # 2. Changement du répertoire de travail vers le dossier du projet
    if PROJECT_DIR.exists():
        os.chdir(PROJECT_DIR)
    else:
        print(f"❌ Erreur : Le dossier {PROJECT_DIR} est introuvable.")
        sys.exit(1)

def run_django(args):
    """Lance une commande Django via manage.py."""
    manage_py = PROJECT_DIR / "manage.py"
    if not manage_py.exists():
        print("❌ manage.py introuvable.")
        return

    cmd = [sys.executable, "manage.py"] + args
    print(f"🚀 Exécution : {' '.join(cmd)}")
    
    try:
        # On utilise subprocess pour isoler l'exécution
        result = subprocess.run(cmd, capture_output=False, text=True)
        return result.returncode
    except Exception as e:
        print(f"💥 Erreur : {e}")
        return 1

if __name__ == "__main__":
    setup_env()
    
    if len(sys.argv) > 1:
        # Si des arguments sont passés, on les transmet à manage.py
        sys.exit(run_django(sys.argv[1:]))
    else:
        # Menu par défaut pour tester le build
        print("--- 🛠️ Menu de Test Local ---")
        print("1. Vérifier les erreurs de build (check)")
        print("2. Tester les migrations (migrate)")
        print("3. Lancer les tests (test)")
        print("4. Quitter")
        
        choice = input("\nChoix : ")
        if choice == "1":
            run_django(["check"])
        elif choice == "2":
            run_django(["migrate"])
        elif choice == "3":
            run_django(["test"])
        else:
            print("Fin.")
