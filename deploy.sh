#!/bin/bash
# Deploy local_daikin from repo to HA custom_components
SRC="/home/node/.openclaw/workspace/local_daikin/custom_components/local_daikin"
DEST="/homeassistant/custom_components/local_daikin"

rm -rf "$DEST"/__pycache__
cp -a "$SRC/"* "$DEST/"
rm -rf "$DEST/__pycache__"
echo "✅ Deployed to HA"
