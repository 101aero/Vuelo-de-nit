#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NIGHT PILOT 64  --  clon en Python (pygame)
===========================================

Recreacion del type-in "Night Pilot 64" de William Fong, publicado en
Commodore Horizons nº 8 (agosto de 1984) para el Commodore 64.

    "El programa representa una avioneta que llega para aterrizar desde
     3500 pies, entorpecida por la oscuridad total."

CONTROLES (como en el original)
    W / X ....... subir / bajar. La PRIMERA pulsacion te nivela,
                  la SEGUNDA cambia la altitud.
    A / D ....... alabear a izquierda / derecha (misma regla).
    + / - ....... velocidad, en incrementos de 5 unidades.
                  Si no tocas nada, baja 1 MPH por segundo.
    ESPACIO ..... bajar / subir el tren de aterrizaje.
    F1 .......... vista de cabina.
    F3 .......... vista de posicion (perfil + planta).
    H ........... ayuda,  P ... pausa,  R ... reiniciar,  ESC ... salir.

DISTANCE es la distancia al centro de la pista. Nivela a buena altura,
inicia un descenso suave, manten el TILT a cero cerca de la pista y baja
el tren antes de tocar. Un pitido avisa si la velocidad o el combustible
son demasiado bajos.

Requisitos:  python3 -m pip install pygame
Ejecucion:   python3 night_pilot.py  [--scale 2] [--mute]

EN ANDROID (Pydroid 3)
    Instala pygame desde el menu Pip de Pydroid y abre este archivo.
    Al detectar Android el juego arranca a pantalla completa y dibuja
    una botonera tactil bajo el panel, con las mismas funciones que el
    teclado. Para probar esa botonera en un ordenador: --touch
    Otras opciones: --no-touch, --fullscreen, --mute, --scale N
"""

import math
import os
import random
import sys
from array import array

import pygame

# ---------------------------------------------------------------------------
# Paleta VIC-II del Commodore 64
# ---------------------------------------------------------------------------
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
RED = (136, 0, 0)
CYAN = (170, 255, 238)
PURPLE = (204, 68, 204)
GREEN = (0, 204, 85)
BLUE = (0, 0, 170)
YELLOW = (238, 238, 119)
ORANGE = (221, 136, 85)
BROWN = (102, 68, 0)
LIGHT_RED = (255, 119, 119)
DARK_GREY = (51, 51, 51)
GREY = (119, 119, 119)
LIGHT_GREEN = (170, 255, 102)
LIGHT_BLUE = (0, 136, 255)
LIGHT_GREY = (187, 187, 187)
BORDER_RED = (198, 38, 24)          # el rojo chillon del borde de la captura

# ---------------------------------------------------------------------------
# Geometria base (se dibuja a 480x300 y se escala con vecino mas proximo)
# ---------------------------------------------------------------------------
BASE_W, BASE_H = 480, 300

WIN_RECT = (58, 20, 364, 112)        # marco blanco de la ventanilla
VIEW_RECT = (92, 32, 296, 88)        # interior negro (lo que se ve fuera)
PANEL_RECT = (58, 140, 364, 150)     # panel de instrumentos

# ---------------------------------------------------------------------------
# Parametros de vuelo
# ---------------------------------------------------------------------------
VS_RATES = {-3: -2400.0, -2: -1200.0, -1: -600.0, 0: 0.0,
            1: 600.0, 2: 1200.0, 3: 2400.0}          # pies/minuto
TILT_DEG = 6.0                 # grados de alabeo por escalon
MAX_TILT = 3
DIST_RATE = 0.0475             # unidades de DISTANCE por MPH y segundo
ALT_SCALE = 1.0 / 25.0         # pies -> unidades del mundo 3D
RWY_HALF_LEN = 55.0            # media longitud de pista (unidades DISTANCE)
RWY_HALF_WID = 16.0            # media anchura de pista
STALL_SPEED = 85.0
MIN_LAND_SPEED = 90.0
MAX_LAND_SPEED = 260.0
MAX_SINK = -750.0              # pies/minuto maximo al tocar
MAX_LAND_OFFSET = 22.0         # desvio lateral maximo al tocar
GLIDE_K = 1.40                 # senda ideal: alt_ideal = distancia * K
# Con estos numeros la senda ideal a 150 MPH pide exactamente -600 pies/min,
# es decir el escalon -1 del mando de altitud, y se toca dentro del limite.


# ===========================================================================
#  Modelo de vuelo  (python puro, sin pygame: se puede probar aparte)
# ===========================================================================
class Flight:
    """Estado y fisica de la avioneta."""

    def __init__(self, level=1, seed=None):
        self.rng = random.Random(seed)
        self.start(level)

    # -- ciclo de vida ------------------------------------------------------
    def start(self, level=1):
        self.level = level
        self.alt = 3500.0                       # pies
        self.dist = 2500.0                      # "km" al centro de la pista
        self.speed = 300.0                      # MPH
        self.vs_idx = 0                         # escalon de ascenso/descenso
        self.tilt_idx = 0                       # escalon de alabeo
        self.lateral = 0.0                      # desvio lateral (unidades)
        self.fuel = max(35.0, 100.0 - (level - 1) * 8.0)
        self.gear = False
        self.state = "fly"                      # fly | landed | crashed
        self.result = ""                        # texto largo del final
        self.score = 0
        self.msg = "GOOD LUCK"
        self.msg_t = 3.0
        self.t = 0.0
        self.warn = ""                          # aviso activo (pitido)
        self.engine = True
        self.wind = self.rng.uniform(-1.0, 1.0) * (0.6 + 0.5 * (level - 1))
        self.gust = 0.0
        self.gust_t = 0.0
        self.touch_vs = 0.0                     # datos del momento de tocar
        self.touch_speed = 0.0
        self.touch_tilt = 0
        self.touch_lateral = 0.0

    # -- entradas del jugador ----------------------------------------------
    def pitch_up(self):
        """W: la primera pulsacion nivela, la segunda hace ascender."""
        if self.state != "fly":
            return
        self.vs_idx = 0 if self.vs_idx < 0 else min(3, self.vs_idx + 1)

    def pitch_down(self):
        """X: la primera pulsacion nivela, la segunda hace descender."""
        if self.state != "fly":
            return
        self.vs_idx = 0 if self.vs_idx > 0 else max(-3, self.vs_idx - 1)

    def tilt_left(self):
        if self.state != "fly":
            return
        self.tilt_idx = 0 if self.tilt_idx > 0 else max(-MAX_TILT, self.tilt_idx - 1)

    def tilt_right(self):
        if self.state != "fly":
            return
        self.tilt_idx = 0 if self.tilt_idx < 0 else min(MAX_TILT, self.tilt_idx + 1)

    def throttle(self, delta):
        if self.state != "fly" or not self.engine:
            return
        self.speed = max(0.0, min(600.0, self.speed + delta))

    def toggle_gear(self):
        if self.state != "fly":
            return
        self.gear = not self.gear
        self.flash("GEAR DOWN" if self.gear else "GEAR UP")

    # -- utilidades ---------------------------------------------------------
    def flash(self, text, secs=2.5):
        self.msg = text
        self.msg_t = secs

    @property
    def vs(self):
        """Velocidad vertical en pies/minuto."""
        return VS_RATES[self.vs_idx]

    @property
    def tilt_angle(self):
        return self.tilt_idx * TILT_DEG

    @property
    def ideal_alt(self):
        return max(0.0, self.dist) * GLIDE_K

    def glide_hint(self):
        if self.dist > 2000:
            return "CRUISE"
        d = self.alt - self.ideal_alt
        if d > 400:
            return "HIGH"
        if d < -400:
            return "LOW"
        return "ON PATH"

    # -- fisica -------------------------------------------------------------
    def update(self, dt):
        if self.state != "fly":
            return
        self.t += dt
        if self.msg_t > 0:
            self.msg_t -= dt

        # --- combustible ---------------------------------------------------
        if self.engine:
            self.fuel -= (0.10 + self.speed / 3000.0) * dt
            if self.fuel <= 0.0:
                self.fuel = 0.0
                self.engine = False
                self.flash("FUEL OUT!", 4.0)

        # --- velocidad -----------------------------------------------------
        self.speed -= 1.0 * dt                      # rozamiento del original
        if self.gear:
            self.speed -= 2.0 * dt                  # resistencia del tren
        if not self.engine:
            self.speed -= 2.5 * dt
            if self.vs_idx > -1:                    # sin motor solo se planea
                self.vs_idx = -1
        # subir cuesta velocidad, bajar la regala
        self.speed -= self.vs * 0.004 * dt
        self.speed = max(0.0, min(600.0, self.speed))

        # --- perdida -------------------------------------------------------
        if self.speed < STALL_SPEED:
            self.vs_idx = -3
            self.warn = "STALL!"
        elif self.fuel < 15.0 and self.engine:
            self.warn = "LOW FUEL"
        elif self.speed < 120.0:
            self.warn = "LOW SPEED"
        elif self.speed > 520.0:
            self.warn = "OVERSPEED"
        elif self.alt < 900.0 and not self.gear:
            self.warn = "GEAR UP!"
        else:
            self.warn = ""

        # --- altitud -------------------------------------------------------
        self.alt += self.vs * dt / 60.0
        self.alt = min(self.alt, 20000.0)

        # --- avance y deriva lateral ---------------------------------------
        self.dist -= self.speed * DIST_RATE * dt
        self.gust_t -= dt
        if self.gust_t <= 0.0:
            self.gust_t = self.rng.uniform(2.0, 6.0)
            self.gust = self.rng.uniform(-1.0, 1.0) * (0.8 + 0.6 * (self.level - 1))
        drift = self.tilt_idx * 5.0 * (self.speed / 300.0) + self.wind + self.gust
        self.lateral += drift * dt

        # --- final ---------------------------------------------------------
        if self.alt <= 0.0:
            self.alt = 0.0
            self._touchdown()
        elif self.dist < -220.0:
            self._crash("HAS SOBREPASADO LA PISTA",
                        "Pasaste de largo sin llegar a tocar tierra.")
        elif abs(self.lateral) > 400.0:
            self._crash("PERDIDO EN LA NOCHE",
                        "Te has desviado demasiado del eje de la pista.")

    # -- toma de tierra -----------------------------------------------------
    def _touchdown(self):
        self.touch_vs = self.vs
        self.touch_speed = self.speed
        self.touch_tilt = self.tilt_idx
        self.touch_lateral = self.lateral

        on_runway = (-RWY_HALF_LEN <= self.dist <= RWY_HALF_LEN
                     and abs(self.lateral) <= MAX_LAND_OFFSET)
        if not on_runway:
            self._crash("TE HAS ESTRELLADO EN LA OSCURIDAD",
                        "Tocaste tierra fuera de la pista "
                        "(DISTANCE %d, desvio %d)." % (self.dist, self.lateral))
            return
        if not self.gear:
            self._crash("SIN TREN DE ATERRIZAJE",
                        "Aterrizaje de panza: el tren seguia recogido.")
            return
        if self.vs < MAX_SINK:
            self._crash("DESCENSO DEMASIADO BRUSCO",
                        "Bajabas a %d pies/min; el maximo son %d."
                        % (self.vs, MAX_SINK))
            return
        if abs(self.tilt_idx) > 1:
            self._crash("UN ALA HA TOCADO LA PISTA",
                        "Tocaste con el avion inclinado (TILT %+d)." % self.tilt_idx)
            return
        if self.speed > MAX_LAND_SPEED:
            self._crash("DEMASIADA VELOCIDAD",
                        "Tocaste a %d MPH; el maximo son %d MPH."
                        % (self.speed, MAX_LAND_SPEED))
            return
        if self.speed < MIN_LAND_SPEED:
            self._crash("ENTRASTE EN PERDIDA",
                        "Tocaste a %d MPH, por debajo de %d MPH."
                        % (self.speed, MIN_LAND_SPEED))
            return

        # --- aterrizaje valido: se puntua la finura -------------------------
        self.state = "landed"
        smooth = max(0.0, 1.0 + self.vs / 700.0)             # 1.0 = posado suave
        centred = max(0.0, 1.0 - abs(self.lateral) / MAX_LAND_OFFSET)
        stopped = max(0.0, 1.0 - abs(self.speed - 140.0) / 160.0)
        level = 1.0 if self.tilt_idx == 0 else 0.5
        self.score = int(600 + 900 * smooth * level
                         + 500 * centred + 300 * stopped + 4 * self.fuel)
        if smooth > 0.75 and centred > 0.7 and self.tilt_idx == 0:
            self.flash("PERFECT!", 6.0)
            self.result = "Aterrizaje de manual: suave, centrado y nivelado."
        else:
            self.flash("LANDED OK", 6.0)
            self.result = "En la pista de una pieza. Mejorable, pero valido."

    def _crash(self, title, detail):
        if self.touch_speed == 0.0:          # choque sin llegar a tocar pista
            self.touch_vs = self.vs
            self.touch_speed = self.speed
            self.touch_tilt = self.tilt_idx
            self.touch_lateral = self.lateral
        self.state = "crashed"
        self.msg = "CRASH!"
        self.msg_t = 9.9
        self.result = detail
        self.crash_title = title

    # -- texto del final ----------------------------------------------------
    def end_title(self):
        if self.state == "landed":
            return "HAS ATERRIZADO"
        return getattr(self, "crash_title", "TE HAS ESTRELLADO")


# ===========================================================================
#  Sonido  (ondas generadas a mano, sin numpy)
# ===========================================================================
class Audio:
    RATE = 22050

    def __init__(self, enabled=True):
        self.ok = False
        self.enabled = enabled
        self.engine_ch = None
        self.engine_freq = -1
        self.beep_t = 0.0
        if not enabled:
            return
        try:
            pygame.mixer.pre_init(self.RATE, -16, 1, 512)
            pygame.mixer.init()
            self.channels = pygame.mixer.get_init()[2] if pygame.mixer.get_init() else 1
            self.engine_ch = pygame.mixer.Channel(0)
            self.ok = True
        except Exception:
            self.ok = False

    # -- generadores --------------------------------------------------------
    def _sound(self, samples):
        buf = array("h", samples)
        if getattr(self, "channels", 1) == 2:
            st = array("h")
            for v in buf:
                st.append(v)
                st.append(v)
            buf = st
        return pygame.mixer.Sound(buffer=buf.tobytes())

    def _tone(self, freq, ms, vol=0.3, wave="square", envelope=True):
        n = int(self.RATE * ms / 1000.0)
        amp = int(32767 * vol)
        period = self.RATE / float(freq)
        out = []
        for i in range(n):
            ph = (i % period) / period
            if wave == "square":
                v = amp if ph < 0.5 else -amp
            elif wave == "saw":
                v = int(amp * (2.0 * ph - 1.0))
            else:
                v = int(amp * math.sin(2.0 * math.pi * ph))
            if envelope:            # evita chasquidos en los sonidos sueltos
                if i < 200:
                    v = int(v * i / 200.0)
                if n - i < 200:
                    v = int(v * (n - i) / 200.0)
            out.append(v)
        return self._sound(out)

    def _noise(self, ms, vol=0.35):
        n = int(self.RATE * ms / 1000.0)
        amp = int(32767 * vol)
        rng = random.Random(7)
        out = []
        for i in range(n):
            env = 1.0 - i / float(n)
            out.append(int(rng.uniform(-amp, amp) * env * env))
        return self._sound(out)

    # -- efectos ------------------------------------------------------------
    def engine(self, speed, running):
        if not self.ok:
            return
        if not running:
            if self.engine_ch.get_busy():
                self.engine_ch.stop()
            self.engine_freq = -1
            return
        freq = int(45 + speed * 0.25)
        if abs(freq - self.engine_freq) >= 3 or not self.engine_ch.get_busy():
            self.engine_freq = freq
            try:
                # numero entero de ciclos: el bucle empalma sin chasquido
                cycles = max(4, int(freq * 0.12))
                ms = 1000.0 * cycles / freq
                snd = self._tone(freq, ms, vol=0.16, wave="saw", envelope=False)
                self.engine_ch.play(snd, loops=-1)
            except Exception:
                self.ok = False

    def warn_beep(self, active, dt):
        if not self.ok:
            return
        if not active:
            self.beep_t = 0.0
            return
        self.beep_t -= dt
        if self.beep_t <= 0.0:
            self.beep_t = 0.55
            try:
                self._tone(880, 110, vol=0.25).play()
            except Exception:
                pass

    def crash(self):
        if not self.ok:
            return
        try:
            self.engine_ch.stop()
            self._noise(900, 0.45).play()
        except Exception:
            pass

    def success(self):
        """Arpegio de aterrizaje, en un solo sonido para no frenar el bucle."""
        if not self.ok:
            return
        try:
            self.engine_ch.stop()
            samples = []
            for freq in (523, 659, 784, 1047):
                n = int(self.RATE * 0.16)
                amp = int(32767 * 0.22)
                period = self.RATE / float(freq)
                for i in range(n):
                    v = amp if (i % period) / period < 0.5 else -amp
                    if i < 200:
                        v = int(v * i / 200.0)
                    if n - i < 400:
                        v = int(v * (n - i) / 400.0)
                    samples.append(v)
            self._sound(samples).play()
        except Exception:
            pass


# ===========================================================================
#  Dibujo
# ===========================================================================
def load_mono(size):
    """Fuente monoespaciada: primero una junto al script (para el APK, donde
    Android no tiene ninguna), luego las del sistema, luego la de pygame."""
    here = os.path.dirname(os.path.abspath(__file__))
    for name in ("DejaVuSansMono.ttf", os.path.join("assets", "DejaVuSansMono.ttf")):
        path = os.path.join(here, name)
        if os.path.exists(path):
            try:
                return pygame.font.Font(path, size)
            except Exception:
                break
    for name in ("dejavusansmono", "liberationmono", "couriernew",
                 "freemono", "consolas", "menlo", "monospace", "couriernewpsmt"):
        path = pygame.font.match_font(name)
        if path:
            return pygame.font.Font(path, size)
    return pygame.font.Font(None, size)


class Fonts:
    def __init__(self):
        self.tiny = load_mono(9)
        self.small = load_mono(11)
        self.read = load_mono(14)
        self.big = load_mono(20)
        self.fw = self.read.size("M")[0]


def txt(surf, font, s, x, y, color):
    surf.blit(font.render(s, False, color), (x, y))


def txt_right(surf, font, s, x_right, y, color):
    img = font.render(s, False, color)
    surf.blit(img, (x_right - img.get_width(), y))


def txt_center(surf, font, s, cx, y, color):
    img = font.render(s, False, color)
    surf.blit(img, (cx - img.get_width() // 2, y))


# --- estrellas fijas del cielo (azimut, elevacion en radianes) --------------
FOCAL = 340.0                    # distancia focal en pixeles (campo de ~47 grados)
_rng = random.Random(1984)
STARS = [(_rng.uniform(-0.40, 0.40), _rng.uniform(0.005, 0.13)) for _ in range(26)]
BEACON = (0.27, 0.085)


def project(flight, px, pz, py=0.0):
    """Proyecta un punto del mundo (x lateral, z a lo largo, y altura) a pixeles.

    Devuelve (x, y, fz) o None si queda detras del avion.
    """
    fz = pz + flight.dist
    if fz < 3.0:
        return None
    focal = FOCAL
    sx = focal * (px - flight.lateral) / fz
    sy = focal * (flight.alt * ALT_SCALE - py) / fz
    a = math.radians(flight.tilt_angle)
    ca, sa = math.cos(a), math.sin(a)
    rx = sx * ca - sy * sa
    ry = sx * sa + sy * ca
    vx, vy, vw, vh = VIEW_RECT
    cx = vx + vw / 2.0
    cy = vy + vh / 2.0 + flight.vs / 150.0
    return (cx + rx, cy + ry, fz)


def draw_night_view(surf, flight, fonts, t):
    """Lo que se ve por la ventanilla: oscuridad total y luces de pista."""
    vx, vy, vw, vh = VIEW_RECT
    view = pygame.Rect(vx, vy, vw, vh)
    surf.fill(BLACK, view)
    prev_clip = surf.get_clip()
    surf.set_clip(view)

    a = math.radians(flight.tilt_angle)
    ca, sa = math.cos(a), math.sin(a)
    cx = vx + vw / 2.0
    cy = vy + vh / 2.0 + flight.vs / 150.0

    def sky(az, el, color, size):
        sx = FOCAL * math.tan(az)
        sy = -FOCAL * math.tan(el)
        x = cx + sx * ca - sy * sa
        y = cy + sx * sa + sy * ca
        if view.collidepoint(int(x), int(y)):
            pygame.draw.rect(surf, color, (int(x), int(y), size, size))

    for az, el in STARS:
        sky(az, el, GREY if (int(t * 2) + int(az * 100)) % 7 else LIGHT_GREY, 1)
    if int(t * 2) % 4 != 3:                     # baliza que parpadea
        sky(BEACON[0], BEACON[1], YELLOW, 2)

    # ---- la pista, trazada en perspectiva (los trazos azules del original)
    near = project(flight, 0.0, -RWY_HALF_LEN)
    far_thr = near[2] if near else 1e9

    def seg(x1, z1, x2, z2, color, width=1):
        a1 = project(flight, x1, z1)
        a2 = project(flight, x2, z2)
        if a1 and a2:
            pygame.draw.line(surf, color, (int(a1[0]), int(a1[1])),
                             (int(a2[0]), int(a2[1])), width)

    edge_col = LIGHT_BLUE if far_thr > 260 else WHITE
    seg(-RWY_HALF_WID, -RWY_HALF_LEN, -RWY_HALF_WID, RWY_HALF_LEN, edge_col)
    seg(RWY_HALF_WID, -RWY_HALF_LEN, RWY_HALF_WID, RWY_HALF_LEN, edge_col)
    seg(-RWY_HALF_WID, -RWY_HALF_LEN, RWY_HALF_WID, -RWY_HALF_LEN, GREEN)
    seg(-RWY_HALF_WID, RWY_HALF_LEN, RWY_HALF_WID, RWY_HALF_LEN, LIGHT_RED)
    # rampa de aproximacion
    seg(0.0, -RWY_HALF_LEN - 130.0, 0.0, -RWY_HALF_LEN, BLUE)

    points = []          # (px, pz, altura, color, tamano base)

    # luces de aproximacion
    for k in range(1, 9):
        z = -RWY_HALF_LEN - k * 15.0
        points.append((0.0, z, 0.0, LIGHT_BLUE, 3.4))
        if k % 3 == 0:
            points.append((-5.0, z, 0.0, LIGHT_BLUE, 2.8))
            points.append((5.0, z, 0.0, LIGHT_BLUE, 2.8))

    # umbral (verde) y final de pista (rojo)
    for i in range(-2, 3):
        points.append((i * RWY_HALF_WID / 2.0, -RWY_HALF_LEN, 0.0, GREEN, 3.0))
        points.append((i * RWY_HALF_WID / 2.0, RWY_HALF_LEN, 0.0, LIGHT_RED, 3.0))

    # luces de borde
    n = 11
    for i in range(n + 1):
        z = -RWY_HALF_LEN + 2.0 * RWY_HALF_LEN * i / n
        col = WHITE if i % 2 == 0 else YELLOW
        points.append((-RWY_HALF_WID, z, 0.0, col, 3.2))
        points.append((RWY_HALF_WID, z, 0.0, col, 3.2))

    # eje de pista
    for i in range(0, 11):
        z = -RWY_HALF_LEN + 2.0 * RWY_HALF_LEN * i / 10.0
        points.append((0.0, z, 0.0, GREY, 2.4))

    for px, pz, py, col, base in points:
        pr = project(flight, px, pz, py)
        if pr is None:
            continue
        x, y, fz = pr
        if not view.collidepoint(int(x), int(y)):
            continue
        size = max(1, int(base * 120.0 / fz))
        size = min(size, 6)
        pygame.draw.rect(surf, col, (int(x) - size // 2, int(y) - size // 2, size, size))

    if flight.state == "crashed" and int(t * 6) % 2 == 0:
        surf.fill(LIGHT_RED, view)
    surf.set_clip(prev_clip)


def draw_window_frame(surf):
    """Marco blanco de la ventanilla, con los montantes punteados."""
    wx, wy, ww, wh = WIN_RECT
    pygame.draw.rect(surf, WHITE, (wx, wy, ww, wh))
    vx, vy, vw, vh = VIEW_RECT
    pygame.draw.rect(surf, BLACK, (vx, vy, vw, vh))
    # esquinas achaflanadas del cristal
    for dx, dy in ((0, 0), (1, 0), (0, 1), (1, 1)):
        x = vx - 6 if dx == 0 else vx + vw - 2
        y = vy - 6 if dy == 0 else vy + vh - 2
        pygame.draw.rect(surf, WHITE, (x, y, 8, 8))
    pygame.draw.line(surf, BLACK, (vx - 6, vy + 2), (vx + 2, vy - 6))
    pygame.draw.line(surf, BLACK, (vx + vw + 4, vy - 6), (vx + vw - 4, vy + 2))
    pygame.draw.line(surf, BLACK, (vx - 6, vy + vh - 2), (vx + 2, vy + vh + 6))
    pygame.draw.line(surf, BLACK, (vx + vw + 4, vy + vh + 6), (vx + vw - 4, vy + vh - 2))
    # montantes punteados
    for cx in (wx + 14, wx + ww - 15):
        for i in range(9):
            pygame.draw.rect(surf, BLACK, (cx, wy + 12 + i * 11, 2, 5))


def dot_row(surf, x, y, pattern, t, seed=0):
    """Fila decorativa de testigos, como los del panel original."""
    for i, (col, filled) in enumerate(pattern):
        cx = x + i * 9
        blink = ((int(t * 1.7) + seed + i * 3) % 5) != 0
        c = col if (filled or blink) else DARK_GREY
        if filled:
            pygame.draw.rect(surf, c, (cx + 1, y + 1, 4, 4))
        else:
            pygame.draw.circle(surf, c, (cx + 3, y + 3), 3, 1)


def draw_panel(surf, flight, fonts, t):
    px, py, pw, ph = PANEL_RECT
    pygame.draw.rect(surf, BLACK, (px, py, pw, ph))
    pygame.draw.rect(surf, BLACK, (px - 4, py + 8, pw + 8, ph - 16))
    pygame.draw.rect(surf, BORDER_RED, (px, py, 10, 8))
    pygame.draw.rect(surf, BORDER_RED, (px + pw - 10, py, 10, 8))

    # ---------------- indicador ALT ---------------------------------------
    ax, ay, aw, ah = px + 8, py + 6, 46, 40
    pygame.draw.rect(surf, WHITE, (ax, ay, aw, ah), 2)
    txt(surf, fonts.small, "ALT", ax + 5, ay + 3, WHITE)
    pygame.draw.line(surf, WHITE, (ax + 5, ay + 26), (ax + aw - 6, ay + 26), 1)
    txt(surf, fonts.tiny, "-", ax + 5, ay + 27, WHITE)
    txt(surf, fonts.tiny, "+", ax + aw - 12, ay + 27, WHITE)
    mid = ax + aw / 2.0
    mx = int(mid + flight.vs_idx * (aw / 2.0 - 8) / 3.0)
    pygame.draw.rect(surf, CYAN, (mx - 2, ay + 22, 5, 9))

    # ---------------- indicador TILT --------------------------------------
    tx, ty, tw, th = px + 8, py + 56, 46, 42
    pygame.draw.rect(surf, WHITE, (tx, ty, tw, th), 2)
    pygame.draw.line(surf, PURPLE, (tx + 6, ty + th // 2), (tx + tw - 7, ty + th // 2), 1)
    cxp = tx + tw / 2.0
    mx = int(cxp + flight.tilt_idx * (tw / 2.0 - 8) / MAX_TILT)
    pygame.draw.rect(surf, PURPLE, (mx - 3, ty + th // 2 - 4, 7, 9))
    pygame.draw.rect(surf, LIGHT_RED, (mx - 1, ty + th // 2 - 2, 3, 5))
    txt(surf, fonts.small, "TILT", tx + 7, ty + th + 2, WHITE)

    # ---------------- testigos decorativos --------------------------------
    gx = px + 62
    dot_row(surf, gx, py + 10, [(WHITE, False)] * 3 + [(WHITE, True), (WHITE, False)], t, 1)
    dot_row(surf, gx, py + 22, [(LIGHT_RED, True)] * 3 + [(PURPLE, True)] * 3, t, 2)
    dot_row(surf, gx - 4, py + 40, [(YELLOW, False), (YELLOW, False), (ORANGE, True),
                                    (ORANGE, True), (GREEN, False), (GREEN, True),
                                    (GREEN, True), (ORANGE, False)], t, 3)
    dot_row(surf, gx, py + 62, [(GREEN, False), (WHITE, True), (WHITE, True),
                                (GREEN, False), (GREEN, False)], t, 4)
    dot_row(surf, gx, py + 78, [(WHITE, True), (GREEN, True), (WHITE, False)], t, 5)
    dot_row(surf, gx, py + 94, [(WHITE, False)] * 5, t, 6)

    # ---------------- combustible -----------------------------------------
    fx, fy, fw_, fh_ = px + 140, py + 4, 16, 96
    pygame.draw.rect(surf, PURPLE, (fx, fy, fw_, fh_), 2)
    lvl = max(0.0, min(1.0, flight.fuel / 100.0))
    h = int((fh_ - 6) * lvl)
    col = YELLOW if flight.fuel > 15 else LIGHT_RED
    if flight.fuel <= 15 and int(t * 3) % 2 == 0:
        col = BLACK
    pygame.draw.rect(surf, col, (fx + 3, fy + fh_ - 3 - h, fw_ - 6, h))
    for i, ch in enumerate("FUEL"):
        txt(surf, fonts.small, ch, fx + fw_ + 4, fy + 8 + i * 12, GREEN)
    dot_row(surf, fx + fw_ + 18, fy + 14, [(GREEN, False), (GREEN, False)], t, 7)
    dot_row(surf, fx + fw_ + 18, fy + 40, [(GREEN, False)], t, 8)
    dot_row(surf, fx + fw_ + 14, fy + 60, [(PURPLE, True), (WHITE, False)], t, 9)

    # ---------------- titulo y mensaje ------------------------------------
    rx = px + 192
    txt(surf, fonts.read, "NIGHT PILOT:", rx + 20, py + 4, WHITE)
    box = pygame.Rect(rx + 20, py + 20, 146, 32)
    pygame.draw.rect(surf, YELLOW, box, 2)
    if flight.msg_t > 0 or flight.state != "fly":
        colour = LIGHT_RED if flight.state == "crashed" else YELLOW
        txt_center(surf, fonts.read, flight.msg, box.centerx, box.y + 9, colour)
    elif flight.warn and int(t * 3) % 2 == 0:
        txt_center(surf, fonts.read, flight.warn, box.centerx, box.y + 9, LIGHT_RED)

    # ---------------- ordenador -------------------------------------------
    txt(surf, fonts.read, "COMPUTER", rx + 38, py + 56, CYAN)
    lights = [
        flight.gear, flight.engine, flight.speed >= 120, flight.fuel > 15,
        abs(flight.tilt_idx) == 0, flight.vs_idx <= 0,
        flight.glide_hint() == "ON PATH", flight.dist < 600,
    ]
    for i, on in enumerate(lights):
        c = LIGHT_GREEN if on else WHITE
        if flight.warn and i in (2, 3) and int(t * 4) % 2 == 0:
            c = LIGHT_RED
        cxl, cyl = rx + 9 + i * 20, py + 78
        if on:
            pygame.draw.circle(surf, c, (cxl, cyl), 5)
        else:
            pygame.draw.circle(surf, c, (cxl, cyl), 5, 1)

    # ---------------- lecturas numericas ----------------------------------
    y = py + 88
    right = px + pw - 8
    rows = [
        ("ALTITUDE  FT :", "%d" % round(flight.alt), CYAN),
        ("DISTANCE  KM :", "%d" % round(flight.dist), WHITE),
        ("UNDERCARRIAGE:", "DOWN" if flight.gear else "UP", GREEN),
        ("SPEED    MPH :", "%d" % round(flight.speed), LIGHT_RED),
    ]
    for label, value, col in rows:
        txt(surf, fonts.read, label, rx + 2, y, col)
        txt_right(surf, fonts.read, value, right, y, ORANGE)
        y += 15


def draw_map(surf, flight, fonts, t):
    """Vista F3: perfil vertical y planta, para saber donde estas."""
    surf.fill(BLACK)
    txt(surf, fonts.read, "POSITION -- F1 = COCKPIT", 14, 6, CYAN)

    # ---------------- perfil (altitud frente a distancia) ------------------
    L, R = 30, BASE_W - 24
    TOP, GND = 40, 136

    def mx(d):
        return L + (R - L) * (2700.0 - d) / 3000.0

    def my(a):
        return GND - (GND - TOP) * min(a, 4200.0) / 4200.0

    pygame.draw.line(surf, GREY, (L, GND), (R, GND), 1)
    txt(surf, fonts.tiny, "PERFIL", L, TOP - 11, GREY)
    # senda ideal
    for d in range(0, 2700, 55):
        pygame.draw.rect(surf, DARK_GREY, (int(mx(d)), int(my(d * GLIDE_K)), 2, 2))
    # pista
    rw_l, rw_r = int(mx(RWY_HALF_LEN)), int(mx(-RWY_HALF_LEN))
    pygame.draw.rect(surf, WHITE, (rw_l, GND - 2, max(3, rw_r - rw_l), 3))
    pygame.draw.rect(surf, GREEN, (rw_l - 2, GND - 7, 3, 6))
    pygame.draw.rect(surf, LIGHT_RED, (rw_r, GND - 7, 3, 6))
    # avion
    ax, ay = int(mx(flight.dist)), int(my(flight.alt))
    pygame.draw.polygon(surf, YELLOW, [(ax + 7, ay), (ax - 5, ay - 4), (ax - 5, ay + 4)])
    pygame.draw.line(surf, ORANGE, (ax - 1, ay - 4), (ax - 1, ay + 4), 1)
    txt(surf, fonts.tiny, "%d FT" % round(flight.alt), ax - 10, ay - 15, CYAN)

    hint = flight.glide_hint()
    hcol = {"HIGH": ORANGE, "LOW": LIGHT_RED, "ON PATH": LIGHT_GREEN}.get(hint, CYAN)
    txt_right(surf, fonts.read, "GLIDE: " + hint, R, TOP - 16, hcol)

    # ---------------- planta (alineacion con el eje) -----------------------
    TOP2, BOT2 = 170, 268
    cx = BASE_W // 2
    txt(surf, fonts.tiny, "EJE DE PISTA", L, TOP2 - 11, GREY)

    def py_(d):
        return TOP2 + (BOT2 - TOP2) * (900.0 - max(-200.0, min(900.0, d))) / 1100.0

    def px_(lat):
        return cx + max(-64.0, min(64.0, lat)) * 3.0

    pygame.draw.line(surf, DARK_GREY, (cx, TOP2), (cx, BOT2), 1)
    for lat in (-60, -30, 30, 60):
        x = int(px_(lat))
        pygame.draw.rect(surf, DARK_GREY, (x, BOT2 - 3, 1, 4))
    rw_top, rw_bot = int(py_(RWY_HALF_LEN)), int(py_(-RWY_HALF_LEN))
    pygame.draw.rect(surf, WHITE,
                     (int(px_(-RWY_HALF_WID)), rw_top,
                      int(px_(RWY_HALF_WID) - px_(-RWY_HALF_WID)),
                      max(3, rw_bot - rw_top)), 1)
    pygame.draw.line(surf, GREEN, (int(px_(-RWY_HALF_WID)), rw_top),
                     (int(px_(RWY_HALF_WID)), rw_top), 1)
    for k in range(1, 9):       # luces de aproximacion, antes del umbral
        pygame.draw.rect(surf, LIGHT_BLUE,
                         (cx - 1, int(py_(RWY_HALF_LEN + k * 15.0)), 2, 2))

    bx, by = int(px_(flight.lateral)), int(py_(flight.dist))
    pygame.draw.polygon(surf, YELLOW, [(bx, by + 6), (bx - 5, by - 5), (bx + 5, by - 5)])
    pygame.draw.line(surf, ORANGE, (bx - 7, by - 1), (bx + 7, by - 1), 1)
    ok = abs(flight.lateral) <= MAX_LAND_OFFSET
    txt(surf, fonts.tiny, "DESVIO %+d" % round(flight.lateral), bx + 10, by - 4,
        LIGHT_GREEN if ok else LIGHT_RED)
    if flight.dist > 900:
        txt(surf, fonts.tiny, "(A %d DE DISTANCIA)" % round(flight.dist),
            cx + 46, TOP2 + 2, DARK_GREY)

    # datos en la esquina
    txt(surf, fonts.read, "DIST %5d   SPD %3d   V/S %+5d   FUEL %2d%%"
        % (round(flight.dist), round(flight.speed), flight.vs, round(flight.fuel)),
        14, BASE_H - 16, CYAN)


HELP_LINES = [
    "W / X ..... SUBIR / BAJAR",
    "            1a pulsacion nivela,",
    "            2a cambia la altitud",
    "A / D ..... ALABEO IZQUIERDA / DERECHA",
    "+ / - ..... VELOCIDAD (de 5 en 5)",
    "ESPACIO ... TREN DE ATERRIZAJE",
    "F1 / F3 ... CABINA / POSICION",
    "P ......... PAUSA",
    "R ......... REINICIAR",
    "H ......... AYUDA          ESC ... SALIR",
    "En movil: usa los botones de abajo.",
    "",
    "Nivela alto, desciende suave, manten el",
    "TILT a cero cerca de la pista y baja el",
    "tren antes de tocar. DISTANCE es lo que",
    "falta hasta el centro de la pista.",
]


def draw_help(surf, fonts, t=0.0):
    box = pygame.Rect(28, 24, BASE_W - 56, BASE_H - 56)
    pygame.draw.rect(surf, BLACK, box)
    pygame.draw.rect(surf, CYAN, box, 2)
    txt_center(surf, fonts.read, "NIGHT PILOT 64", box.centerx, box.y + 8, YELLOW)
    txt_center(surf, fonts.small, "William Fong -- Commodore Horizons, 1984",
               box.centerx, box.y + 24, GREY)
    y = box.y + 44
    left = box.x + 22
    for line in HELP_LINES:
        col = CYAN if line.startswith("  ") else WHITE
        txt(surf, fonts.small, line, left, y, col)
        y += 12
    if int(t * 2) % 2 == 0:
        txt_center(surf, fonts.small, "PULSA UNA TECLA PARA VOLAR",
                   box.centerx, box.y + box.h - 16, LIGHT_GREEN)


def wrap(text, width):
    """Parte un texto en lineas de como mucho `width` caracteres."""
    lines, cur = [], ""
    for word in text.split():
        if len(cur) + len(word) + (1 if cur else 0) <= width:
            cur = (cur + " " + word).strip()
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def draw_end(surf, flight, fonts, t):
    landed = flight.state == "landed"
    col = LIGHT_GREEN if landed else LIGHT_RED
    lines = wrap(flight.result, 42)[:3]
    h = 84 + 13 * len(lines)
    box = pygame.Rect(44, (BASE_H - h) // 2, BASE_W - 88, h)
    pygame.draw.rect(surf, BLACK, box)
    pygame.draw.rect(surf, col, box, 2)

    y = box.y + 10
    txt_center(surf, fonts.read, flight.end_title(), box.centerx, y, col)
    y += 22
    for line in lines:
        txt_center(surf, fonts.small, line, box.centerx, y, WHITE)
        y += 13
    y += 6
    if landed:
        txt_center(surf, fonts.read, "SCORE %d" % flight.score, box.centerx, y, YELLOW)
        nxt = "N = SIGUIENTE NIVEL   R = REPETIR"
    else:
        txt_center(surf, fonts.small, "V/S %+d   SPD %d   TILT %+d   DESVIO %+d"
                   % (flight.touch_vs, flight.touch_speed,
                      flight.touch_tilt, flight.touch_lateral),
                   box.centerx, y, ORANGE)
        nxt = "R = OTRO INTENTO   ESC = SALIR"
    if int(t * 2) % 2 == 0:
        txt_center(surf, fonts.small, nxt, box.centerx, box.y + h - 18, CYAN)


def draw_frame(surf, flight, fonts, t, view_mode, paused, show_help):
    surf.fill(BORDER_RED)
    if view_mode == "map":
        draw_map(surf, flight, fonts, t)
    else:
        draw_window_frame(surf)
        draw_night_view(surf, flight, fonts, t)
        draw_panel(surf, flight, fonts, t)
    if flight.state != "fly":
        draw_end(surf, flight, fonts, t)
    elif paused:
        txt_center(surf, fonts.big, "PAUSA", BASE_W // 2, BASE_H // 2 - 10, YELLOW)
    if show_help:
        draw_help(surf, fonts, t)


# ===========================================================================
#  Controles tactiles (Android / Pydroid 3)
# ===========================================================================
ANDROID = hasattr(sys, "getandroidapilevel") or "ANDROID_ARGUMENT" in os.environ

TOUCH_ROWS = [
    [("SUBIR", "up"), ("BAJAR", "down"), ("IZQ", "left"),
     ("DER", "right"), ("VISTA", "view"), ("AYUDA", "help")],
    [("+5", "faster"), ("-5", "slower"), ("TREN", "gear"),
     ("PAUSA", "pause"), ("REINI", "reset"), ("SALIR", "quit")],
]


def compute_layout(sw, sh, touch, fixed_scale=None, crisp=False):
    """Reparte la pantalla entre el juego y, si hace falta, los botones.

    `crisp` fuerza escalas enteras (ventana de escritorio); en movil se
    aprovecha toda la pantalla, que a esa densidad no se nota."""
    # dos filas de botones, de 190 px de alto como mucho para no comerse
    # la pantalla en un movil en vertical
    strip_h = min(max(104, int(sh * 0.24)), 380, sh // 2) if touch else 0
    avail_h = sh - strip_h
    if fixed_scale:
        ratio = float(fixed_scale)
    else:
        ratio = max(0.4, min(sw / float(BASE_W), avail_h / float(BASE_H)))
        if crisp and ratio >= 2.0:
            ratio = float(int(ratio))
    w, h = int(BASE_W * ratio), int(BASE_H * ratio)
    dest = pygame.Rect((sw - w) // 2, max(0, (avail_h - h) // 2), w, h)
    strip = pygame.Rect(0, sh - strip_h, sw, strip_h)
    return dest, strip


def touch_buttons(strip):
    """Devuelve [(rect, etiqueta, accion)] repartidos por la franja inferior."""
    out = []
    rows = len(TOUCH_ROWS)
    bh = strip.h // rows
    for r, row in enumerate(TOUCH_ROWS):
        bw = strip.w // len(row)
        for c, (label, action) in enumerate(row):
            out.append((pygame.Rect(strip.x + c * bw + 2, strip.y + r * bh + 2,
                                    bw - 4, bh - 4), label, action))
    return out


def touch_font(strip):
    """Letra de los botones: la mayor que cabe de alto y de ancho."""
    cols = max(len(row) for row in TOUCH_ROWS)
    longest = max(len(label) for row in TOUCH_ROWS for label, _ in row)
    by_height = strip.h // 6
    by_width = (strip.w / float(cols) - 10) / (0.62 * longest)
    return load_mono(int(max(9, min(40, by_height, by_width))))


def draw_touchpad(screen, buttons, font, flash):
    for rect, label, action in buttons:
        lit = flash.get(action, 0.0) > 0.0
        pygame.draw.rect(screen, GREY if lit else BLACK, rect)
        pygame.draw.rect(screen, YELLOW if lit else WHITE, rect, 2)
        img = font.render(label, False, BLACK if lit else CYAN)
        screen.blit(img, (rect.centerx - img.get_width() // 2,
                          rect.centery - img.get_height() // 2))


# ===========================================================================
#  Bucle principal
# ===========================================================================
def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    mute = "--mute" in argv
    touch = ANDROID or "--touch" in argv
    if "--no-touch" in argv:
        touch = False
    full = ANDROID or "--fullscreen" in argv
    scale = None
    if "--scale" in argv:
        try:
            scale = max(1, min(6, int(argv[argv.index("--scale") + 1])))
        except (ValueError, IndexError):
            scale = None

    audio = Audio(enabled=not mute)          # antes de pygame.init() por el mixer
    pygame.init()
    pygame.font.init()
    pygame.display.set_caption("NIGHT PILOT 64")

    if full:
        try:
            info = pygame.display.Info()
            screen = pygame.display.set_mode((info.current_w, info.current_h),
                                             pygame.FULLSCREEN)
        except Exception:
            screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
    else:
        screen = pygame.display.set_mode((BASE_W * (scale or 2),
                                          BASE_H * (scale or 2)))
    sw, sh = screen.get_size()
    dest, strip = compute_layout(sw, sh, touch, None if full else scale,
                                 crisp=not full)
    buttons = touch_buttons(strip) if touch else []
    btn_font = touch_font(strip) if touch else None

    base = pygame.Surface((BASE_W, BASE_H))
    fonts = Fonts()
    clock = pygame.time.Clock()

    flight = Flight(level=1)
    view_mode = "cockpit"
    paused = False
    show_help = True
    ended_handled = False
    running = True
    flash = {}
    t = 0.0

    def act(name):
        """Una sola tabla de acciones para el teclado y para los botones."""
        nonlocal view_mode, paused, show_help, ended_handled, running
        if name == "quit":
            running = False
        elif name == "help":
            show_help = not show_help
        elif name == "pause":
            paused = not paused
        elif name == "cockpit":
            view_mode = "cockpit"
        elif name == "map":
            view_mode = "map"
        elif name == "view":
            view_mode = "map" if view_mode == "cockpit" else "cockpit"
        elif name == "reset":
            flight.start(flight.level)
            ended_handled = False
            show_help = False
        elif name == "next" and flight.state == "landed":
            flight.start(flight.level + 1)
            ended_handled = False
        elif show_help:
            show_help = False                # el primer toque solo despega
        elif flight.state == "fly" and not paused:
            {"up": flight.pitch_up, "down": flight.pitch_down,
             "left": flight.tilt_left, "right": flight.tilt_right,
             "gear": flight.toggle_gear,
             "faster": lambda: flight.throttle(5),
             "slower": lambda: flight.throttle(-5)}.get(name, lambda: None)()

    KEYMAP = {}
    for key_names, action in (
            (("K_ESCAPE", "K_q"), "quit"), (("K_h",), "help"),
            (("K_p",), "pause"), (("K_F1",), "cockpit"), (("K_F3",), "map"),
            (("K_TAB",), "view"), (("K_r",), "reset"), (("K_n",), "next"),
            (("K_w", "K_UP"), "up"), (("K_x", "K_DOWN"), "down"),
            (("K_a", "K_LEFT"), "left"), (("K_d", "K_RIGHT"), "right"),
            (("K_SPACE",), "gear"),
            (("K_PLUS", "K_EQUALS", "K_KP_PLUS"), "faster"),
            (("K_MINUS", "K_KP_MINUS"), "slower")):
        for kn in key_names:
            code = getattr(pygame, kn, None)
            if code is not None:
                KEYMAP[code] = action

    while running:
        dt = clock.tick(60) / 1000.0
        dt = min(dt, 0.05)
        t += dt
        for key in list(flash):
            flash[key] -= dt
            if flash[key] <= 0:
                del flash[key]

        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                running = False
            elif ev.type == pygame.KEYDOWN:
                action = KEYMAP.get(ev.key)
                if action:
                    act(action)
                elif show_help:
                    show_help = False
            elif ev.type == pygame.MOUSEBUTTONDOWN:
                pos = getattr(ev, "pos", None)
                if pos is None:
                    continue
                for rect, label, action in buttons:
                    if rect.collidepoint(pos):
                        flash[action] = 0.12
                        act(action)
                        break
                else:
                    if show_help:
                        show_help = False
                    elif flight.state != "fly":
                        act("reset")

        if not paused and not show_help:
            flight.update(dt)

        # sonido
        audio.engine(flight.speed, flight.state == "fly" and flight.engine and not paused)
        audio.warn_beep(bool(flight.warn) and flight.state == "fly" and not paused, dt)
        if flight.state != "fly" and not ended_handled:
            ended_handled = True
            if flight.state == "crashed":
                audio.crash()
            else:
                audio.success()

        draw_frame(base, flight, fonts, t, view_mode, paused, show_help)
        screen.fill(BLACK)
        screen.blit(pygame.transform.scale(base, (dest.w, dest.h)), (dest.x, dest.y))
        if touch:
            draw_touchpad(screen, buttons, btn_font, flash)
        pygame.display.flip()

    pygame.quit()
    return 0


# ===========================================================================
#  Prueba automatica del modelo (sin ventana):  python3 night_pilot.py --selftest
# ===========================================================================
def selftest(wind=0.0, level=1, seed=3, verbose=True):
    """Vuela una aproximacion completa con un piloto automatico tosco.

    Sirve para comprobar que el modelo es jugable: que se puede seguir la
    senda, frenar a tiempo y tocar dentro de los limites."""
    f = Flight(level=level, seed=seed)
    f.wind = wind
    dt = 1.0 / 30.0
    steps = 0
    ctrl = 0.0                               # el piloto solo actua 4 veces/s
    while f.state == "fly" and steps < 30000:
        steps += 1
        ctrl -= dt
        if ctrl <= 0.0:
            ctrl = 0.25
            # --- senda vertical: ritmo de la senda mas correccion del error
            path = -GLIDE_K * f.speed * DIST_RATE * 60.0
            err = f.alt - f.ideal_alt
            want_vs = path - err * 1.5
            if f.dist < 300:
                want_vs = max(want_vs, -650.0)          # llegada suave
            best = min(VS_RATES, key=lambda i: abs(VS_RATES[i] - want_vs))
            best = max(-2, min(1, best))
            if best > f.vs_idx:
                f.pitch_up()
            elif best < f.vs_idx:
                f.pitch_down()
            # --- eje de pista
            if f.lateral > 1.5 and f.tilt_idx > -1:
                f.tilt_left()
            elif f.lateral < -1.5 and f.tilt_idx < 1:
                f.tilt_right()
            elif abs(f.lateral) <= 1.5 and f.tilt_idx != 0:
                (f.tilt_left if f.tilt_idx > 0 else f.tilt_right)()
            # --- velocidad
            want = 300.0 if f.dist > 1200 else (200.0 if f.dist > 500 else 150.0)
            if f.speed < want - 4:
                f.throttle(5)
            elif f.speed > want + 4:
                f.throttle(-5)
            # --- tren
            if f.dist < 700 and not f.gear:
                f.toggle_gear()
        f.update(dt)
    if not verbose:
        return f
    print("estado ......", f.state)
    print("titulo ......", f.end_title())
    print("detalle .....", f.result)
    print("tiempo ......", "%.1f s" % f.t)
    print("toma ........ dist %.0f  v/s %+d  spd %.0f  tilt %+d  desvio %+.1f"
          % (f.dist, f.touch_vs, f.touch_speed, f.touch_tilt, f.touch_lateral))
    print("combustible .", "%.0f%%" % f.fuel)
    print("puntos ......", f.score)
    return 0 if f.state == "landed" else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    sys.exit(main())
