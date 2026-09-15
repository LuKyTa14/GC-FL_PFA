#!/usr/bin/env bash
# Salir si hay un error
set -o errexit

# Instalar dependencias
pip install -r requirements.txt

# Convertir archivos estaticos
python manage.py collectstatic --no-input

# Aplicar migraciones
python manage.py migrate