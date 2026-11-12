#!/usr/bin/env python3
"""Contrôle de 3 zones RGB (décodeurs DMX 4 canaux) via OLA.

- Page web mobile (sélecteur de couleur par zone) sur le port HTTP_PORT (8080)
- Routes simples en GET : /zone/<1-3|all>/<couleur>, /all/<couleur>, /off
  (couleur nommée, hexadécimale sans # ou random)
- MQTT optionnel (si paho-mqtt est installé)
- Envoie le DMX à OLA par son API HTTP (POST /set_dmx)

Bibliothèque standard seulement (sauf paho-mqtt, optionnel). Léger pour un Zero v1.
"""
import colorsys
import json
import os
import random
import sys
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

OLA_URL = os.environ.get("OLA_URL", "http://127.0.0.1:9090/set_dmx")
UNIVERSE = int(os.environ.get("DMX_UNIVERSE", "1"))
HTTP_PORT = int(os.environ.get("HTTP_PORT", "8080"))
STATE_FILE = os.environ.get("STATE_FILE", "/var/lib/ola-lights/state.json")
MQTT_HOST = os.environ.get("MQTT_HOST", "127.0.0.1")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_BASE = os.environ.get("MQTT_BASE", "lumieres")
# Courbe de gradation. Les décodeurs font du PWM linéaire : la lumière émise suit
# la valeur DMX, alors que l'œil, lui, ne la suit pas. 2.2 rend le curseur
# d'intensité linéaire pour la perception. GAMMA=1 revient à l'ancien comportement.
GAMMA = float(os.environ.get("GAMMA", "2.2"))

# Adresse DMX de départ de chaque décodeur (4 canaux chacun : R, G, B, W inutilisé)
ADDRESSES = [1, 5, 9]
ZONES = len(ADDRESSES)
FRAME_LEN = max(ADDRESSES) + 3  # dernier canal utilisé

BRIGHTNESS_STEP = 10  # pas des boutons - / + et du curseur, en pourcent

lock = threading.Lock()
state = [[0, 0, 0] for _ in range(ZONES)]
brightness = 100  # intensité générale, 0 à 100 %
mqtt_client = None


# ---------------------------------------------------------------- DMX / OLA
def brightness_factor():
    """Facteur appliqué aux couleurs, corrigé pour la perception.

    Le décodeur fait du PWM linéaire : à la valeur DMX 128, le ruban émet bien la
    moitié des photons — mais l'œil y voit environ 73 % de luminosité, pas 50 %.
    D'où l'impression que le haut du curseur ne fait rien et que le bas s'effondre.
    Élever le facteur à la puissance GAMMA corrige ce décalage.

    La correction porte sur le facteur d'intensité, jamais sur les couleurs
    elles-mêmes : le rendu d'une couleur donnée à 100 % reste exactement ce qu'il
    était.
    """
    if brightness >= 100:
        return 1.0
    if brightness <= 0:
        return 0.0
    return (brightness / 100) ** GAMMA


def build_frame():
    """Trame DMX : la couleur de chaque zone, atténuée par l'intensité générale.

    Les décodeurs AKEPO n'ont pas de canal de gradateur maître : l'intensité est
    appliquée ici, en multipliant les valeurs RGB avant l'envoi.
    """
    factor = brightness_factor()
    frame = [0] * FRAME_LEN
    for z, rgb in enumerate(state):
        base = ADDRESSES[z] - 1
        frame[base:base + 3] = [round(c * factor) for c in rgb]
    return frame


def send_dmx():
    """Envoie l'état complet à OLA. Appelé avec le verrou pris."""
    data = urllib.parse.urlencode(
        {"u": UNIVERSE, "d": ",".join(str(v) for v in build_frame())}
    ).encode()
    try:
        urllib.request.urlopen(urllib.request.Request(OLA_URL, data=data), timeout=2).read()
        return True
    except Exception as exc:  # olad absent, réseau, etc.
        print(f"[ola] envoi impossible : {exc}", file=sys.stderr)
        return False


def clamp(v):
    return max(0, min(255, int(v)))


def clamp_percent(v):
    return max(0, min(100, int(v)))


def parse_rgb(value):
    """Accepte '#rrggbb', 'r,g,b', [r,g,b] ou {'r':..,'g':..,'b':..}."""
    if isinstance(value, dict):
        return [clamp(value["r"]), clamp(value["g"]), clamp(value["b"])]
    if isinstance(value, (list, tuple)) and len(value) == 3:
        return [clamp(v) for v in value]
    if isinstance(value, str):
        s = value.strip()
        if s.startswith("{") or s.startswith("["):
            return parse_rgb(json.loads(s))
        if s.startswith("#") and len(s) == 7:
            return [int(s[i:i + 2], 16) for i in (1, 3, 5)]
        parts = s.split(",")
        if len(parts) == 3:
            return [clamp(p) for p in parts]
    raise ValueError(f"couleur invalide : {value!r}")


def set_zones(zone, rgb):
    """zone : index 0..2 ou 'all'."""
    with lock:
        targets = range(ZONES) if zone == "all" else [int(zone)]
        for z in targets:
            if not 0 <= z < ZONES:
                raise ValueError("zone invalide")
            state[z] = list(rgb)
        ok = send_dmx()
        save_state()
        publish_state()
    return ok


def set_brightness(value):
    """Intensité générale. value : 0-100, ou '+'/'-' pour un pas de 10 %."""
    global brightness
    with lock:
        if value == "+":
            brightness = clamp_percent(brightness + BRIGHTNESS_STEP)
        elif value == "-":
            brightness = clamp_percent(brightness - BRIGHTNESS_STEP)
        else:
            brightness = clamp_percent(value)
        ok = send_dmx()
        save_state()
        publish_state()
    return ok


def save_state():
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, "w") as f:
            json.dump({"zones": state, "brightness": brightness}, f)
    except OSError as exc:
        print(f"[état] sauvegarde impossible : {exc}", file=sys.stderr)


def load_state():
    """Relit l'état sauvegardé. Accepte l'ancien format (simple liste de couleurs)."""
    global brightness
    try:
        with open(STATE_FILE) as f:
            saved = json.load(f)
        if isinstance(saved, dict):
            zones = saved["zones"]
            brightness = clamp_percent(saved.get("brightness", 100))
        else:  # ancien format : [[r,g,b], [r,g,b], [r,g,b]]
            zones = saved
        for z in range(ZONES):
            state[z] = [clamp(v) for v in zones[z]]
    except (OSError, ValueError, IndexError, KeyError, TypeError):
        pass


def restore_when_ready():
    """Renvoie la dernière couleur au démarrage (olad peut mettre un moment)."""
    for _ in range(30):
        with lock:
            if send_dmx():
                return
        time.sleep(2)


# ------------------------------------------------------- Routes simples (GET)
# Couleurs utilisables dans les URL : /zone/1/rouge, /all/blue, /zone/2/ff8000 ...
NAMED = {
    "off": (0, 0, 0), "eteint": (0, 0, 0), "noir": (0, 0, 0), "black": (0, 0, 0),
    "rouge": (255, 0, 0), "red": (255, 0, 0),
    "vert": (0, 255, 0), "green": (0, 255, 0),
    "bleu": (0, 0, 255), "blue": (0, 0, 255),
    "blanc": (255, 255, 255), "white": (255, 255, 255),
    "chaud": (255, 180, 100), "warm": (255, 180, 100),
    "ambre": (255, 128, 0), "amber": (255, 128, 0),
    "jaune": (255, 200, 0), "yellow": (255, 200, 0),
    "violet": (128, 0, 255), "purple": (128, 0, 255),
    "rose": (255, 0, 128), "pink": (255, 0, 128),
    "cyan": (0, 255, 255),
}
RANDOM_WORDS = {"random", "aleatoire", "hasard"}


def random_rgb():
    """Couleur vive au hasard (teinte aléatoire, saturation et luminosité au maximum)."""
    r, g, b = colorsys.hsv_to_rgb(random.random(), 1.0, 1.0)
    return [round(r * 255), round(g * 255), round(b * 255)]


def color_from_word(word):
    w = urllib.parse.unquote(word).strip().lower().lstrip("#")
    if w in NAMED:
        return list(NAMED[w])
    if len(w) == 6:
        try:
            return [int(w[i:i + 2], 16) for i in (0, 2, 4)]
        except ValueError:
            pass
    raise ValueError(f"couleur inconnue : {word}")


# Mots acceptés dans /<mot>/<valeur> pour régler l'intensité générale
INTENSITY_WORDS = {"intensite", "intensité", "intensity", "dim"}
UP_WORDS = {"plus", "up", "+"}
DOWN_WORDS = {"moins", "down", "-"}


def intensity_route(word):
    """Gère /intensite/<0-100|plus|moins>. Retourne (code, dict)."""
    w = urllib.parse.unquote(word).strip().lower()
    if w in UP_WORDS:
        value = "+"
    elif w in DOWN_WORDS:
        value = "-"
    else:
        try:
            value = clamp_percent(w.rstrip("%"))
        except ValueError:
            return 400, {"ok": False, "error": f"intensité invalide : {word} (0 à 100, plus ou moins)"}
    ok = set_brightness(value)
    with lock:
        return 200, {"ok": ok, "intensite": brightness, "zones": [hex_of(c) for c in state]}


def simple_route(path):
    """Gère /zone/<1-3|all>/<couleur>, /all/<couleur>, /intensite/<n> et /off."""
    parts = [p for p in path.split("?")[0].split("/") if p]
    if parts == ["off"]:
        parts = ["all", "off"]
    if len(parts) == 2 and urllib.parse.unquote(parts[0]).lower() in INTENSITY_WORDS:
        return intensity_route(parts[1])
    if len(parts) == 2 and parts[0] == "all":
        parts = ["zone", "all", parts[1]]
    if len(parts) != 3 or parts[0] != "zone":
        return None
    zone_name, word = parts[1], parts[2].lower()
    if zone_name == "all":
        zones = list(range(ZONES))
    elif zone_name.isdigit() and 1 <= int(zone_name) <= ZONES:
        zones = [int(zone_name) - 1]
    else:
        return 400, {"ok": False, "error": f"zone invalide : {zone_name} (1 à {ZONES} ou all)"}
    try:
        if word in RANDOM_WORDS:
            colors = {z: random_rgb() for z in zones}  # une couleur différente par zone
        else:
            c = color_from_word(word)
            colors = {z: c for z in zones}
    except ValueError as exc:
        return 400, {"ok": False, "error": str(exc)}
    with lock:
        for z, c in colors.items():
            state[z] = c
        ok = send_dmx()
        save_state()
        publish_state()
        zones_hex = [hex_of(c) for c in state]
        level = brightness
    return 200, {"ok": ok, "zones": zones_hex, "intensite": level}


# --------------------------------------------------------------------- MQTT
def hex_of(rgb):
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def publish_state():
    if mqtt_client is None:
        return
    try:
        for z, rgb in enumerate(state):
            mqtt_client.publish(f"{MQTT_BASE}/zone/{z + 1}/state", hex_of(rgb), retain=True)
        mqtt_client.publish(f"{MQTT_BASE}/intensite/state", str(brightness), retain=True)
    except Exception as exc:
        print(f"[mqtt] publication impossible : {exc}", file=sys.stderr)


def start_mqtt():
    global mqtt_client
    try:
        import paho.mqtt.client as mqtt
    except ImportError:
        print("[mqtt] paho-mqtt absent : MQTT désactivé")
        return
    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1)
    except AttributeError:  # paho 1.x
        client = mqtt.Client()

    def on_connect(c, userdata, flags, rc):
        print(f"[mqtt] connecté (code {rc})")
        c.subscribe(f"{MQTT_BASE}/zone/+/set")
        c.subscribe(f"{MQTT_BASE}/intensite/set")

    def on_message(c, userdata, msg):
        payload = msg.payload.decode()
        try:
            if msg.topic.split("/")[-2] == "intensite":
                p = payload.strip().lower()
                set_brightness(p if p in ("+", "-") else clamp_percent(p.rstrip("%")))
                return
            zone_name = msg.topic.split("/")[-2]
            zone = "all" if zone_name == "all" else int(zone_name) - 1
            set_zones(zone, parse_rgb(payload))
        except Exception as exc:
            print(f"[mqtt] message ignoré ({msg.topic}) : {exc}", file=sys.stderr)

    client.on_connect = on_connect
    client.on_message = on_message
    client.reconnect_delay_set(min_delay=2, max_delay=30)
    try:
        client.connect_async(MQTT_HOST, MQTT_PORT)
        client.loop_start()
        mqtt_client = client
    except Exception as exc:
        print(f"[mqtt] démarrage impossible : {exc}", file=sys.stderr)


# --------------------------------------------------------------------- HTTP
HTML = """<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Lumières</title>
<style>
  :root{color-scheme:dark}
  body{margin:0;padding:16px;font:16px system-ui,sans-serif;background:#111;color:#eee;max-width:520px;margin:auto}
  h1{font-size:20px;margin:0 0 16px}
  .card{background:#1c1c1f;border-radius:14px;padding:14px;margin-bottom:12px;display:flex;align-items:center;gap:14px}
  .card span{flex:1;font-weight:600}
  input[type=color]{width:72px;height:48px;border:0;padding:0;background:none;border-radius:8px}
  .swatch{width:20px;height:20px;border-radius:50%;border:1px solid #444}
  .row{display:flex;flex-wrap:wrap;gap:8px;margin:6px 0 14px}
  button{flex:1 1 30%;padding:12px;border:0;border-radius:10px;background:#2a2a2e;color:#eee;font-size:15px}
  button:active{background:#3a3a40}
  #msg{min-height:20px;color:#e88;font-size:14px}
  .card.col{display:block}
  .dimhead{display:flex;align-items:center;gap:14px;margin-bottom:12px}
  .dimhead span{flex:1;font-weight:600}
  .dimhead output{font-variant-numeric:tabular-nums;color:#aaa;font-size:15px}
  .dimrow{display:flex;align-items:center;gap:12px}
  .dimrow input[type=range]{flex:1;min-width:0;accent-color:#eee;height:32px}
  button.step{flex:0 0 56px;font-size:22px;line-height:1;padding:12px 0}
</style></head><body>
<h1>Lumières</h1>
<div id="zones"></div>
<div class="card"><span>Toutes les zones</span><input type="color" id="all" value="#000000"></div>
<div class="card col">
  <div class="dimhead"><span>Intensité</span><output id="dimval">100 %</output></div>
  <div class="dimrow">
    <button class="step" id="dimdown" aria-label="Baisser de 10 %">−</button>
    <input type="range" id="dim" min="0" max="100" step="10" value="100" aria-label="Intensité">
    <button class="step" id="dimup" aria-label="Monter de 10 %">+</button>
  </div>
</div>
<div class="row" id="scenes"></div>
<div id="msg"></div>
<script>
const N = 3;
const SCENES = [
  ["Éteint","#000000"],["Blanc chaud","#ffb464"],["Blanc","#ffffff"],
  ["Rouge","#ff0000"],["Vert","#00ff00"],["Bleu","#0000ff"],
  ["Ambre","#ff8000"],["Violet","#8000ff"],["Cyan","#00ffff"]
];
const inputs = [];
let last = 0, timer = null;

function send(zone, color){
  fetch("/api/set",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({zone:zone,color:color})})
   .then(r=>r.json()).then(j=>{document.getElementById("msg").textContent=j.ok?"":"OLA injoignable"})
   .catch(()=>{document.getElementById("msg").textContent="Connexion perdue"});
}
function throttled(zone, color){
  const now = Date.now();
  clearTimeout(timer);
  if(now-last>100){last=now;send(zone,color);}
  else timer=setTimeout(()=>{last=Date.now();send(zone,color)},100);
}
const zonesDiv = document.getElementById("zones");
for(let i=0;i<N;i++){
  const card=document.createElement("div");card.className="card";
  card.innerHTML=`<span>Zone ${i+1}</span><input type="color" value="#000000">`;
  const inp=card.querySelector("input");
  inp.addEventListener("input",()=>throttled(i,inp.value));
  inp.addEventListener("change",()=>send(i,inp.value));
  inputs.push(inp);zonesDiv.appendChild(card);
}
const all=document.getElementById("all");
function setAll(c){all.value=c;inputs.forEach(i=>i.value=c);}
all.addEventListener("input",()=>{inputs.forEach(i=>i.value=all.value);throttled("all",all.value)});
all.addEventListener("change",()=>send("all",all.value));
for(const [name,c] of SCENES){
  const b=document.createElement("button");b.textContent=name;
  b.onclick=()=>{setAll(c);send("all",c)};
  document.getElementById("scenes").appendChild(b);
}

// Intensité générale, par pas de 10 %
const dim=document.getElementById("dim"), dimval=document.getElementById("dimval");
let dlast=0, dtimer=null;
function showDim(v){dim.value=v;dimval.textContent=v+" %";}
function sendDim(v){
  fetch("/api/set",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({intensite:v})})
   .then(r=>r.json()).then(j=>{showDim(j.intensite);
     document.getElementById("msg").textContent=j.ok?"":"OLA injoignable"})
   .catch(()=>{document.getElementById("msg").textContent="Connexion perdue"});
}
function throttledDim(v){
  const now=Date.now();
  clearTimeout(dtimer);
  if(now-dlast>100){dlast=now;sendDim(v);}
  else dtimer=setTimeout(()=>{dlast=Date.now();sendDim(v)},100);
}
dim.addEventListener("input",()=>{dimval.textContent=dim.value+" %";throttledDim(+dim.value)});
dim.addEventListener("change",()=>sendDim(+dim.value));
document.getElementById("dimdown").onclick=()=>sendDim("-");
document.getElementById("dimup").onclick=()=>sendDim("+");

fetch("/api/state").then(r=>r.json())
  .then(s=>{s.zones.forEach((c,i)=>inputs[i].value=c);showDim(s.intensite)}).catch(()=>{});
</script></body></html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/":
            self._send(200, HTML, "text/html")
        elif self.path == "/api/state":
            with lock:
                self._send(200, json.dumps(
                    {"zones": [hex_of(c) for c in state], "intensite": brightness}))
        else:
            result = simple_route(self.path)
            if result is None:
                self._send(404, json.dumps({"error": "introuvable"}))
            else:
                code, payload = result
                self._send(code, json.dumps(payload))

    def do_POST(self):
        if self.path != "/api/set":
            return self._send(404, json.dumps({"error": "introuvable"}))
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            if "intensite" in body:
                v = body["intensite"]
                ok = set_brightness(v if v in ("+", "-") else clamp_percent(v))
            else:
                zone = body["zone"]
                zone = "all" if zone == "all" else int(zone)
                ok = set_zones(zone, parse_rgb(body["color"]))
            with lock:
                self._send(200, json.dumps({"ok": ok, "intensite": brightness}))
        except Exception as exc:
            self._send(400, json.dumps({"ok": False, "error": str(exc)}))


def main():
    load_state()
    start_mqtt()
    threading.Thread(target=restore_when_ready, daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0", HTTP_PORT), Handler)
    print(f"[http] page de contrôle sur le port {HTTP_PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
