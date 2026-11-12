# Lumières : guide d'utilisation

Trois zones de rubans LED RGB commandées par le Raspberry Pi, à l'adresse
**192.168.1.45** (ou `OLA.local`, ou le nom Tailscale depuis l'extérieur).

## 1. La page web

Ouvre **http://192.168.1.45:8080** sur ton téléphone ou ton ordi. Ajoute-la à
l'écran d'accueil pour l'avoir sous la main.

- **Zone 1, 2, 3** : touche la pastille de couleur et choisis. La lumière suit en direct.
- **Toutes les zones** : la même couleur partout.
- **Intensité** : le curseur va de 0 à 100 % par pas de 10. Les boutons **−** et
  **+** de part et d'autre font la même chose, un cran à la fois. Le réglage vaut
  pour les trois zones.
- **Boutons de scènes** : Éteint, Blanc chaud, Blanc, Rouge, Vert, Bleu, Ambre,
  Violet, Cyan.
- Un message rouge en bas (« OLA injoignable » ou « Connexion perdue ») signale un
  problème : voir la section 6.

Couleur et intensité sont indépendantes : baisser à 0 % puis remonter retrouve la
couleur. Les deux sont mémorisées et reviennent après une coupure de courant.

## 2. Les adresses rapides

Chaque adresse ouverte dans un navigateur, ou appelée par un raccourci, change la
lumière tout de suite.

| Adresse | Effet |
|---|---|
| `http://192.168.1.45:8080/zone/1/rouge` | Zone 1 en rouge |
| `http://192.168.1.45:8080/zone/2/ff8000` | Zone 2 en orange (hexadécimal, sans `#`) |
| `http://192.168.1.45:8080/all/chaud` | Les 3 zones en blanc chaud |
| `http://192.168.1.45:8080/zone/3/random` | Zone 3 dans une couleur vive au hasard |
| `http://192.168.1.45:8080/all/random` | Une couleur différente au hasard par zone |
| `http://192.168.1.45:8080/intensite/50` | Intensité à 50 % |
| `http://192.168.1.45:8080/intensite/plus` | Monter de 10 % |
| `http://192.168.1.45:8080/intensite/moins` | Baisser de 10 % |
| `http://192.168.1.45:8080/off` | Tout éteindre |

Zones : `1`, `2`, `3` ou `all`. On peut écrire `/all/<couleur>` au lieu de
`/zone/all/<couleur>`. Pour l'intensité, `intensity`, `dim`, `up` et `down`
fonctionnent aussi, et le `%` est toléré (`/intensite/40%`).

## 3. Les couleurs nommées

| Couleur | Noms acceptés | Couleur | Noms acceptés |
|---|---|---|---|
| Rouge | `rouge`, `red` | Jaune | `jaune`, `yellow` |
| Vert | `vert`, `green` | Violet | `violet`, `purple` |
| Bleu | `bleu`, `blue` | Rose | `rose`, `pink` |
| Blanc | `blanc`, `white` | Cyan | `cyan` |
| Blanc chaud | `chaud`, `warm` | Éteint | `off`, `eteint`, `noir`, `black` |
| Ambre | `ambre`, `amber` | Au hasard | `random`, `aleatoire`, `hasard` |

Les majuscules ne comptent pas. Pour toute autre couleur, son code hexadécimal à
6 caractères (ex. `00ff80`).

## 4. Raccourcis et domotique

- **iPhone (Raccourcis)** : action « Obtenir le contenu de l'URL » avec une adresse
  rapide, puis le raccourci à l'écran d'accueil ou à Siri (« Lumières rouges »).
- **Android** : widget de favori de navigateur, ou une app de requêtes HTTP
  (HTTP Shortcuts, Tasker).
- **Ligne de commande** :

  ```bash
  curl http://192.168.1.45:8080/all/bleu
  curl http://192.168.1.45:8080/intensite/30
  ```

- **MQTT** (Home Assistant, Node-RED, scripts) :

  ```bash
  mosquitto_pub -h 192.168.1.45 -t lumieres/zone/all/set -m '#ff0000'
  mosquitto_pub -h 192.168.1.45 -t lumieres/intensite/set -m '40'
  mosquitto_pub -h 192.168.1.45 -t lumieres/intensite/set -m '+'
  ```

  L'état est publié sur `lumieres/zone/N/state` et `lumieres/intensite/state`.

## 5. Un mot sur l'intensité

Les décodeurs n'ont pas de canal de gradateur : l'intensité est obtenue en
atténuant les valeurs de couleur avant de les envoyer. Conséquence pratique :
**un ruban à 10 % ne donne pas 10 % de lumière perçue**. L'échelle est linéaire
en DMX, pas pour l'œil, donc le bas de la plage paraît chuter plus vite que le
haut. C'est normal, pas un défaut de réglage.

En dessous de 10 %, les valeurs envoyées deviennent très petites (26 sur 255) et
certains rubans commencent à scintiller ou à tirer vers une teinte un peu fausse,
les trois canaux ne descendant pas exactement au même rythme.

## 6. Si ça ne marche pas

| Symptôme | À essayer |
|---|---|
| La page ne s'ouvre pas | Le Pi est-il allumé et sur le réseau ? En SSH : `sudo systemctl status ola-lights` |
| « OLA injoignable » | `sudo systemctl restart olad`, puis réessaie après 10 secondes |
| La page répond mais rien ne s'allume | L'intensité n'est-elle pas à 0 % ? Nœud Art-Net alimenté, en mode `artnet -> dmx` ? Décodeurs alimentés et adressés à 1, 5 et 9 ? Teste la DMX Console d'OLA : http://192.168.1.45:9090 |
| Tout est très sombre | Intensité au minimum : `curl http://192.168.1.45:8080/intensite/100` |
| Une seule zone ne réagit pas | Vérifie l'adresse de ce décodeur et le câble RJ45 qui y mène (Signal Out vers Signal In) |
| Mauvaises couleurs (rouge et vert inversés…) | Câblage du ruban sur le décodeur : CH1 = rouge, CH2 = vert, CH3 = bleu |
| Après une panne de courant | Rien à faire : la dernière couleur et la dernière intensité reviennent seules |

Pour voir ce que le Pi envoie vraiment, sans dépendre des lampes :

```bash
curl 'http://192.168.1.45:9090/get_dmx?u=1'
```

Les 12 premiers canaux correspondent aux trois zones : 1-3, 5-7, 9-11.
