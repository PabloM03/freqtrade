#!/bin/bash

# Comprobación de argumento
if [ -z "$1" ]; then
  echo "❌ Uso: ./changeStrategy.sh NombreEstrategia.py"
  exit 1
fi

FILE="$1"
STRATEGY_NAME=$(basename "$FILE" .py)
STRATEGY_DIR="user_data/strategies"
CONFIG_FILE="config.json"

# Verifica que el archivo existe
if [ ! -f "$FILE" ]; then
  echo "❌ El archivo '$FILE' no existe en el directorio actual."
  exit 1
fi

# Mueve el archivo al directorio de estrategias
echo "� Moviendo '$FILE' a '$STRATEGY_DIR/'..."
mv "$FILE" "$STRATEGY_DIR/" || {
  echo "❌ Error al mover el archivo"
  exit 1
}

# Modifica la línea de "strategy": en config.json usando sed
echo "� Cambiando estrategia en config.json a '$STRATEGY_NAME'..."
sed -i -E 's/^\s*"strategy":\s*"[^\"]*"/  "strategy": "'$STRATEGY_NAME'"/' "$CONFIG_FILE"

# Verifica si sed tuvo éxito
if [ $? -ne 0 ]; then
  echo "❌ Error al modificar config.json"
  exit 1
fi

# Reinicia el servicio de freqtrade
echo "� Reiniciando el servicio freqtrade..."
sudo systemctl restart freqtrade

# Espera un poco para que el servicio arranque
sleep 3

# Muestra el estado del servicio
echo "� Estado del servicio:"
sudo systemctl status freqtrade -n 20 --no-pager
