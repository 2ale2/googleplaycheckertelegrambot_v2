#!/bin/bash

echo "=== Verifica aggiornamenti e installazione python3-venv... ===

"
sudo apt update && sudo apt upgrade -y && sudo apt install -y python3-venv

sleep 1

echo "

=== Clonazione del progetto ===

"
git clone https://github.com/2ale2/googleplaycheckertelegrambot_v2.git || {
  echo "Errore durante la clonazione del repository"
  exit 1
}
cd googleplaycheckertelegrambot_v2 || exit

mkdir logs

REPO_PATH="$(pwd)/googleplaycheckertelegrambot_v2"

sleep 1

echo "

=== Aggiungendo il modulo 'modules' al PYTHONPATH ==="

if ! grep -q "$REPO_PATH" ~/.bashrc; then
  echo "export PYTHONPATH=\$PYTHONPATH:$REPO_PATH" >> ~/.bashrc
  echo "

=== Percorso aggiunto a PYTHONPATH ==="
else
    echo "

=== i - Il percorso è già presente in PYTHONPATH ==="
fi

source "$HOME/.bashrc"

sleep 2

echo "

=== Creazione dell'ambiente virtuale ==="
python3 -m venv .venv || {
  echo "Errore durante la creazione dell'ambiente virtuale"
  exit 1
}
sleep 2

source .venv/bin/activate

sleep 1

if ! command -v pip &> /dev/null; then
    echo "pip non è installato. Vuoi installarlo? (y/n)"
    read -r install_pip
    if [[ $install_pip == "y" ]]; then
        sudo apt install -y python3-pip || {
            echo "Errore durante l'installazione di pip."
            exit 1
        }
    else
        echo "E' necessario avere pip per procedere."
        exit 1
    fi
fi

echo "

=== Installazione delle dipendenze ==="
pip install -r requirements.txt || {
  echo "Errore durante l'installazione delle dipendenze

  "
  exit 1
}
pip install "python-telegram-bot[callback-data]"
pip install "python-telegram-bot[job-queue]"
sleep 2

echo "

=== Decrittografia del file .env crittografato... ==="
success=0
max_attempts=3
attempts=0
sleep 2

while [ $success -eq 0 ] && [ $attempts -lt $max_attempts ]; do
    ((attempts++))
    echo "

> Tentativo $attempts di $max_attempts"
    read -sp ">> Inserisci la password per decrittografare il file .env:" password
    echo

    if gpg --batch --passphrase "$password" -d .env.gpg > .env; then
        success=1
        echo "

i - .env decrittografato con successo."
    else
        echo "

i - Password errata. Riprova."
    fi
done

if [ $success -eq 0 ]; then
    echo "Errore: troppi tentativi falliti. Uscita dal processo."
    exit 1
fi
sleep 2


if [ -f ".env" ]; then
    echo "

=== Il file .env è stato creato ==="
fi

sleep 2

echo "

======== Configurazione completata ========

Per avviare il bot, esegui questi comandi:
1. cd googleplaycheckertelegrambot_v2
2. source .venv/bin/activate
3. python3 modules/main.py

i - E' consigliabile aggiungere lo script come servizio per non doverlo avviare manualmente ogni volta
"
sleep 2