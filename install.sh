#!/usr/bin/env bash
# Installation sur le Raspberry Pi Zero 2 WH : OLA (+ prise en charge DMXking USB),
# Mosquitto, Tailscale et page de contrôle.
# Usage : copier install.sh et ola-lights.py dans le même dossier du Zero, puis :
#   bash install.sh
# Variables optionnelles : SKIP_TAILSCALE=1  SKIP_MQTT=1
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
[ -f "$DIR/ola-lights.py" ] || { echo "ola-lights.py introuvable à côté de install.sh"; exit 1; }

echo "== Paquets =="
sudo apt-get update
PKGS="ola python3-paho-mqtt curl"
[ "${SKIP_MQTT:-0}" = "1" ] || PKGS="$PKGS mosquitto mosquitto-clients"
sudo apt-get install -y $PKGS

echo "== OLA =="
sudo systemctl enable --now olad
# Ajoute l'utilisateur courant au groupe olad (droits pour les commandes ola_*)
OLA_USER="${SUDO_USER:-$USER}"
if getent group olad >/dev/null; then
  sudo usermod -aG olad "$OLA_USER"
  echo "$OLA_USER ajouté au groupe olad (effectif à la prochaine connexion SSH)"
else
  echo "Groupe olad introuvable : étape ignorée"
fi

echo "== Interface USB DMXking ultraDMX Micro (optionnelle) =="
# Pas de pilote à installer : la puce FTDI est gérée par le noyau (ftdi_sio, /dev/ttyUSB0)
# et OLA la pilote avec son plugin USB Serial (mode compatible Enttec USB Pro).
# 1) Le démon OLA doit pouvoir ouvrir /dev/ttyUSB* (groupe dialout sur Raspberry Pi OS).
if id olad >/dev/null 2>&1; then
  sudo usermod -aG dialout olad
  echo "Utilisateur olad ajouté au groupe dialout"
else
  echo "Utilisateur olad introuvable : vérifier sous quel compte tourne olad (ps -o user= -C olad)"
fi
# 2) Plugin USB Serial activé, plugin FTDI DMX désactivé (il prendrait l'interface
#    en contournant le pilote série ; il ne sert que pour les interfaces Open DMX).
set_ola_conf() {  # fichier clé valeur
  local f="/etc/ola/$1"
  if sudo test -f "$f"; then
    if sudo grep -q "^$2 *=" "$f"; then
      sudo sed -i "s/^$2 *=.*/$2 = $3/" "$f"
    else
      echo "$2 = $3" | sudo tee -a "$f" >/dev/null
    fi
    echo "$1 : $2 = $3"
  else
    echo "$1 absent (OLA ne l'a pas encore créé) : étape ignorée"
  fi
}
for _ in $(seq 1 15); do sudo test -f /etc/ola/ola-usbserial.conf && break; sleep 1; done
set_ola_conf ola-usbserial.conf enabled true
set_ola_conf ola-ftdidmx.conf enabled false
sudo systemctl restart olad

if [ "${SKIP_MQTT:-0}" != "1" ]; then
  echo "== Mosquitto (réseau local, sans mot de passe) =="
  sudo tee /etc/mosquitto/conf.d/lan.conf >/dev/null <<'EOF'
listener 1883
allow_anonymous true
EOF
  sudo systemctl enable mosquitto
  sudo systemctl restart mosquitto
fi

echo "== Page de contrôle =="
sudo install -d /opt/ola-lights
sudo install -m 755 "$DIR/ola-lights.py" /opt/ola-lights/ola-lights.py
sudo tee /etc/systemd/system/ola-lights.service >/dev/null <<'EOF'
[Unit]
Description=Contrôle des lumières (OLA)
After=network-online.target olad.service
Wants=network-online.target

[Service]
ExecStart=/usr/bin/python3 /opt/ola-lights/ola-lights.py
Environment=STATE_FILE=/var/lib/ola-lights/state.json
Environment=DMX_UNIVERSE=1
Environment=HTTP_PORT=8080
DynamicUser=yes
StateDirectory=ola-lights
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now ola-lights

if [ "${SKIP_TAILSCALE:-0}" != "1" ]; then
  echo "== Tailscale =="
  # Un échec de Tailscale ne doit pas bloquer le reste du script.
  if curl -fsSL https://tailscale.com/install.sh | sh; then
    echo "Ensuite, lance : sudo tailscale up"
  else
    echo "Tailscale : installation échouée."
    echo "Plan B : installer Tailscale sur une autre machine du lab et l'utiliser"
    echo "comme routeur de sous-réseau pour atteindre ce Zero (ports 8080 et 9090)."
  fi
fi

cat <<'EOF'

== Reste à faire à la main ==
1. Trouver l'appareil Art-Net dans OLA :   ola_dev_info
2. L'associer à l'univers 1 (adapter le numéro d'appareil) :
     ola_patch --device <N> --port <P> --universe 1
   ATTENTION au numéro de port : dans le plugin Art-Net d'OLA, le numéro du
   port de sortie EST le numéro d'univers Art-Net dans le subnet. Pour un
   nœud réglé sur l'univers Art-Net 1, c'est --port 1, pas --port 0.
   Avec le mauvais port, get_dmx renvoie les bonnes valeurs, les logs restent
   vierges, et rien ne s'allume.
   (ou dans l'interface web OLA, port 9090 : onglet Universes / Add Universe)
3. Sur le nœud Art-Net : mode « artnet -> dmx », et net / subnet / univers
   identiques à ceux du port Art-Net d'OLA.
   OLA n'a pas de champ « IP de destination » : en unicast il émet vers les
   nœuds qui ont répondu à son ArtPoll. Si un nœud joignable au ping ne reçoit
   rien, passer always_broadcast = true dans /etc/ola/ola-artnet.conf.
4. Décodeurs AKEPO : adresses 1, 5 et 9.
5. Page de contrôle : http://<ip-du-zero>:8080
   Routes simples : /zone/<1|2|3|all>/<couleur>, /all/random, /off
                    /intensite/<0-100|plus|moins>
   MQTT : lumieres/zone/<1|2|3|all>/set   (payload : #rrggbb, r,g,b ou {"r":..,"g":..,"b":..})
          lumieres/intensite/set          (payload : 0-100, + ou -)
6. (Optionnel) DMXking ultraDMX Micro : la brancher sur le hub, puis
     ola_dev_info            # repérer l'appareil (DMXking / Enttec USB Pro)
     ola_patch -d <N> -p 0 -u 1
   Patchée sur l'univers 1, elle sort les mêmes couleurs que le nœud Art-Net.
   Si rien n'apparaît : ls /dev/ttyUSB*  puis  sudo systemctl restart olad
EOF
