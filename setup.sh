#!/bin/bash

echo "Clonazione del progetto..."
git clone https://github.com/tuo/repository.git || {
  echo "Errore durante la clonazione del repository"
  exit 1
}
cd repository || exit

echo "Creazione dell'ambiente virtuale..."
python3 -m venv venv || {
  echo "Errore durante la creazione dell'ambiente virtuale"
  exit 1
}

source venv/bin/activate

echo "Installazione delle dipendenze..."
pip install -r requirements.txt || {
  echo "Errore durante l'installazione delle dipendenze"
  exit 1
}

echo "Decrittografia del file .env crittografato..."
success=0
max_attempts=3
attempts=0

while [ $success -eq 0 ] && [ $attempts -lt $max_attempts ]; do
    ((attempts++))
    echo "Tentativo $attempts di $max_attempts"
    read -sp "Inserisci la password per decrittografare il file .env: " password
    echo

    if gpg --batch --passphrase "$password" -d .env.gpg > .env; then
        success=1
        echo ".env decrittografato con successo."
    else
        echo "Password errata. Riprova."
    fi
done

if [ $success -eq 0 ]; then
    echo "Errore: troppi tentativi falliti. Uscita dal processo."
    exit 1
fi


if [ -f ".env" ]; then
    echo "Il file .env è stato creato. Assicurati che le variabili nel file .env siano corrette!"
fi

echo "Configurazione completata. Attiva l'ambiente virtuale con 'source venv/bin/activate' e avvia il bot con 'python3 main.py'"
