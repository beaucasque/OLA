# OLA — nœud DMX et contrôle des lumières sur Raspberry Pi Zero 2 W

Trois zones de rubans LED RGB pilotées depuis une page web, via
[OLA](https://www.openlighting.org/ola/) et un nœud Art-Net.

```
Pi Zero 2 W (OLA) --Ethernet--> switch --Ethernet--> nœud Art-Net
nœud Art-Net --XLR (DMX)--> décodeur 1 --RJ45 (DMX)--> décodeur 2 --RJ45 (DMX)--> décodeur 3
```

## Contenu du dépôt

| Fichier | Rôle |
|---|---|
| `install.sh` | Installation complète : OLA, Mosquitto, service systemd, Tailscale |
| `ola-lights.py` | Le démon : page web, routes URL, MQTT, envoi DMX à olad |
| `docs/handout.md` | État du montage, matériel, configuration — à joindre à une session Claude |
| `docs/guide-lumieres.md` | Mode d'emploi au quotidien |
| `reference/*.pdf` | Les documents d'origine, avant la première installation réelle |

## Installation

Copier les deux fichiers dans le même dossier du Pi, puis :

```bash
bash install.sh
```

Variables optionnelles : `SKIP_TAILSCALE=1`, `SKIP_MQTT=1`.

Ensuite, patcher l'univers DMX — voir [docs/handout.md](docs/handout.md), section
« Configuration à faire à la main ». **Attention au numéro de port** : dans le
plugin Art-Net d'OLA, le numéro du port de sortie *est* le numéro d'univers
Art-Net dans le subnet. Pour un nœud réglé sur l'univers 1, c'est `--port 1`.

## Utilisation

Page de contrôle : **http://192.168.1.45:8080**

```bash
curl http://192.168.1.45:8080/zone/1/rouge
curl http://192.168.1.45:8080/all/chaud
curl http://192.168.1.45:8080/intensite/50
curl http://192.168.1.45:8080/off
```

Le mode d'emploi complet est dans [docs/guide-lumieres.md](docs/guide-lumieres.md).

## État

Installé et vérifié sur le matériel réel le 11 novembre 2026 : les trois zones
répondent aux bonnes adresses DMX, avec les bonnes couleurs et l'atténuation
proportionnelle.
