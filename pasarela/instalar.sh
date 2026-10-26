#!/bin/bash
# Despliega la pasarela en la caja de la impresora (Armbian, 192.168.0.102). Se ejecuta desde el PC.
# Requisito previo, una sola vez en la caja: tailscale instalado y `tailscale up --hostname=delta --accept-dns=false`
# (--accept-dns=false: la caja es el DNS de la casa con Pi-hole y Tailscale no debe tocarle el resolv.conf).
set -e
CAJA=root@192.168.0.102
cd "$(dirname "$0")"
ssh "$CAJA" 'mkdir -p /opt/delta-pasarela/iconos'
scp -q pasarela.py index.html manifest.webmanifest "$CAJA:/opt/delta-pasarela/"
scp -q iconos/*.png "$CAJA:/opt/delta-pasarela/iconos/"
scp -q delta-pasarela.service "$CAJA:/etc/systemd/system/"
ssh "$CAJA" 'systemctl daemon-reload && systemctl enable delta-pasarela && systemctl restart delta-pasarela && tailscale serve --bg 7890'
