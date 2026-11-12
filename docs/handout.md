# Handout : nœud DMX OLA sur Raspberry Pi Zero 2 W

Mis à jour le 11 novembre 2026, après la première installation réelle.
À joindre au début d'une session Claude desktop (SSH sur le Pi), avec `install.sh`
et `ola-lights.py`. Le mode d'emploi au quotidien est dans `guide-lumieres.md`.

## 1. Où on en est

Tout fonctionne. L'installation a été faite sur le Pi, avec le vrai OLA, le vrai
nœud Art-Net et les trois décodeurs : les trois zones répondent aux bonnes
adresses, avec les bonnes couleurs, et l'intensité s'applique correctement.

Les sections « non vérifié » des versions précédentes de ce document sont donc
caduques — ce qui reste à surveiller est signalé en section 8.

## 2. Matériel

| Élément | Détail |
|---|---|
| Raspberry Pi Zero 2 W | 4 cœurs Cortex-A53, 64 bits, 512 Mo de RAM (~415 Mo visibles). Hostname `OLA`, Debian 13 (trixie), noyau 6.18 arm64. |
| Réseau | Adaptateur Ethernet USB Plugable (puce ASIX) sur un hub USB OTG, port data du Pi. `eth0` en **192.168.1.45**. `avahi-daemon` actif, donc `OLA.local` répond aussi. |
| Alimentation | PoE : splitter 5 V avec sortie micro-USB (2 A ou plus) sur le port PWR. |
| Nœud Art-Net | Erhai / Pknight CR001R, **192.168.1.81**. 1 univers, 512 canaux, sortie XLR 3 broches, écran OLED + 4 boutons. Mode unicast, net 0 / subnet 0 / **univers 1**. |
| Décodeurs | 3 × AKEPO DMX 4 canaux (12-24 V, 4 A/canal), entrée XLR + 2 ports RJ45. Utilisés en RGB : 3 canaux par décodeur, le canal blanc reste à 0. |
| Optionnelle | Interface USB DMXking ultraDMX Micro (compatible Enttec USB Pro). Pas de pilote à installer : puce FTDI gérée par le noyau, plugin USB Serial d'OLA. `install.sh` la prépare. Non testée à ce jour. |

## 3. Schéma

```
Pi (OLA) --Ethernet--> switch --Ethernet--> nœud Art-Net
nœud Art-Net --XLR (DMX)--> décodeur 1 --RJ45 (DMX)--> décodeur 2 --RJ45 (DMX)--> décodeur 3
```

- Les RJ45 des décodeurs portent du **DMX, pas de l'Ethernet** : ne jamais les
  brancher au switch, au routeur ou au PoE.
- Câbles RJ45 droits, de « Signal Out » vers « Signal In » (ports différents).
- Décodeurs aux adresses **1, 5 et 9**. Zone 1 = canaux 1-3, zone 2 = canaux 5-7,
  zone 3 = canaux 9-11.

## 4. Installation

```bash
bash install.sh          # variables : SKIP_TAILSCALE=1, SKIP_MQTT=1
```

Le script installe OLA, Mosquitto (réseau local, sans mot de passe), le service
`ola-lights` (port 8080) et Tailscale. Il ajoute l'utilisateur courant au groupe
`olad` et l'utilisateur `olad` au groupe `dialout`, active le plugin USB Serial
et désactive le plugin FTDI DMX.

À savoir sur cette machine :

- **`sudo` demande un mot de passe** — le script est entièrement à base de `sudo`,
  il faut donc le lancer dans un terminal interactif.
- **C'est lent.** 415 Mo de RAM et le swap saturé : `apt-get` passe l'essentiel de
  son temps en I/O wait. Compter une vingtaine de minutes, et éviter de lancer
  autre chose de lourd en parallèle.
- Après l'installation, **se reconnecter en SSH** pour que l'appartenance au
  groupe `olad` prenne effet. En attendant : `sg olad -c 'ola_dev_info'`.

## 5. Configuration à faire à la main

```bash
ola_dev_info                      # repérer l'appareil Art-Net (device 2 ici)
ola_patch -d 2 -p 1 -u 1          # port 1 = univers Art-Net 1
```

> **Le piège.** Les versions précédentes de ce handout indiquaient `--port 0`.
> C'est faux. Dans le plugin Art-Net d'OLA, **le numéro du port de sortie *est* le
> numéro d'univers Art-Net dans le subnet**. Le nœud étant réglé sur l'univers 1,
> il faut le port 1. Avec le port 0, OLA émet sur l'univers Art-Net 0 : `get_dmx`
> renvoie les bonnes valeurs, les logs restent vierges, et rien ne s'allume.

- **Nœud Art-Net** (menu OLED) : mode `artnet -> dmx`, net 0 / subnet 0, univers 1,
  IP fixe 192.168.1.81.
- **Décodeurs** : adresses 1, 5 et 9 ; réglages H (mode) et S (vitesse) en DMX normal.
- **Test** : `ola_set_dmx -u 1 -d 255,0,0` allume la zone 1 en rouge.

### Unicast

`/etc/ola/ola-artnet.conf` est en `always_broadcast = false`. OLA **n'a pas de champ
« IP de destination »** : en unicast, il envoie aux nœuds qui ont répondu à son
ArtPoll. Le CR001R répond correctement, donc rien à faire. Si un nœud restait muet
alors qu'il est joignable au ping, le repli est :

```bash
sudo sed -i 's/^always_broadcast = false/always_broadcast = true/' /etc/ola/ola-artnet.conf
sudo systemctl restart olad
```

## 6. Contrôle

- **Page web** : http://192.168.1.45:8080 — un sélecteur de couleur par zone, un
  pour toutes les zones, un réglage d'**intensité générale** (curseur par pas de
  10 % encadré de boutons −/+), et 9 scènes.
- **Routes simples** (GET) : `/zone/<1|2|3|all>/<couleur>`, `/all/<couleur>`,
  `/all/random`, `/off`, `/intensite/<0-100|plus|moins>`.
- **MQTT** : `lumieres/zone/<1|2|3|all>/set` (`#rrggbb`, `r,g,b` ou JSON) et
  `lumieres/intensite/set` (`0`-`100`, `+` ou `-`). États publiés sur
  `lumieres/zone/N/state` et `lumieres/intensite/state`.
- **API HTTP d'OLA** : `POST http://localhost:9090/set_dmx` avec `u` et `d`.
  Lecture : `curl 'http://localhost:9090/get_dmx?u=1'` — très pratique pour
  vérifier ce qu'OLA émet vraiment, sans dépendre des lampes.

### L'intensité

Les décodeurs AKEPO n'ont pas de canal de gradateur maître. L'intensité est donc
appliquée dans `ola-lights.py`, en multipliant les valeurs RGB juste avant
l'envoi DMX. Couleur et intensité sont deux réglages **séparés** : descendre à
0 % puis remonter restitue la couleur au lieu de la perdre.

### La courbe de gradation

Le décodeur fait du **PWM linéaire** : à la valeur DMX 128, le ruban émet bien la
moitié des photons — mais l'œil y voit environ 73 % de luminosité. Sans
correction, le haut du curseur semble ne rien faire et le bas s'effondre.

`brightness_factor()` élève donc le facteur à la puissance `GAMMA` (2,2 par
défaut), ce qui rend le curseur linéaire **pour la perception** :

| Curseur | DMX sans correction | DMX avec gamma | Luminosité perçue |
|---|---|---|---|
| 100 % | 255 | 255 | 100 % |
| 70 % | 178 | 116 | 70 % |
| 50 % | 128 | 55 | 50 % |
| 30 % | 76 | 18 | 30 % |
| 10 % | 26 | 2 | 11 % |

La correction porte sur le **facteur d'intensité**, jamais sur les couleurs
elles-mêmes : le rendu d'une couleur donnée à 100 % est inchangé.

Réglable sans toucher au code, via le service : `Environment=GAMMA=2.2` dans
`/etc/systemd/system/ola-lights.service`. `GAMMA=1` restaure l'ancien
comportement linéaire.

Revers de la médaille : en bas d'échelle les valeurs DMX deviennent minuscules
(2 à 10 %, 7 à 20 %). Sur 8 bits il n'y a plus beaucoup de marche disponible, et
c'est là que des rubans bon marché scintillent ou dérivent en teinte. Si c'est
gênant, un `GAMMA` plus doux (1,8) relève le bas de la plage.

## 7. État persistant

`STATE_FILE=/var/lib/ola-lights/state.json`, avec `DynamicUser=yes` et
`StateDirectory` : le fichier réel est dans `/var/lib/private/ola-lights/`.

Format : `{"zones": [[r,g,b], [r,g,b], [r,g,b]], "brightness": 100}`. Le démon
relit aussi l'ancien format (simple liste de couleurs) sans broncher. Couleurs et
intensité reviennent au démarrage.

## 8. À surveiller

- **La carte SD.** Pendant l'installation, `iptables_1.8.11-2_arm64.deb` avait la
  taille annoncée mais un SHA256 différent de celui du dépôt — or apt vérifie le
  hash au téléchargement, donc le fichier s'est abîmé une fois écrit. Le
  retéléchargement est passé sans problème. Un incident isolé peut arriver ; si
  d'autres corruptions apparaissent, c'est le premier suspect.
- **Tailscale** est installé et `tailscaled` tourne, mais la machine est
  déconnectée (`Logged out`). Faire `sudo tailscale up` au besoin. Son
  installation avait d'abord échoué, emportée par le `.deb` corrompu ci-dessus.
- **La DMXking ultraDMX Micro** n'a jamais été branchée. `install.sh` a fait sa
  part (groupe `dialout`, plugin USB Serial activé, plugin FTDI DMX désactivé),
  mais rien n'est vérifié.
- **Node-RED** : à mettre sur une autre machine, il n'y a pas la RAM ici.

## 9. Vérifications utiles

```bash
systemctl is-active olad ola-lights mosquitto
curl -s localhost:8080/api/state                 # {"zones": [...], "intensite": N}
curl -s 'http://localhost:9090/get_dmx?u=1'      # ce qu'OLA émet vraiment
sg olad -c 'ola_uni_info'                        # l'univers 1 existe-t-il ?
journalctl -u ola-lights -n 20
```
