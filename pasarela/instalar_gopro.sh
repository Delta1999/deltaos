#!/bin/bash
# Despliega el puente de la GoPro en la caja de la impresora (Armbian, 192.168.0.102). Se ejecuta desde el PC.
# Requisitos previos, una sola vez en la caja: adaptador WiFi USB (RTL8188EU) y /etc/netplan/40-gopro.yaml con la
# red GOPRO-BP-… (IP fija 10.5.5.100/24, sin rutas ni DNS) y /etc/delta-gopro.env (chmod 600) con GOPRO_PW=<clave WiFi>.
set -e
CAJA=root@192.168.0.102
cd "$(dirname "$0")"
ssh "$CAJA" 'mkdir -p /opt/delta-pasarela'
scp -q gopro_puente.py "$CAJA:/opt/delta-pasarela/"
scp -q delta-gopro.service "$CAJA:/etc/systemd/system/"
ssh "$CAJA" 'systemctl daemon-reload && systemctl enable delta-gopro && systemctl restart delta-gopro'
