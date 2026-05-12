"""RoboCop — Python edition.

A side-scrolling run-and-gun inspired by the 1988 Data East arcade and the
Ocean Software ZX Spectrum port. Single file, pygame only (numpy optional
for synthesised audio).

Controls:
    Arrows / WASD   move, down to crouch
    Space           fire
    Z / LShift      jump
    Enter           start / advance / continue
    Esc             pause / quit from title
    Mouse           aim during hostage bonus, left-click to fire
"""

from __future__ import annotations

import math
import random
import sys
from dataclasses import dataclass, field
from typing import Callable

import pygame

try:
    import numpy as np
    HAS_NUMPY = True
except Exception:
    HAS_NUMPY = False


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

W, H = 640, 360
SCALE = 2
WIN_W, WIN_H = W * SCALE, H * SCALE
FPS = 60
GROUND_Y = H - 56

# Modern palette (cyberpunk noir)
BLACK = (0, 0, 0)
WHITE = (240, 244, 250)
CYAN = (0, 230, 255)
MAGENTA = (230, 60, 200)
YELLOW = (255, 220, 70)
RED = (235, 50, 60)
GREEN = (60, 230, 110)
BLUE = (60, 130, 240)
DARK = (10, 14, 24)
GREY = (130, 138, 150)
ORANGE = (255, 150, 40)
STEEL_LIGHT = (210, 220, 230)
STEEL_MID = (150, 165, 180)
STEEL_DARK = (60, 75, 95)
ARMOR_BLUE = (70, 110, 170)
ARMOR_HIGH = (180, 210, 240)
VISOR_GLOW = (60, 255, 240)

WEAPON_AUTO9 = "AUTO-9"
WEAPON_TRIPLE = "3-WAY"
WEAPON_RAPID = "RAPID"
WEAPON_COBRA = "COBRA"

WEAPON_DURATION = 12.0


# ---------------------------------------------------------------------------
# Audio — synthesised at startup
# ---------------------------------------------------------------------------

class Audio:
    def __init__(self):
        self.enabled = False
        self.sounds: dict[str, pygame.mixer.Sound] = {}
        if not HAS_NUMPY:
            return
        try:
            pygame.mixer.pre_init(22050, -16, 1, 512)
            pygame.mixer.init()
        except pygame.error:
            return
        self.enabled = True
        self._make("shot", self._square(880, 0.05, 0.25))
        self._make("triple", self._square(660, 0.07, 0.25))
        self._make("rapid", self._square(1100, 0.03, 0.20))
        self._make("cobra", self._noise(0.10, 0.35))
        self._make("punch", self._noise(0.08, 0.45))
        self._make("hit", self._sweep(440, 110, 0.18, 0.40))
        self._make("powerup", self._arpeggio([523, 659, 784, 1046], 0.06, 0.35))
        self._make("clear", self._arpeggio([523, 659, 784, 1046, 784, 1046], 0.10, 0.40))
        self._make("explode", self._noise(0.35, 0.55))
        self._make("ed209_step", self._sweep(120, 60, 0.20, 0.40))

    def _make(self, name: str, samples) -> None:
        if not self.enabled:
            return
        try:
            channels = pygame.mixer.get_init()[2] if pygame.mixer.get_init() else 1
            if channels == 2:
                samples = np.column_stack((samples, samples))
            snd = pygame.sndarray.make_sound(samples)
        except Exception:
            return
        self.sounds[name] = snd

    @staticmethod
    def _square(freq: float, dur: float, vol: float):
        n = int(22050 * dur)
        t = np.arange(n)
        wave = np.where((t * freq / 22050) % 1.0 < 0.5, 1.0, -1.0)
        env = np.linspace(1.0, 0.0, n) ** 1.5
        out = (wave * env * vol * 32767).astype(np.int16)
        return out

    @staticmethod
    def _noise(dur: float, vol: float):
        n = int(22050 * dur)
        wave = np.random.uniform(-1.0, 1.0, n)
        env = np.linspace(1.0, 0.0, n) ** 1.2
        return (wave * env * vol * 32767).astype(np.int16)

    @staticmethod
    def _sweep(f1: float, f2: float, dur: float, vol: float):
        n = int(22050 * dur)
        t = np.linspace(0, dur, n)
        freq = np.linspace(f1, f2, n)
        phase = 2 * np.pi * np.cumsum(freq) / 22050
        wave = np.sign(np.sin(phase))
        env = np.linspace(1.0, 0.0, n) ** 1.2
        return (wave * env * vol * 32767).astype(np.int16)

    @staticmethod
    def _arpeggio(freqs: list[float], note_dur: float, vol: float):
        chunks = []
        for f in freqs:
            n = int(22050 * note_dur)
            t = np.arange(n)
            wave = np.where((t * f / 22050) % 1.0 < 0.5, 1.0, -1.0)
            env = np.linspace(1.0, 0.6, n)
            chunks.append((wave * env * vol * 32767).astype(np.int16))
        return np.concatenate(chunks)

    def play(self, name: str) -> None:
        if not self.enabled:
            return
        snd = self.sounds.get(name)
        if snd is not None:
            snd.play()


# ---------------------------------------------------------------------------
# Drawing helpers
# ---------------------------------------------------------------------------

# Cached glow surfaces keyed by (radius, colour)
_GLOW_CACHE: dict[tuple, pygame.Surface] = {}


def glow(radius: int, colour: tuple[int, int, int], alpha: int = 180) -> pygame.Surface:
    key = (radius, colour, alpha)
    s = _GLOW_CACHE.get(key)
    if s is not None:
        return s
    size = radius * 2 + 2
    s = pygame.Surface((size, size), pygame.SRCALPHA)
    for r in range(radius, 0, -1):
        a = int(alpha * (1 - r / radius) ** 2)
        pygame.draw.circle(s, (*colour, a), (radius + 1, radius + 1), r)
    _GLOW_CACHE[key] = s
    return s


def blit_glow(surf: pygame.Surface, pos: tuple[int, int], radius: int,
              colour: tuple[int, int, int], alpha: int = 180) -> None:
    g = glow(radius, colour, alpha)
    surf.blit(g, (pos[0] - radius - 1, pos[1] - radius - 1),
              special_flags=pygame.BLEND_ADD)


_GRAD_CACHE: dict[tuple, pygame.Surface] = {}


def gradient_rect(surf: pygame.Surface, rect: pygame.Rect,
                  c0: tuple[int, int, int], c1: tuple[int, int, int]) -> None:
    key = (rect.width, rect.height, c0, c1)
    cached = _GRAD_CACHE.get(key)
    if cached is None:
        strip = pygame.Surface((1, rect.height))
        for y in range(rect.height):
            t = y / max(1, rect.height - 1)
            strip.set_at((0, y), (
                int(c0[0] + (c1[0] - c0[0]) * t),
                int(c0[1] + (c1[1] - c0[1]) * t),
                int(c0[2] + (c1[2] - c0[2]) * t),
            ))
        cached = pygame.transform.scale(strip, (rect.width, rect.height))
        _GRAD_CACHE[key] = cached
    surf.blit(cached, rect.topleft)


def draw_robocop(surf: pygame.Surface, x: int, y: int, facing: int,
                 walking_phase: float, crouching: bool, flicker: bool) -> None:
    """Draw RoboCop with shading: silver-blue armor, glowing visor strip.
    (x, y) is feet-centre."""
    if flicker and int(walking_phase * 20) % 2 == 0:
        return

    f = 1 if facing >= 0 else -1
    walk = math.sin(walking_phase * 9) if not crouching else 0
    leg_swing = int(walk * 4)
    body_lift = int(abs(walk) * 1.2)
    h_total = 40 if not crouching else 30

    # Soft drop shadow on ground
    sh = pygame.Surface((26, 6), pygame.SRCALPHA)
    pygame.draw.ellipse(sh, (0, 0, 0, 120), sh.get_rect())
    surf.blit(sh, (x - 13, y - 2))

    # Legs (front and back leg with swing)
    for side, swing in ((-1, leg_swing), (1, -leg_swing)):
        lx = x + side * 3
        ltop = y - 14 + body_lift
        if crouching:
            ltop = y - 8
        # Thigh
        pygame.draw.rect(surf, STEEL_DARK, (lx - 3, ltop, 6, 8))
        pygame.draw.rect(surf, STEEL_MID, (lx - 3, ltop, 6, 2))
        # Shin
        pygame.draw.rect(surf, STEEL_DARK, (lx - 3 + swing // 2, ltop + 7, 6, 8))
        pygame.draw.rect(surf, STEEL_LIGHT, (lx - 3 + swing // 2, ltop + 7, 1, 8))
        # Boot
        pygame.draw.rect(surf, BLACK, (lx - 4 + swing // 2, y - 2, 8, 3))
        pygame.draw.line(surf, STEEL_MID, (lx - 4 + swing // 2, y - 2),
                         (lx + 3 + swing // 2, y - 2))

    # Torso (chestplate with light side and dark side)
    top = y - h_total + body_lift
    chest_h = 16 if not crouching else 12
    body_w = 18
    pygame.draw.rect(surf, ARMOR_BLUE, (x - body_w // 2, top + 6, body_w, chest_h))
    # Highlight (light side facing direction)
    pygame.draw.rect(surf, ARMOR_HIGH, (x - body_w // 2, top + 6,
                                        body_w, 2))
    pygame.draw.rect(surf, STEEL_LIGHT,
                     (x + (body_w // 2 - 2) * f, top + 6, 2, chest_h))
    # Shadow side
    pygame.draw.rect(surf, STEEL_DARK,
                     (x - (body_w // 2) * f, top + 6, 2, chest_h))
    # Sternum line
    pygame.draw.line(surf, STEEL_DARK, (x, top + 8), (x, top + 6 + chest_h - 2))
    # Belt
    pygame.draw.rect(surf, STEEL_DARK, (x - body_w // 2, top + 6 + chest_h - 2, body_w, 2))

    # Shoulders (rounded)
    pygame.draw.circle(surf, STEEL_MID, (x - body_w // 2 + 1, top + 7), 4)
    pygame.draw.circle(surf, STEEL_MID, (x + body_w // 2 - 1, top + 7), 4)
    pygame.draw.circle(surf, STEEL_LIGHT, (x - body_w // 2 + 1, top + 6), 2)
    pygame.draw.circle(surf, STEEL_LIGHT, (x + body_w // 2 - 1, top + 6), 2)

    # Head / helmet
    helm_w = 12
    pygame.draw.rect(surf, STEEL_LIGHT, (x - helm_w // 2, top, helm_w, 8))
    pygame.draw.rect(surf, STEEL_DARK, (x - helm_w // 2, top + 7, helm_w, 1))
    # Helmet top highlight
    pygame.draw.rect(surf, WHITE, (x - helm_w // 2 + 2, top, helm_w - 4, 1))
    # Jaw / chin
    pygame.draw.rect(surf, (220, 200, 180), (x - 3, top + 6, 6, 3))
    # Visor strip with glow
    visor_rect = (x - helm_w // 2 + 1, top + 3, helm_w - 2, 2)
    pygame.draw.rect(surf, VISOR_GLOW, visor_rect)
    blit_glow(surf, (x, top + 4), 6, VISOR_GLOW, alpha=200)

    # Arm + Auto-9
    arm_y = top + 9 + body_lift if not crouching else top + 7
    if f >= 0:
        # Upper arm
        pygame.draw.rect(surf, ARMOR_BLUE, (x + body_w // 2 - 1, arm_y - 1, 5, 5))
        pygame.draw.rect(surf, ARMOR_HIGH, (x + body_w // 2 - 1, arm_y - 1, 5, 1))
        # Forearm
        pygame.draw.rect(surf, STEEL_MID, (x + body_w // 2 + 3, arm_y, 4, 4))
        # Auto-9
        gx = x + body_w // 2 + 6
        pygame.draw.rect(surf, (35, 35, 40), (gx, arm_y, 9, 3))
        pygame.draw.rect(surf, (70, 70, 80), (gx, arm_y, 9, 1))
        pygame.draw.rect(surf, (35, 35, 40), (gx + 1, arm_y + 3, 3, 2))
    else:
        pygame.draw.rect(surf, ARMOR_BLUE, (x - body_w // 2 - 4, arm_y - 1, 5, 5))
        pygame.draw.rect(surf, ARMOR_HIGH, (x - body_w // 2 - 4, arm_y - 1, 5, 1))
        pygame.draw.rect(surf, STEEL_MID, (x - body_w // 2 - 7, arm_y, 4, 4))
        gx = x - body_w // 2 - 15
        pygame.draw.rect(surf, (35, 35, 40), (gx, arm_y, 9, 3))
        pygame.draw.rect(surf, (70, 70, 80), (gx, arm_y, 9, 1))
        pygame.draw.rect(surf, (35, 35, 40), (gx + 5, arm_y + 3, 3, 2))


def draw_punk(surf: pygame.Surface, x: int, y: int, phase: float,
              colour: tuple[int, int, int], facing: int) -> None:
    f = 1 if facing >= 0 else -1
    walk = math.sin(phase * 8)
    leg_swing = int(walk * 3)

    # Shadow
    sh = pygame.Surface((20, 5), pygame.SRCALPHA)
    pygame.draw.ellipse(sh, (0, 0, 0, 110), sh.get_rect())
    surf.blit(sh, (x - 10, y - 2))

    # Legs (denim jeans)
    jeans = (40, 55, 100)
    jeans_dark = (20, 30, 60)
    pygame.draw.rect(surf, jeans, (x - 4, y - 12, 4, 12 - leg_swing))
    pygame.draw.rect(surf, jeans, (x + 0, y - 12, 4, 12 + leg_swing))
    pygame.draw.rect(surf, jeans_dark, (x - 4, y - 12, 1, 12))
    pygame.draw.rect(surf, jeans_dark, (x + 0, y - 12, 1, 12))
    # Boots
    pygame.draw.rect(surf, BLACK, (x - 5, y - 1, 5, 2))
    pygame.draw.rect(surf, BLACK, (x + 0, y - 1, 5, 2))

    # Torso (leather jacket)
    jacket = colour
    jacket_dark = tuple(max(0, c - 60) for c in colour)
    jacket_light = tuple(min(255, c + 50) for c in colour)
    pygame.draw.rect(surf, jacket, (x - 6, y - 24, 12, 13))
    pygame.draw.rect(surf, jacket_light, (x - 6, y - 24, 12, 2))
    pygame.draw.rect(surf, jacket_dark, (x + 4 * f, y - 24, 2, 13))
    # Zipper
    pygame.draw.line(surf, (200, 200, 80), (x, y - 22), (x, y - 13))

    # Head
    skin = (220, 190, 160)
    pygame.draw.rect(surf, skin, (x - 4, y - 30, 8, 6))
    pygame.draw.rect(surf, (160, 130, 100), (x - 4, y - 25, 8, 1))
    # Hair (mohawk)
    hair = (30, 30, 40)
    pygame.draw.rect(surf, hair, (x - 4, y - 32, 8, 3))
    pygame.draw.rect(surf, hair, (x - 1, y - 34, 2, 2))
    # Eyes
    pygame.draw.rect(surf, RED, (x - 2 + (1 if f > 0 else -2), y - 29, 1, 1))
    pygame.draw.rect(surf, RED, (x + 1 + (1 if f > 0 else -2), y - 29, 1, 1))

    # Pistol
    gx = x + (5 if f > 0 else -10)
    pygame.draw.rect(surf, (40, 40, 50), (gx, y - 20, 6, 2))
    pygame.draw.rect(surf, (80, 80, 90), (gx, y - 20, 6, 1))


def draw_heavy(surf: pygame.Surface, x: int, y: int, phase: float, facing: int) -> None:
    """Armoured swat-like thug."""
    f = 1 if facing >= 0 else -1
    walk = math.sin(phase * 6)
    leg_swing = int(walk * 3)
    sh = pygame.Surface((24, 5), pygame.SRCALPHA)
    pygame.draw.ellipse(sh, (0, 0, 0, 120), sh.get_rect())
    surf.blit(sh, (x - 12, y - 2))
    # Legs
    pygame.draw.rect(surf, (40, 50, 50), (x - 5, y - 12, 4, 12 - leg_swing))
    pygame.draw.rect(surf, (40, 50, 50), (x + 1, y - 12, 4, 12 + leg_swing))
    pygame.draw.rect(surf, BLACK, (x - 6, y - 1, 6, 2))
    pygame.draw.rect(surf, BLACK, (x + 0, y - 1, 6, 2))
    # Body armour
    body = (55, 80, 60)
    bodyL = (90, 130, 95)
    bodyD = (30, 45, 35)
    pygame.draw.rect(surf, body, (x - 8, y - 26, 16, 15))
    pygame.draw.rect(surf, bodyL, (x - 8, y - 26, 16, 2))
    pygame.draw.rect(surf, bodyD, (x + (6 * f), y - 26, 2, 15))
    # Vest pockets
    pygame.draw.rect(surf, bodyD, (x - 6, y - 22, 4, 3))
    pygame.draw.rect(surf, bodyD, (x + 2, y - 22, 4, 3))
    # Helmet (full visor)
    pygame.draw.rect(surf, (35, 35, 40), (x - 5, y - 33, 10, 8))
    pygame.draw.rect(surf, (60, 60, 65), (x - 5, y - 33, 10, 1))
    pygame.draw.rect(surf, (180, 50, 50), (x - 4, y - 31, 8, 2))
    blit_glow(surf, (x, y - 30), 5, (220, 60, 60), alpha=140)
    # Rifle
    if f > 0:
        pygame.draw.rect(surf, (30, 30, 35), (x + 6, y - 22, 12, 2))
        pygame.draw.rect(surf, (60, 60, 65), (x + 6, y - 22, 12, 1))
        pygame.draw.rect(surf, (30, 30, 35), (x + 4, y - 23, 4, 4))
    else:
        pygame.draw.rect(surf, (30, 30, 35), (x - 18, y - 22, 12, 2))
        pygame.draw.rect(surf, (60, 60, 65), (x - 18, y - 22, 12, 1))
        pygame.draw.rect(surf, (30, 30, 35), (x - 8, y - 23, 4, 4))


def draw_ed209(surf: pygame.Surface, x: int, y: int, phase: float) -> None:
    body = (180, 130, 50)
    body_high = (240, 200, 120)
    body_low = (110, 70, 20)
    dark = (60, 40, 10)
    # Shadow
    sh = pygame.Surface((80, 10), pygame.SRCALPHA)
    pygame.draw.ellipse(sh, (0, 0, 0, 150), sh.get_rect())
    surf.blit(sh, (x - 40, y - 4))
    # Legs (chicken-walker)
    sway = int(math.sin(phase * 3) * 4)
    for side, off in ((-1, sway), (1, -sway)):
        lx = x + side * 14
        # Thigh
        pygame.draw.polygon(surf, body_low,
                            [(lx - 6, y - 50), (lx + 6, y - 50),
                             (lx + 8, y - 30), (lx - 8, y - 30)])
        pygame.draw.line(surf, body_high, (lx - 6, y - 50), (lx - 6, y - 30))
        # Shin
        pygame.draw.rect(surf, dark, (lx - 4, y - 30, 8, 22 + off))
        pygame.draw.rect(surf, body_low, (lx - 4, y - 30, 2, 22 + off))
        # Claw foot
        pygame.draw.polygon(surf, dark,
                            [(lx - 10, y), (lx + 10, y),
                             (lx + 8, y + 5), (lx, y + 4), (lx - 8, y + 5)])
        pygame.draw.line(surf, body_high, (lx - 6, y + 1), (lx + 6, y + 1))
    # Hip pivot
    pygame.draw.ellipse(surf, body_low, (x - 18, y - 56, 36, 14))
    # Main torso
    pygame.draw.polygon(surf, body,
                        [(x - 26, y - 76), (x + 26, y - 76),
                         (x + 32, y - 52), (x - 32, y - 52)])
    pygame.draw.polygon(surf, body_high,
                        [(x - 26, y - 76), (x + 26, y - 76),
                         (x + 22, y - 72), (x - 22, y - 72)])
    pygame.draw.polygon(surf, body_low,
                        [(x - 32, y - 52), (x + 32, y - 52),
                         (x + 26, y - 56), (x - 26, y - 56)])
    # Panel lines
    pygame.draw.line(surf, dark, (x - 18, y - 76), (x - 22, y - 52))
    pygame.draw.line(surf, dark, (x + 18, y - 76), (x + 22, y - 52))
    pygame.draw.line(surf, dark, (x, y - 76), (x, y - 52))
    # Shoulders (rotary cannons / missile pods)
    for side in (-1, 1):
        sx = x + side * 32
        pygame.draw.rect(surf, body_low, (sx - 8, y - 70, 16, 14))
        pygame.draw.rect(surf, body_high, (sx - 8, y - 70, 16, 2))
        # Gun barrels
        bx = sx + side * 8
        pygame.draw.rect(surf, dark, (bx if side > 0 else bx - 14, y - 66, 14, 4))
        pygame.draw.circle(surf, BLACK,
                           (bx + (12 if side > 0 else -12), y - 64), 2)
    # Head/sensor cluster
    pygame.draw.polygon(surf, body,
                        [(x - 14, y - 92), (x + 14, y - 92),
                         (x + 18, y - 78), (x - 18, y - 78)])
    pygame.draw.polygon(surf, body_high,
                        [(x - 14, y - 92), (x + 14, y - 92),
                         (x + 10, y - 90), (x - 10, y - 90)])
    # Twin sensor eyes
    pygame.draw.rect(surf, (40, 0, 0), (x - 10, y - 86, 7, 5))
    pygame.draw.rect(surf, (40, 0, 0), (x + 3, y - 86, 7, 5))
    pygame.draw.rect(surf, RED, (x - 9, y - 85, 5, 3))
    pygame.draw.rect(surf, RED, (x + 4, y - 85, 5, 3))
    blit_glow(surf, (x - 7, y - 84), 6, RED, alpha=200)
    blit_glow(surf, (x + 6, y - 84), 6, RED, alpha=200)
    # Antennae
    pygame.draw.line(surf, dark, (x - 8, y - 92), (x - 10, y - 100))
    pygame.draw.line(surf, dark, (x + 8, y - 92), (x + 10, y - 100))


def draw_boddicker(surf: pygame.Surface, x: int, y: int, phase: float, facing: int) -> None:
    f = 1 if facing >= 0 else -1
    walk = math.sin(phase * 8)
    leg_swing = int(walk * 3)
    sh = pygame.Surface((22, 5), pygame.SRCALPHA)
    pygame.draw.ellipse(sh, (0, 0, 0, 130), sh.get_rect())
    surf.blit(sh, (x - 11, y - 2))
    # Pants
    pygame.draw.rect(surf, (30, 30, 35), (x - 5, y - 14, 4, 14 - leg_swing))
    pygame.draw.rect(surf, (30, 30, 35), (x + 1, y - 14, 4, 14 + leg_swing))
    pygame.draw.rect(surf, BLACK, (x - 6, y - 1, 6, 2))
    pygame.draw.rect(surf, BLACK, (x + 0, y - 1, 6, 2))
    # Suit jacket
    pygame.draw.rect(surf, (50, 50, 60), (x - 7, y - 28, 14, 16))
    pygame.draw.rect(surf, (90, 90, 100), (x - 7, y - 28, 14, 2))
    pygame.draw.rect(surf, (25, 25, 30), (x + (5 * f), y - 28, 2, 16))
    # Shirt + tie
    pygame.draw.rect(surf, WHITE, (x - 2, y - 28, 4, 6))
    pygame.draw.rect(surf, RED, (x - 1, y - 26, 2, 8))
    # Head
    skin = (220, 190, 160)
    pygame.draw.rect(surf, skin, (x - 5, y - 36, 10, 8))
    pygame.draw.rect(surf, (170, 140, 110), (x - 5, y - 29, 10, 1))
    # Hair (slicked back, blond)
    pygame.draw.rect(surf, (200, 180, 90), (x - 5, y - 38, 10, 3))
    pygame.draw.rect(surf, (160, 140, 60), (x - 5, y - 38, 10, 1))
    # Glasses
    pygame.draw.rect(surf, BLACK, (x - 5, y - 33, 4, 2))
    pygame.draw.rect(surf, BLACK, (x + 1, y - 33, 4, 2))
    pygame.draw.line(surf, BLACK, (x - 1, y - 32), (x + 1, y - 32))
    blit_glow(surf, (x, y - 32), 4, (180, 200, 220), alpha=70)
    # Shotgun
    if f > 0:
        pygame.draw.rect(surf, (40, 20, 10), (x + 6, y - 22, 14, 3))
        pygame.draw.rect(surf, (70, 40, 20), (x + 6, y - 22, 14, 1))
        pygame.draw.rect(surf, (40, 40, 50), (x + 18, y - 22, 4, 3))
    else:
        pygame.draw.rect(surf, (40, 20, 10), (x - 20, y - 22, 14, 3))
        pygame.draw.rect(surf, (70, 40, 20), (x - 20, y - 22, 14, 1))
        pygame.draw.rect(surf, (40, 40, 50), (x - 22, y - 22, 4, 3))


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------

@dataclass
class Bullet:
    x: float
    y: float
    vx: float
    vy: float
    friendly: bool
    damage: int = 1
    life: float = 2.5
    pierce: bool = False
    colour: tuple[int, int, int] = YELLOW
    size: int = 2
    gravity: bool = False
    hit_ids: set = field(default_factory=set)

    @property
    def rect(self) -> pygame.Rect:
        return pygame.Rect(int(self.x - self.size), int(self.y - self.size),
                           self.size * 2, self.size * 2)


@dataclass
class Spark:
    x: float
    y: float
    vx: float
    vy: float
    life: float
    colour: tuple[int, int, int]


@dataclass
class PowerUp:
    x: float
    y: float
    kind: str

    @property
    def rect(self) -> pygame.Rect:
        return pygame.Rect(int(self.x - 6), int(self.y - 10), 12, 12)


class Enemy:
    def __init__(self, x: float, y: float, kind: str):
        self.x = x
        self.y = y
        self.kind = kind
        self.facing = -1
        self.phase = random.random() * 10
        self.cooldown = random.uniform(0.5, 1.8)
        self.dead = False
        self.hit_flash = 0.0
        self.score = 100
        if kind == "punk":
            self.hp = 1
            self.speed = 30
            self.colour = (200, 60, 60)
        elif kind == "heavy":
            self.hp = 2
            self.speed = 22
            self.colour = (60, 120, 60)
            self.score = 200
        elif kind == "drone":
            self.hp = 2
            self.speed = 50
            self.colour = ORANGE
            self.y = GROUND_Y - 80
            self.dive_t = random.uniform(2.0, 4.0)
            self.score = 250
        elif kind == "boddicker":
            self.hp = 14
            self.speed = 55
            self.colour = (200, 200, 200)
            self.score = 1000
        elif kind == "ed209":
            self.hp = 14
            self.speed = 18
            self.colour = (170, 110, 30)
            self.score = 3000
            self.missile_t = 1.5
            self.step_t = 0.0
        else:
            self.hp = 1
            self.speed = 30
            self.colour = WHITE

    @property
    def rect(self) -> pygame.Rect:
        if self.kind == "ed209":
            return pygame.Rect(int(self.x - 34), int(self.y - 100), 68, 100)
        if self.kind == "boddicker":
            return pygame.Rect(int(self.x - 8), int(self.y - 36), 16, 36)
        if self.kind == "drone":
            return pygame.Rect(int(self.x - 12), int(self.y - 10), 24, 18)
        return pygame.Rect(int(self.x - 6), int(self.y - 32), 12, 32)

    def update(self, dt: float, game: "Game") -> None:
        self.phase += dt
        if self.hit_flash > 0:
            self.hit_flash -= dt

        player = game.player
        dx = player.x - self.x
        self.facing = 1 if dx > 0 else -1

        if self.kind == "punk":
            if abs(dx) > 80:
                self.x += self.facing * self.speed * dt
            self.cooldown -= dt
            if self.cooldown <= 0 and abs(dx) < 220:
                game.spawn_enemy_bullet(self.x + self.facing * 6, self.y - 18,
                                        self.facing * 160, 0)
                self.cooldown = random.uniform(1.2, 2.0)
        elif self.kind == "heavy":
            self.cooldown -= dt
            if self.cooldown <= 0 and abs(dx) < 260:
                shooter = self
                for i in range(3):
                    def _shot(g=game, src=shooter, i=i):
                        if src.dead:
                            return
                        g.spawn_enemy_bullet(src.x + src.facing * 8,
                                             src.y - 16,
                                             src.facing * 180, 0)
                    game.delayed.append((0.12 * i, _shot))
                self.cooldown = 2.4
        elif self.kind == "drone":
            self.x += self.facing * self.speed * dt
            self.y += math.sin(self.phase * 3) * 0.6
            self.dive_t -= dt
            if self.dive_t <= 0:
                game.spawn_enemy_bullet(self.x, self.y + 8, 0, 200)
                self.dive_t = random.uniform(1.4, 2.6)
        elif self.kind == "boddicker":
            if abs(dx) > 70:
                self.x += self.facing * self.speed * dt
            self.cooldown -= dt
            if self.cooldown <= 0:
                for ang in (-0.15, 0, 0.15):
                    game.spawn_enemy_bullet(self.x + self.facing * 8, self.y - 22,
                                            self.facing * 200,
                                            math.sin(ang) * 200,
                                            colour=ORANGE)
                self.cooldown = 1.4
        elif self.kind == "ed209":
            # Slow stomp toward player
            if abs(dx) > 90:
                self.x += self.facing * self.speed * dt
                self.step_t += dt
                if self.step_t > 0.6:
                    game.audio.play("ed209_step")
                    self.step_t = 0
                    game.shake(2)
            self.missile_t -= dt
            if self.missile_t <= 0:
                # Lob 2 missiles
                for off in (-20, 20):
                    game.spawn_enemy_bullet(self.x + off, self.y - 36,
                                            self.facing * 120,
                                            -40,
                                            colour=ORANGE,
                                            gravity=True)
                self.missile_t = 2.6

    def draw(self, surf: pygame.Surface, cam_x: int) -> None:
        sx = int(self.x - cam_x)
        sy = int(self.y)
        if self.hit_flash > 0 and int(self.hit_flash * 40) % 2 == 0:
            return
        if self.kind == "punk":
            draw_punk(surf, sx, sy, self.phase, self.colour, self.facing)
        elif self.kind == "heavy":
            draw_heavy(surf, sx, sy, self.phase, self.facing)
        elif self.kind == "drone":
            # Hover drone with rotor blur + thruster glow
            bob = int(math.sin(self.phase * 6) * 2)
            sy2 = sy + bob
            # Rotor blur
            rotor = pygame.Surface((36, 4), pygame.SRCALPHA)
            pygame.draw.ellipse(rotor, (180, 180, 200, 120), rotor.get_rect())
            surf.blit(rotor, (sx - 18, sy2 - 14))
            pygame.draw.line(surf, GREY, (sx - 12, sy2 - 12), (sx + 12, sy2 - 12))
            # Body
            pygame.draw.ellipse(surf, (60, 60, 80), (sx - 12, sy2 - 8, 24, 14))
            pygame.draw.ellipse(surf, (110, 110, 140), (sx - 12, sy2 - 8, 24, 6))
            pygame.draw.rect(surf, self.colour, (sx - 8, sy2 - 4, 16, 4))
            # Eye
            pygame.draw.rect(surf, RED, (sx - 2, sy2 - 1, 4, 2))
            blit_glow(surf, (sx, sy2), 5, RED, alpha=160)
            # Thrusters
            tcol = (255, 180, 60)
            pygame.draw.rect(surf, tcol, (sx - 10, sy2 + 5, 4, 3))
            pygame.draw.rect(surf, tcol, (sx + 6, sy2 + 5, 4, 3))
            blit_glow(surf, (sx - 8, sy2 + 8), 5, tcol, alpha=180)
            blit_glow(surf, (sx + 8, sy2 + 8), 5, tcol, alpha=180)
        elif self.kind == "boddicker":
            draw_boddicker(surf, sx, sy, self.phase, self.facing)
        elif self.kind == "ed209":
            draw_ed209(surf, sx, sy, self.phase)

    def hit(self, dmg: int, game: "Game", melee: bool = False) -> None:
        if self.kind == "ed209" and not melee:
            # Bullets bounce
            for _ in range(3):
                game.sparks.append(Spark(self.x - 10, self.y - 30,
                                         random.uniform(-40, 40),
                                         random.uniform(-60, -20),
                                         0.3, YELLOW))
            return
        self.hp -= dmg
        self.hit_flash = 0.2
        game.audio.play("hit")
        if self.hp <= 0:
            self.dead = True
            game.score += self.score
            game.audio.play("explode")
            for _ in range(12):
                game.sparks.append(Spark(self.x,
                                         self.y - 14,
                                         random.uniform(-80, 80),
                                         random.uniform(-120, -20),
                                         random.uniform(0.3, 0.7),
                                         random.choice([YELLOW, ORANGE, RED])))


class Player:
    WIDTH = 16
    HEIGHT = 38

    def __init__(self):
        self.x = 60.0
        self.y = float(GROUND_Y)
        self.vx = 0.0
        self.vy = 0.0
        self.facing = 1
        self.on_ground = True
        self.crouching = False
        self.phase = 0.0
        self.hp = 6
        self.max_hp = 6
        self.lives = 3
        self.iframes = 0.0
        self.weapon = WEAPON_AUTO9
        self.weapon_t = 0.0
        self.shoot_cd = 0.0
        self.alive = True
        self.respawn_t = 0.0
        self.punch_t = 0.0
        self.muzzle_t = 0.0

    @property
    def rect(self) -> pygame.Rect:
        h = 22 if self.crouching else self.HEIGHT
        return pygame.Rect(int(self.x - self.WIDTH / 2),
                           int(self.y - h),
                           self.WIDTH, h)

    def take_hit(self, dmg: int, game: "Game") -> None:
        if self.iframes > 0 or not self.alive:
            return
        self.hp -= dmg
        self.iframes = 1.0
        game.audio.play("hit")
        game.shake(4)
        if self.hp <= 0:
            self.die(game)

    def die(self, game: "Game") -> None:
        self.alive = False
        self.lives -= 1
        self.respawn_t = 1.8
        game.audio.play("explode")
        for _ in range(20):
            game.sparks.append(Spark(self.x, self.y - 15,
                                     random.uniform(-120, 120),
                                     random.uniform(-160, -40),
                                     random.uniform(0.4, 0.9),
                                     random.choice([CYAN, WHITE, YELLOW])))

    def update(self, dt: float, game: "Game", input_state: dict) -> None:
        self.phase += dt
        if self.weapon != WEAPON_AUTO9:
            self.weapon_t -= dt
            if self.weapon_t <= 0:
                self.weapon = WEAPON_AUTO9
        self.shoot_cd = max(0, self.shoot_cd - dt)
        self.iframes = max(0, self.iframes - dt)
        self.punch_t = max(0, self.punch_t - dt)
        self.muzzle_t = max(0, self.muzzle_t - dt)

        if not self.alive:
            self.respawn_t -= dt
            if self.respawn_t <= 0:
                if self.lives > 0:
                    self.alive = True
                    self.hp = self.max_hp
                    self.iframes = 1.5
                    # respawn at camera left
                    self.x = max(game.cam_x + 40, self.x)
                    self.y = GROUND_Y
                else:
                    game.set_state("GAME_OVER")
            return

        move = 0
        if input_state.get("left"):
            move -= 1
            self.facing = -1
        if input_state.get("right"):
            move += 1
            self.facing = 1
        self.crouching = bool(input_state.get("down")) and self.on_ground

        speed = 90 if not self.crouching else 0
        self.vx = move * speed
        self.x += self.vx * dt

        if input_state.get("jump") and self.on_ground and not self.crouching:
            self.vy = -210
            self.on_ground = False

        self.vy += 620 * dt
        self.y += self.vy * dt
        if self.y >= GROUND_Y:
            self.y = GROUND_Y
            self.vy = 0
            self.on_ground = True

        # Clamp to stage bounds
        self.x = max(8, min(self.x, game.stage.length - 8))
        # Don't walk off left of camera
        self.x = max(self.x, game.cam_x + 8)

        if input_state.get("shoot"):
            self.try_shoot(game)

        # Auto-melee
        for e in game.enemies:
            if e.dead:
                continue
            if abs(e.x - self.x) < 18 and abs(e.y - self.y) < 36:
                if self.punch_t <= 0:
                    self.punch_t = 0.35
                    game.audio.play("punch")
                    e.hit(3, game, melee=True)
                    game.shake(2)
                    break

    def try_shoot(self, game: "Game") -> None:
        if self.shoot_cd > 0:
            return
        muzzle_x = self.x + self.facing * 22
        muzzle_y = self.y - (16 if self.crouching else 22)
        if self.weapon == WEAPON_AUTO9:
            game.bullets.append(Bullet(muzzle_x, muzzle_y,
                                       self.facing * 360, 0, True,
                                       colour=YELLOW))
            self.shoot_cd = 0.18
            game.audio.play("shot")
        elif self.weapon == WEAPON_TRIPLE:
            for ang in (-0.2, 0, 0.2):
                game.bullets.append(Bullet(muzzle_x, muzzle_y,
                                           self.facing * 340 * math.cos(ang),
                                           math.sin(ang) * 340,
                                           True,
                                           colour=CYAN))
            self.shoot_cd = 0.24
            game.audio.play("triple")
        elif self.weapon == WEAPON_RAPID:
            game.bullets.append(Bullet(muzzle_x, muzzle_y,
                                       self.facing * 420, 0, True,
                                       colour=WHITE))
            self.shoot_cd = 0.07
            game.audio.play("rapid")
        elif self.weapon == WEAPON_COBRA:
            game.bullets.append(Bullet(muzzle_x, muzzle_y,
                                       self.facing * 300, 0, True,
                                       damage=3, pierce=True,
                                       colour=ORANGE, size=3))
            self.shoot_cd = 0.32
            game.audio.play("cobra")
        # Flash regardless of weapon's cooldown length
        self.muzzle_t = 0.06

    def pick_weapon(self, kind: str, game: "Game") -> None:
        if kind == "health":
            self.hp = min(self.max_hp, self.hp + 2)
        else:
            self.weapon = kind
            self.weapon_t = WEAPON_DURATION
        game.audio.play("powerup")
        game.weapon_flash = (kind, 1.5)


# ---------------------------------------------------------------------------
# Stages
# ---------------------------------------------------------------------------

@dataclass
class StageSpawn:
    x: float
    fn: Callable[["Game"], None]


@dataclass
class Stage:
    name: str
    length: int
    palette: tuple
    spawns: list[StageSpawn]
    boss: str | None = None
    bonus_after: bool = False


def stage_streets() -> Stage:
    palette = ((25, 25, 50), (50, 30, 90), (180, 60, 140))
    spawns: list[StageSpawn] = []
    for x in (260, 360, 480, 600, 720, 900, 1050, 1200, 1380):
        kind = random.choice(["punk", "punk", "heavy"])
        spawns.append(StageSpawn(x, (lambda g, xx=x, k=kind:
                                     g.enemies.append(Enemy(xx, GROUND_Y, k)))))
    # Power-up halfway
    spawns.append(StageSpawn(700, lambda g: g.powerups.append(
        PowerUp(700, GROUND_Y - 10, WEAPON_TRIPLE))))
    spawns.append(StageSpawn(1100, lambda g: g.powerups.append(
        PowerUp(1100, GROUND_Y - 10, "health"))))
    return Stage("DETROIT STREETS", 1600, palette, spawns, bonus_after=True)


def stage_factory() -> Stage:
    palette = ((20, 30, 30), (40, 70, 60), (90, 200, 180))
    spawns: list[StageSpawn] = []
    xs = [260, 360, 460, 560, 700, 820, 940, 1060, 1180, 1320, 1450]
    for i, x in enumerate(xs):
        kind = "punk" if i % 3 else "heavy"
        spawns.append(StageSpawn(x, lambda g, xx=x, k=kind:
                                 g.enemies.append(Enemy(xx, GROUND_Y, k))))
    for x in (500, 1000):
        spawns.append(StageSpawn(x, lambda g, xx=x: g.enemies.append(
            Enemy(xx, GROUND_Y - 80, "drone"))))
    spawns.append(StageSpawn(800, lambda g: g.powerups.append(
        PowerUp(800, GROUND_Y - 10, WEAPON_RAPID))))
    spawns.append(StageSpawn(1300, lambda g: g.powerups.append(
        PowerUp(1300, GROUND_Y - 10, WEAPON_COBRA))))
    return Stage("DRUG FACTORY", 1700, palette, spawns)


def stage_junkyard() -> Stage:
    palette = ((30, 25, 15), (80, 55, 25), (240, 180, 60))
    spawns: list[StageSpawn] = []
    for x in (240, 360, 500, 640, 780, 920):
        spawns.append(StageSpawn(x, lambda g, xx=x: g.enemies.append(
            Enemy(xx, GROUND_Y, "heavy"))))
    spawns.append(StageSpawn(500, lambda g: g.powerups.append(
        PowerUp(500, GROUND_Y - 10, "health"))))
    return Stage("JUNKYARD", 1300, palette, spawns, boss="boddicker")


def stage_ocp() -> Stage:
    palette = ((10, 15, 35), (35, 50, 110), (130, 170, 240))
    spawns: list[StageSpawn] = []
    # Sparse goons leading up to the boss arena
    for x in (300, 480, 660, 820):
        spawns.append(StageSpawn(x, lambda g, xx=x: g.enemies.append(
            Enemy(xx, GROUND_Y, "heavy"))))
    spawns.append(StageSpawn(700, lambda g: g.powerups.append(
        PowerUp(700, GROUND_Y - 10, "health"))))
    return Stage("OCP HQ", 1500, palette, spawns, boss="ed209")


# ---------------------------------------------------------------------------
# Game
# ---------------------------------------------------------------------------

class Game:
    def __init__(self):
        pygame.init()
        self.window = pygame.display.set_mode((WIN_W, WIN_H))
        pygame.display.set_caption("RoboCop - Python")
        self.screen = pygame.Surface((W, H))
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("couriernew", 14, bold=True)
        self.big = pygame.font.SysFont("couriernew", 22, bold=True)
        self.huge = pygame.font.SysFont("couriernew", 40, bold=True)
        self.audio = Audio()
        self.scanline_overlay = self._build_scanlines()
        self.vignette = self._build_vignette()
        self.input = {"left": False, "right": False, "down": False,
                      "jump": False, "shoot": False}
        self.reset_run()

    def reset_run(self) -> None:
        """Reset all per-run state without rebuilding window/audio/overlays."""
        self.state = "TITLE"
        self.state_t = 0.0
        self.player = Player()
        self.bullets = []
        self.enemies = []
        self.powerups = []
        self.sparks = []
        self.delayed = []
        self.cam_x = 0.0
        self.score = 0
        self.shake_t = 0.0
        self.shake_amp = 0.0
        self.weapon_flash = None
        self.stage_index = 0
        self.stages = [stage_streets(), stage_factory(),
                       stage_junkyard(), stage_ocp()]
        self.stage = self.stages[0]
        self.spawned = set()
        self.boss_spawned = False
        self.stage_timer = 200.0
        self.bonus_targets = []
        self.bonus_t = 0.0
        self.bonus_score = 0
        self.crosshair = (W // 2, H // 2)
        self.mouse_fired = False
        self.message = None
        self.start_stage(0)
        self.set_state("TITLE")

    # ------------------------------------------------------------------
    # State / stage management
    # ------------------------------------------------------------------

    def _build_scanlines(self) -> pygame.Surface:
        surf = pygame.Surface((W, H), pygame.SRCALPHA)
        for y in range(0, H, 2):
            pygame.draw.line(surf, (0, 0, 0, 60), (0, y), (W, y))
        # Subtle blue chroma every 6 lines
        for y in range(0, H, 6):
            pygame.draw.line(surf, (0, 40, 80, 30), (0, y + 1), (W, y + 1))
        return surf

    def _build_vignette(self) -> pygame.Surface:
        surf = pygame.Surface((W, H), pygame.SRCALPHA)
        cx, cy = W / 2, H / 2
        maxd = math.hypot(cx, cy)
        # Per-pixel radial darken (cached once, so cost is acceptable)
        for y in range(0, H, 2):
            for x in range(0, W, 2):
                d = math.hypot(x - cx, y - cy) / maxd
                a = int(max(0.0, (d - 0.55)) * 240)
                a = min(180, a)
                if a > 0:
                    surf.set_at((x, y), (0, 0, 0, a))
                    if x + 1 < W:
                        surf.set_at((x + 1, y), (0, 0, 0, a))
                    if y + 1 < H:
                        surf.set_at((x, y + 1), (0, 0, 0, a))
                        if x + 1 < W:
                            surf.set_at((x + 1, y + 1), (0, 0, 0, a))
        return surf

    def set_state(self, s: str) -> None:
        self.state = s
        self.state_t = 0.0
        # Hide the OS cursor only while the bonus stage is active
        pygame.mouse.set_visible(s != "BONUS")

    def shake(self, amp: float) -> None:
        self.shake_t = 0.25
        self.shake_amp = max(self.shake_amp, amp)

    def start_stage(self, idx: int) -> None:
        self.stage_index = idx
        self.stage = self.stages[idx]
        self.bullets.clear()
        self.enemies.clear()
        self.powerups.clear()
        self.sparks.clear()
        self.delayed.clear()
        self.spawned.clear()
        self.boss_spawned = False
        self.cam_x = 0.0
        self.player.x = 60
        self.player.y = GROUND_Y
        self.player.vx = 0
        self.player.vy = 0
        self.player.alive = True
        self.player.iframes = 1.0
        self.stage_timer = 200.0
        self.set_state("STAGE_INTRO")

    def start_bonus(self) -> None:
        self.bonus_targets = []
        self.bonus_t = 0.0
        self.bonus_score = 0
        # Generate 8 hostage scenes
        for i in range(8):
            criminal_x = random.randint(80, W - 100)
            civilian_x = criminal_x + random.choice([-50, 50])
            civilian_x = max(60, min(W - 60, civilian_x))
            self.bonus_targets.append({
                "t_appear": i * 1.6 + 0.6,
                "duration": 1.4,
                "criminal_x": criminal_x,
                "civilian_x": civilian_x,
                "y": H // 2 + 20,
                "resolved": False,
                "hit_criminal": False,
                "hit_civilian": False,
            })
        self.set_state("BONUS")

    def _explode(self, x: float, y: float, colour: tuple[int, int, int],
                 big: bool = False) -> None:
        n = 20 if big else 8
        for _ in range(n):
            self.sparks.append(Spark(x,
                                     y - 6,
                                     random.uniform(-160, 160),
                                     random.uniform(-180, -40),
                                     random.uniform(0.4, 0.9),
                                     random.choice([colour, YELLOW, WHITE])))
        if big:
            self.shake(5)
            self.audio.play("explode")

    def spawn_enemy_bullet(self, x: float, y: float, vx: float, vy: float,
                           colour: tuple[int, int, int] = RED,
                           gravity: bool = False) -> None:
        if gravity:
            b = Bullet(x, y, vx, vy, friendly=False, damage=2, life=3.0,
                       colour=ORANGE, size=3, gravity=True)
        else:
            b = Bullet(x, y, vx, vy, friendly=False, colour=colour)
        self.bullets.append(b)

    # ------------------------------------------------------------------
    # Input
    # ------------------------------------------------------------------

    def handle_event(self, ev: pygame.event.Event) -> None:
        if ev.type == pygame.QUIT:
            pygame.quit()
            sys.exit()
        if ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_ESCAPE:
                if self.state == "PLAY":
                    self.set_state("PAUSE")
                elif self.state == "PAUSE":
                    self.set_state("PLAY")
                elif self.state == "TITLE":
                    pygame.quit()
                    sys.exit()
            if ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                if self.state == "TITLE":
                    self.start_stage(0)
                elif self.state == "STAGE_INTRO":
                    self.set_state("PLAY")
                elif self.state == "STAGE_CLEAR":
                    self._advance_stage()
                elif self.state == "BONUS_INTRO":
                    self.start_bonus()
                elif self.state == "BONUS_RESULT":
                    self._advance_stage()
                elif self.state == "GAME_OVER":
                    self.reset_run()
                elif self.state == "ENDING":
                    self.reset_run()
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            if self.state == "BONUS":
                self.mouse_fired = True

    def _advance_stage(self) -> None:
        if self.stage.bonus_after and self.state != "BONUS_RESULT":
            self.set_state("BONUS_INTRO")
            return
        if self.stage_index + 1 < len(self.stages):
            self.start_stage(self.stage_index + 1)
        else:
            self.set_state("ENDING")

    def read_keys(self) -> None:
        keys = pygame.key.get_pressed()
        self.input["left"] = keys[pygame.K_LEFT] or keys[pygame.K_a]
        self.input["right"] = keys[pygame.K_RIGHT] or keys[pygame.K_d]
        self.input["down"] = keys[pygame.K_DOWN] or keys[pygame.K_s]
        self.input["jump"] = keys[pygame.K_z] or keys[pygame.K_LSHIFT] or keys[pygame.K_UP] or keys[pygame.K_w]
        self.input["shoot"] = keys[pygame.K_SPACE]

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def update(self, dt: float) -> None:
        self.state_t += dt
        if self.shake_t > 0:
            self.shake_t -= dt
            if self.shake_t <= 0:
                self.shake_amp = 0
        if self.weapon_flash:
            kind, t = self.weapon_flash
            t -= dt
            self.weapon_flash = (kind, t) if t > 0 else None
        if self.message:
            txt, t = self.message
            t -= dt
            self.message = (txt, t) if t > 0 else None

        if self.state == "PLAY":
            self._update_play(dt)
        elif self.state == "BONUS":
            self._update_bonus(dt)

    def _update_play(self, dt: float) -> None:
        self.stage_timer -= dt
        if self.stage_timer <= 0 and self.player.alive:
            self.player.take_hit(99, self)

        self.player.update(dt, self, self.input)

        # Camera scrolls forward only
        target_cam = self.player.x - W * 0.35
        target_cam = max(self.cam_x, target_cam)  # forward only
        target_cam = max(0, min(target_cam, self.stage.length - W))
        self.cam_x += (target_cam - self.cam_x) * min(1.0, dt * 4)

        # Spawn enemies near camera
        for i, sp in enumerate(self.stage.spawns):
            if i in self.spawned:
                continue
            if sp.x < self.cam_x + W + 40:
                sp.fn(self)
                self.spawned.add(i)

        # Boss
        if (self.stage.boss and not self.boss_spawned
                and self.cam_x >= self.stage.length - W - 1):
            self.boss_spawned = True
            bx = self.stage.length - 100
            self.enemies.append(Enemy(bx, GROUND_Y, self.stage.boss))
            self.message = (f"!!! {self.stage.boss.upper()} !!!", 2.0)

        # Delayed callbacks
        still: list[tuple[float, Callable[[], None]]] = []
        for t, fn in self.delayed:
            t -= dt
            if t <= 0:
                fn()
            else:
                still.append((t, fn))
        self.delayed = still

        # Bullets
        for b in self.bullets:
            b.x += b.vx * dt
            b.y += b.vy * dt
            if b.gravity:
                b.vy += 380 * dt
                # Explode on ground impact
                if b.y >= GROUND_Y:
                    b.life = 0
                    self._explode(b.x, GROUND_Y, ORANGE, big=True)
                    if (self.player.alive
                            and abs(self.player.x - b.x) < 26
                            and abs(self.player.y - GROUND_Y) < 30):
                        self.player.take_hit(b.damage, self)
            b.life -= dt
        self.bullets = [b for b in self.bullets if b.life > 0
                        and -50 < (b.x - self.cam_x) < W + 50
                        and b.y < GROUND_Y + 10]

        # Bullet collisions
        for b in self.bullets:
            if b.friendly:
                for e in self.enemies:
                    if e.dead:
                        continue
                    eid = id(e)
                    if b.pierce and eid in b.hit_ids:
                        continue
                    if e.rect.collidepoint(b.x, b.y):
                        e.hit(b.damage, self)
                        if b.pierce:
                            b.hit_ids.add(eid)
                        else:
                            b.life = 0
                            break
            else:
                if self.player.alive and self.player.rect.collidepoint(b.x, b.y):
                    self.player.take_hit(b.damage, self)
                    b.life = 0

        # Enemies
        for e in self.enemies:
            if not e.dead:
                e.update(dt, self)
        self.enemies = [e for e in self.enemies if not e.dead]

        # Power-ups
        picked = []
        for p in self.powerups:
            if self.player.alive and self.player.rect.colliderect(p.rect):
                self.player.pick_weapon(p.kind, self)
                picked.append(p)
        for p in picked:
            self.powerups.remove(p)

        # Sparks
        for s in self.sparks:
            s.x += s.vx * dt
            s.y += s.vy * dt
            s.vy += 200 * dt
            s.life -= dt
        self.sparks = [s for s in self.sparks if s.life > 0]

        # Stage clear: reached end + no enemies (or boss dead)
        at_end = self.player.x >= self.stage.length - 30
        boss_alive = any(e for e in self.enemies if e.kind in ("boddicker", "ed209"))
        if self.stage.boss:
            if self.boss_spawned and not boss_alive:
                self.audio.play("clear")
                self.score += int(self.stage_timer) * 10
                self.set_state("STAGE_CLEAR")
        else:
            if at_end and not self.enemies:
                self.audio.play("clear")
                self.score += int(self.stage_timer) * 10
                self.set_state("STAGE_CLEAR")

    def _update_bonus(self, dt: float) -> None:
        self.bonus_t += dt
        self.crosshair = pygame.mouse.get_pos()
        cx = self.crosshair[0] // SCALE
        cy = self.crosshair[1] // SCALE

        # Time out expired targets
        for t in self.bonus_targets:
            if t["resolved"]:
                continue
            if self.bonus_t > t["t_appear"] + t["duration"]:
                t["resolved"] = True

        # Process a single shot per click
        if self.mouse_fired:
            self.mouse_fired = False
            self.audio.play("shot")
            for t in self.bonus_targets:
                if t["resolved"]:
                    continue
                if self.bonus_t < t["t_appear"]:
                    continue
                if abs(cx - t["criminal_x"]) < 16 and abs(cy - t["y"] + 16) < 24:
                    t["resolved"] = True
                    t["hit_criminal"] = True
                    self.bonus_score += 500
                    self.score += 500
                    break
                if abs(cx - t["civilian_x"]) < 16 and abs(cy - t["y"] + 16) < 24:
                    t["resolved"] = True
                    t["hit_civilian"] = True
                    self.audio.play("hit")
                    break

        if self.bonus_t > self.bonus_targets[-1]["t_appear"] + self.bonus_targets[-1]["duration"] + 0.6:
            # Result
            saved = sum(1 for t in self.bonus_targets if t["hit_criminal"])
            killed_civ = sum(1 for t in self.bonus_targets if t["hit_civilian"])
            self.bonus_summary = (saved, killed_civ)
            if saved == len(self.bonus_targets) and killed_civ == 0:
                self.player.hp = min(self.player.max_hp, self.player.hp + 2)
            self.set_state("BONUS_RESULT")

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def draw(self) -> None:
        s = self.screen
        if self.state == "TITLE":
            self._draw_title(s)
        elif self.state == "STAGE_INTRO":
            self._draw_stage_intro(s)
        elif self.state in ("PLAY", "PAUSE"):
            self._draw_play(s)
            if self.state == "PAUSE":
                self._draw_centre_text(s, "PAUSED", self.big, WHITE, 0)
                self._draw_centre_text(s, "Press ESC to resume", self.font, CYAN, 30)
        elif self.state == "STAGE_CLEAR":
            self._draw_play(s)
            self._draw_centre_text(s, "STAGE CLEAR", self.big, YELLOW, -20)
            bonus = int(max(0, self.stage_timer) * 10)
            self._draw_centre_text(s, f"TIME BONUS  {bonus}", self.font, WHITE, 10)
            self._draw_centre_text(s, "Press ENTER", self.font, CYAN, 30)
        elif self.state == "BONUS_INTRO":
            self._draw_bonus_intro(s)
        elif self.state == "BONUS":
            self._draw_bonus(s)
        elif self.state == "BONUS_RESULT":
            self._draw_bonus_result(s)
        elif self.state == "GAME_OVER":
            self._draw_game_over(s)
        elif self.state == "ENDING":
            self._draw_ending(s)

        # Vignette + scanlines overlay
        if self.scanline_overlay is not None:
            s.blit(self.scanline_overlay, (0, 0))
        if self.vignette is not None:
            s.blit(self.vignette, (0, 0))

        # Shake
        ox, oy = 0, 0
        if self.shake_t > 0:
            ox = random.randint(-int(self.shake_amp), int(self.shake_amp))
            oy = random.randint(-int(self.shake_amp), int(self.shake_amp))
        scaled = pygame.transform.scale(s, (WIN_W, WIN_H))
        self.window.fill(BLACK)
        self.window.blit(scaled, (ox * SCALE, oy * SCALE))
        pygame.display.flip()

    def _draw_centre_text(self, surf, text, font, colour, dy=0) -> None:
        img = font.render(text, False, colour)
        surf.blit(img, (W // 2 - img.get_width() // 2, H // 2 - img.get_height() // 2 + dy))

    def _draw_title(self, s: pygame.Surface) -> None:
        # Animated gradient background
        gradient_rect(s, pygame.Rect(0, 0, W, H), (5, 8, 25), (25, 10, 45))
        # Distant city silhouette
        for i in range(0, W, 30):
            bh = 40 + ((i * 7) % 80)
            pygame.draw.rect(s, (15, 18, 35), (i, H - 60 - bh, 28, bh + 60))
            for wy in range(H - 60 - bh + 6, H - 70, 8):
                if ((i + wy) // 8) % 3 == 0:
                    pygame.draw.rect(s, (180, 200, 240), (i + 6, wy, 2, 3))
                    pygame.draw.rect(s, (240, 200, 100), (i + 16, wy, 2, 3))
        # Grid floor (perspective)
        horizon = H - 80
        for i in range(-10, 11):
            xtop = W // 2 + i * 30
            xbot = W // 2 + i * 180
            pygame.draw.line(s, (40, 100, 180), (xtop, horizon), (xbot, H))
        for j in range(1, 9):
            y = horizon + j * j * 1.4
            pygame.draw.line(s, (40, 100, 180), (0, int(y)), (W, int(y)))

        # ROBOCOP title with strong glow
        title = self.huge.render("ROBOCOP", False, CYAN)
        # Soft horizontal glow band behind the title
        band = pygame.Surface((title.get_width() + 80, title.get_height() + 24),
                              pygame.SRCALPHA)
        for i in range(8, 0, -1):
            a = 18 if i > 4 else 28
            pygame.draw.ellipse(band, (0, 200, 220, a),
                                (8 - i * 2, 8 - i, band.get_width() - 16 + i * 4,
                                 band.get_height() - 16 + i * 2))
        s.blit(band, (W // 2 - band.get_width() // 2, 20))
        # Shadow layers
        for off in (4, 3, 2):
            t = self.huge.render("ROBOCOP", False, (0, 80, 120))
            s.blit(t, (W // 2 - title.get_width() // 2 + off, 30 + off))
        s.blit(title, (W // 2 - title.get_width() // 2, 28))
        # Magenta underline
        uy = 28 + title.get_height() - 2
        pygame.draw.rect(s, MAGENTA, (W // 2 - title.get_width() // 2,
                                      uy, title.get_width(), 2))

        sub = self.font.render(
            "PYTHON EDITION  -  inspired by Ocean / Data East 1988",
            False, MAGENTA)
        s.blit(sub, (W // 2 - sub.get_width() // 2, 90))

        # Robocop centre with floor light
        rx = W // 2
        ry = H - 70
        # Spotlight
        spot = pygame.Surface((140, 30), pygame.SRCALPHA)
        pygame.draw.ellipse(spot, (60, 220, 240, 80), spot.get_rect())
        s.blit(spot, (rx - 70, ry - 4))
        draw_robocop(s, rx, ry, 1, self.state_t * 0.3, False, False)
        # Side punks (decorative)
        draw_punk(s, rx - 90, ry, self.state_t * 0.3, (180, 60, 60), 1)
        draw_punk(s, rx + 90, ry, self.state_t * 0.3 + 1, (60, 100, 180), -1)

        # Blinking prompt
        if int(self.state_t * 2) % 2 == 0:
            press = self.font.render("PRESS  ENTER  TO  SERVE  THE  PUBLIC  TRUST",
                                     False, YELLOW)
            # Tight glow band behind the text
            pw = press.get_width()
            ph = press.get_height()
            gb = pygame.Surface((pw + 24, ph + 8), pygame.SRCALPHA)
            for i in range(4, 0, -1):
                pygame.draw.rect(gb, (255, 220, 70, 25),
                                 (12 - i * 2, 4 - i, pw + i * 4, ph + i * 2),
                                 border_radius=4)
            s.blit(gb, (W // 2 - gb.get_width() // 2, H - 36))
            s.blit(press, (W // 2 - press.get_width() // 2, H - 32))
        ctrl = self.font.render(
            "ARROWS move  -  SPACE fire  -  Z jump  -  DOWN crouch",
            False, WHITE)
        s.blit(ctrl, (W // 2 - ctrl.get_width() // 2, H - 16))

    def _draw_stage_intro(self, s: pygame.Surface) -> None:
        gradient_rect(s, pygame.Rect(0, 0, W, H), (5, 8, 20), (15, 10, 30))
        # Subtle scan grid
        for y in range(0, H, 8):
            pygame.draw.line(s, (12, 16, 30), (0, y), (W, y))
        # Big stage number with shadow
        big_n = self.huge.render(f"STAGE {self.stage_index + 1}", False, CYAN)
        sh = self.huge.render(f"STAGE {self.stage_index + 1}", False, (0, 80, 100))
        s.blit(sh, (W // 2 - big_n.get_width() // 2 + 3, H // 2 - 67))
        s.blit(big_n, (W // 2 - big_n.get_width() // 2, H // 2 - 70))
        name = self.huge.render(self.stage.name, False, WHITE)
        s.blit(name, (W // 2 - name.get_width() // 2, H // 2 - 20))
        # Underline
        pygame.draw.rect(s, MAGENTA,
                         (W // 2 - name.get_width() // 2,
                          H // 2 - 20 + name.get_height(),
                          name.get_width(), 2))
        # Prime directives panel
        panel_rect = pygame.Rect(W // 2 - 140, H // 2 + 40, 280, 70)
        panel = pygame.Surface(panel_rect.size, pygame.SRCALPHA)
        panel.fill((0, 0, 0, 160))
        s.blit(panel, panel_rect.topleft)
        pygame.draw.rect(s, CYAN, panel_rect, 1)
        dirs = [
            "1. SERVE THE PUBLIC TRUST",
            "2. PROTECT THE INNOCENT",
            "3. UPHOLD THE LAW",
        ]
        for i, d in enumerate(dirs):
            img = self.font.render(d, False, MAGENTA)
            s.blit(img, (panel_rect.x + 14, panel_rect.y + 8 + i * 18))
        if int(self.state_t * 2) % 2 == 0:
            self._draw_centre_text(s, "PRESS ENTER", self.font, YELLOW, 130)

    def _draw_play(self, s: pygame.Surface) -> None:
        far, mid, near = self.stage.palette
        cam = self.cam_x
        stage_id = self.stage_index

        # ---- Sky / atmosphere ----
        sky_top = (max(0, far[0] // 3), max(0, far[1] // 3), max(0, far[2] // 3 + 10))
        sky_bot = far
        gradient_rect(s, pygame.Rect(0, 0, W, GROUND_Y), sky_top, sky_bot)

        # Stars / haze (only stages 0 and 3)
        if stage_id in (0, 3):
            for i in range(40):
                sx = (i * 53 - int(cam * 0.05)) % W
                sy = (i * 17) % (GROUND_Y - 60)
                a = 100 + (i * 31) % 120
                s.set_at((sx, sy), (a, a, min(255, a + 30)))

        # Moon / sun (stage 0 moon, stage 1 sun, stage 2 hazy sun, stage 3 floodlight)
        if stage_id == 0:
            mx = W - 90
            blit_glow(s, (mx, 60), 30, (210, 220, 240), alpha=90)
            pygame.draw.circle(s, (230, 230, 240), (mx, 60), 14)
            pygame.draw.circle(s, (200, 200, 215), (mx + 4, 57), 12)
        elif stage_id == 1:
            sx = 90
            blit_glow(s, (sx, 70), 40, (255, 180, 80), alpha=100)
            pygame.draw.circle(s, (255, 220, 130), (sx, 70), 16)
        elif stage_id == 2:
            blit_glow(s, (W - 100, 80), 50, (255, 160, 80), alpha=90)
            pygame.draw.circle(s, (240, 160, 90), (W - 100, 80), 18)

        # ---- Far skyline (parallax 0.15) ----
        for i in range(-1, W // 28 + 4):
            bx = i * 36 - int(cam * 0.15) % 36
            bh = 60 + ((i * 17) % 50)
            top_y = GROUND_Y - bh - 30
            col = (mid[0] // 3, mid[1] // 3, mid[2] // 3 + 10)
            pygame.draw.rect(s, col, (bx, top_y, 32, bh + 30))
            # antenna
            if i % 3 == 0:
                pygame.draw.line(s, col, (bx + 16, top_y), (bx + 16, top_y - 8))
                pygame.draw.circle(s, RED, (bx + 16, top_y - 8), 1)

        # ---- Mid skyline (parallax 0.35) with lit windows ----
        for i in range(-1, W // 40 + 4):
            bx = i * 56 - int(cam * 0.35) % 56
            bh = 80 + ((i * 13) % 70)
            top_y = GROUND_Y - bh - 12
            colb = tuple(int(c * 0.55) for c in mid)
            pygame.draw.rect(s, colb, (bx, top_y, 48, bh + 12))
            # roof shadow
            pygame.draw.rect(s, tuple(int(c * 0.35) for c in mid),
                             (bx, top_y, 48, 3))
            # lit windows
            for wy in range(top_y + 8, GROUND_Y - 12, 8):
                for wx in range(bx + 4, bx + 44, 8):
                    if ((wx + wy + i) * 7) % 11 < 4:
                        wcol = (255, 220, 120) if ((wx * wy) % 5) else (200, 210, 240)
                        pygame.draw.rect(s, wcol, (wx, wy, 3, 4))

        # ---- Near foreground silhouettes (parallax 0.6) ----
        for i in range(-1, W // 70 + 3):
            bx = i * 110 - int(cam * 0.6) % 110
            bh = 50 + ((i * 23) % 40)
            top_y = GROUND_Y - bh
            colb = tuple(int(c * 0.4) for c in near)
            pygame.draw.rect(s, colb, (bx, top_y, 90, bh))
            # Neon signs (stage-dependent)
            if i % 2 == 0:
                sign_col = (CYAN if stage_id == 0 else MAGENTA
                            if stage_id == 1 else YELLOW if stage_id == 2 else CYAN)
                pygame.draw.rect(s, sign_col, (bx + 20, top_y + 12, 30, 6))
                blit_glow(s, (bx + 35, top_y + 15), 14, sign_col, alpha=140)
            for wy in range(top_y + 4, GROUND_Y - 4, 6):
                for wx in range(bx + 2, bx + 88, 6):
                    if ((wx + wy) // 6 + i) % 4 == 0:
                        pygame.draw.rect(s, (255, 200, 80), (wx, wy, 2, 3))

        # ---- Ground ----
        gradient_rect(s, pygame.Rect(0, GROUND_Y, W, H - GROUND_Y),
                      (35, 38, 50), (12, 14, 22))
        # Floor reflection of skyline (very faint)
        for i in range(-1, W // 50 + 3):
            bx = i * 56 - int(cam * 0.35) % 56
            colb = tuple(int(c * 0.18) for c in mid)
            pygame.draw.rect(s, colb, (bx, GROUND_Y + 1, 48, 6))
        # Lane lines / road markings
        for i in range(-1, W // 22 + 2):
            x = i * 28 - int(cam) % 28
            pygame.draw.rect(s, (220, 200, 60), (x, GROUND_Y + 18, 14, 2))
        # Curb
        pygame.draw.line(s, (90, 95, 110), (0, GROUND_Y), (W, GROUND_Y))
        pygame.draw.line(s, (160, 165, 180), (0, GROUND_Y + 1), (W, GROUND_Y + 1))

        # Rain (stage 0 + 3) — deterministic streaks falling
        if stage_id in (0, 3):
            t = self.state_t
            for i in range(80):
                base_x = (i * 71) % W
                base_y = (i * 53) % H
                rx = int((base_x - cam * 0.4) % W)
                ry = int((base_y + t * 400) % H)
                pygame.draw.line(s, (160, 180, 220),
                                 (rx, ry), (rx - 2, ry + 6))
        # Dust / embers (stage 1 + 2)
        elif stage_id in (1, 2):
            for i in range(30):
                rx = (i * 47 - int(self.state_t * 30)) % W
                ry = (i * 31 + int(math.sin(self.state_t + i) * 10)) % GROUND_Y
                col = (255, 180, 80) if stage_id == 2 else (180, 200, 200)
                s.set_at((rx, ry), col)

        # ---- Power-ups (glowing crates) ----
        for p in self.powerups:
            sx = int(p.x - cam)
            sy = int(p.y)
            bob = int(math.sin(self.state_t * 4 + p.x) * 2)
            col = {
                WEAPON_TRIPLE: CYAN, WEAPON_RAPID: WHITE,
                WEAPON_COBRA: ORANGE, "health": GREEN,
            }.get(p.kind, YELLOW)
            blit_glow(s, (sx, sy - 6 + bob), 12, col, alpha=160)
            pygame.draw.rect(s, (30, 30, 40), (sx - 7, sy - 13 + bob, 14, 13))
            pygame.draw.rect(s, col, (sx - 6, sy - 12 + bob, 12, 11))
            pygame.draw.rect(s, WHITE, (sx - 6, sy - 12 + bob, 12, 2))
            pygame.draw.rect(s, tuple(max(0, c - 80) for c in col),
                             (sx - 6, sy - 4 + bob, 12, 2))
            label = {WEAPON_TRIPLE: "3", WEAPON_RAPID: "R",
                     WEAPON_COBRA: "C", "health": "+"}.get(p.kind, "?")
            img = self.font.render(label, False, BLACK)
            s.blit(img, (sx - img.get_width() // 2, sy - 11 + bob))

        # ---- Enemies ----
        for e in self.enemies:
            e.draw(s, int(cam))

        # ---- Bullets with glow trail ----
        for b in self.bullets:
            bx = int(b.x - cam)
            by = int(b.y)
            if b.friendly:
                # Trail
                for i in range(1, 5):
                    tx = bx - int(b.vx * 0.002 * i)
                    ty = by - int(b.vy * 0.002 * i)
                    a = 200 - i * 40
                    blit_glow(s, (tx, ty), 3, b.colour, alpha=a)
                blit_glow(s, (bx, by), 6, b.colour, alpha=220)
                pygame.draw.rect(s, WHITE, (bx - 1, by - 1, 2, 2))
            else:
                blit_glow(s, (bx, by), 5, b.colour, alpha=180)
                pygame.draw.rect(s, b.colour, (bx - 1, by - 1, 3, 3))

        # ---- Player ----
        if self.player.alive:
            px = int(self.player.x - cam)
            py = int(self.player.y)
            draw_robocop(s, px, py,
                         self.player.facing, self.player.phase,
                         self.player.crouching, self.player.iframes > 0)
            # Muzzle flash
            if self.player.muzzle_t > 0:
                mf = self.player.facing
                muz_y = py - (16 if self.player.crouching else 22)
                muz_x = px + mf * 22
                blit_glow(s, (muz_x, muz_y), 10, YELLOW, alpha=220)
                pygame.draw.polygon(s, WHITE, [
                    (muz_x, muz_y), (muz_x + mf * 6, muz_y - 2),
                    (muz_x + mf * 8, muz_y), (muz_x + mf * 6, muz_y + 2)])
            # Punch shockwave
            if self.player.punch_t > 0:
                t = self.player.punch_t / 0.35
                radius = int((1 - t) * 10) + 3
                ring = pygame.Surface((radius * 2 + 4, radius * 2 + 4), pygame.SRCALPHA)
                pygame.draw.circle(ring, (255, 255, 255, int(220 * t)),
                                   (radius + 2, radius + 2), radius, 2)
                fx = px + self.player.facing * 16
                fy = py - 22
                s.blit(ring, (fx - radius - 2, fy - radius - 2))

        # ---- Sparks (multi-pixel with fade) ----
        for sp in self.sparks:
            sx = int(sp.x - cam)
            sy = int(sp.y)
            life_n = max(0.0, min(1.0, sp.life * 1.5))
            size = 1 + int(life_n * 2)
            blit_glow(s, (sx, sy), 4, sp.colour, alpha=int(life_n * 200))
            pygame.draw.rect(s, sp.colour, (sx, sy, size, size))

        # ---- HUD ----
        self._draw_hud(s)

    def _draw_hud(self, s: pygame.Surface) -> None:
        # Top bar (translucent)
        bar = pygame.Surface((W, 30), pygame.SRCALPHA)
        bar.fill((6, 10, 18, 200))
        s.blit(bar, (0, 0))
        pygame.draw.line(s, CYAN, (0, 30), (W, 30))
        pygame.draw.line(s, (30, 60, 90), (0, 31), (W, 31))

        # Health label + segmented bar with glow
        lbl = self.font.render("HEALTH", False, CYAN)
        s.blit(lbl, (8, 4))
        for i in range(self.player.max_hp):
            x = 8 + i * 14
            y = 16
            if i < self.player.hp:
                c = (235, 50, 60) if i < 2 else (255, 180, 60) if i < 4 else (60, 230, 110)
                blit_glow(s, (x + 5, y + 4), 6, c, alpha=140)
                pygame.draw.rect(s, c, (x, y, 11, 9))
                pygame.draw.rect(s, WHITE, (x, y, 11, 2))
            else:
                pygame.draw.rect(s, (35, 38, 50), (x, y, 11, 9))
                pygame.draw.rect(s, (60, 65, 80), (x, y, 11, 1))

        # Stage name with subtle glow
        name = self.stage.name
        img = self.big.render(name, False, WHITE)
        sx = W // 2 - img.get_width() // 2
        blit_glow(s, (W // 2, 10), 30, CYAN, alpha=80)
        s.blit(img, (sx, 2))

        # Timer
        t = max(0, int(self.stage_timer))
        col = YELLOW if t > 30 else RED
        timg = self.font.render(f"TIME {t:03d}", False, col)
        s.blit(timg, (W // 2 - timg.get_width() // 2, 20))

        # Score / lives (right side)
        sc = self.big.render(f"{self.score:06d}", False, YELLOW)
        s.blit(sc, (W - sc.get_width() - 8, 2))
        lv = self.font.render(f"LIVES x{self.player.lives}", False, WHITE)
        s.blit(lv, (W - lv.get_width() - 8, 20))

        # Weapon panel (top-left under health)
        wp_y = 36
        pygame.draw.rect(s, (10, 14, 24), (4, wp_y, 110, 16))
        pygame.draw.rect(s, CYAN, (4, wp_y, 110, 16), 1)
        wp_col = {WEAPON_AUTO9: WHITE, WEAPON_TRIPLE: CYAN,
                  WEAPON_RAPID: YELLOW, WEAPON_COBRA: ORANGE}[self.player.weapon]
        wp = self.font.render(self.player.weapon, False, wp_col)
        s.blit(wp, (10, wp_y + 3))
        # Weapon timer bar
        if self.player.weapon != WEAPON_AUTO9:
            f = max(0.0, self.player.weapon_t / WEAPON_DURATION)
            pygame.draw.rect(s, (40, 40, 60), (70, wp_y + 5, 36, 6))
            pygame.draw.rect(s, wp_col, (70, wp_y + 5, int(36 * f), 6))

        # Weapon flash announcement
        if self.weapon_flash:
            kind, t = self.weapon_flash
            if int(t * 6) % 2 == 0:
                img = self.huge.render(kind, False, YELLOW)
                blit_glow(s, (W // 2, 80), 40, YELLOW, alpha=160)
                s.blit(img, (W // 2 - img.get_width() // 2, 60))
        if self.message:
            txt, t = self.message
            if int(t * 4) % 2 == 0:
                img = self.big.render(txt, False, RED)
                blit_glow(s, (W // 2, 110), 40, RED, alpha=160)
                s.blit(img, (W // 2 - img.get_width() // 2, 100))

    def _draw_bonus_intro(self, s: pygame.Surface) -> None:
        s.fill(BLACK)
        self._draw_centre_text(s, "HOSTAGE RESCUE", self.big, CYAN, -40)
        lines = [
            "Criminals are taking hostages.",
            "Shoot the CRIMINAL (red), not the CIVILIAN (white).",
            "Mouse to aim, left-click to fire.",
            "",
            "PRESS ENTER",
        ]
        for i, ln in enumerate(lines):
            img = self.font.render(ln, False, WHITE if i != 4 else YELLOW)
            s.blit(img, (W // 2 - img.get_width() // 2, 130 + i * 14))

    def _draw_bonus(self, s: pygame.Surface) -> None:
        gradient_rect(s, pygame.Rect(0, 0, W, H), (15, 8, 25), (40, 18, 50))
        # First-person alley perspective
        pygame.draw.polygon(s, (25, 18, 35),
                            [(0, 0), (W, 0), (W - 80, H), (80, H)])
        # Side walls bricks
        for y in range(0, H, 14):
            for x in range(0, 80, 16):
                pygame.draw.rect(s, (50, 28, 60), (x + (y // 14) % 2 * 8, y, 14, 12))
                pygame.draw.rect(s, (80, 45, 95), (x + (y // 14) % 2 * 8, y, 14, 1))
        for y in range(0, H, 14):
            for x in range(W - 80, W, 16):
                pygame.draw.rect(s, (50, 28, 60), (x + (y // 14) % 2 * 8, y, 14, 12))
                pygame.draw.rect(s, (80, 45, 95), (x + (y // 14) % 2 * 8, y, 14, 1))
        # Floor
        gradient_rect(s, pygame.Rect(80, H - 80, W - 160, 80),
                      (40, 25, 50), (10, 8, 20))
        pygame.draw.rect(s, (60, 40, 70), (80, H - 80, W - 160, 2))
        # Streetlamp glow
        blit_glow(s, (W // 2, 20), 60, (255, 220, 130), alpha=140)
        pygame.draw.rect(s, (200, 180, 100), (W // 2 - 2, 0, 4, 12))

        # Targets
        for t in self.bonus_targets:
            if t["resolved"]:
                continue
            if self.bonus_t < t["t_appear"]:
                continue
            if self.bonus_t > t["t_appear"] + t["duration"]:
                continue
            cy = t["y"]
            cx_civ = t["civilian_x"]
            cx_cri = t["criminal_x"]
            # Civilian (white shirt, scared)
            sh = pygame.Surface((22, 5), pygame.SRCALPHA)
            pygame.draw.ellipse(sh, (0, 0, 0, 130), sh.get_rect())
            s.blit(sh, (cx_civ - 11, cy + 4))
            pygame.draw.rect(s, (30, 30, 35), (cx_civ - 5, cy - 14, 10, 14))
            pygame.draw.rect(s, WHITE, (cx_civ - 6, cy - 26, 12, 14))
            pygame.draw.rect(s, (220, 200, 170), (cx_civ - 4, cy - 34, 8, 8))
            pygame.draw.rect(s, (180, 140, 100), (cx_civ - 4, cy - 36, 8, 3))
            # Hands up
            pygame.draw.rect(s, (220, 200, 170), (cx_civ - 8, cy - 36, 3, 6))
            pygame.draw.rect(s, (220, 200, 170), (cx_civ + 5, cy - 36, 3, 6))

            # Criminal (red, with gun)
            sh2 = pygame.Surface((22, 5), pygame.SRCALPHA)
            pygame.draw.ellipse(sh2, (0, 0, 0, 130), sh2.get_rect())
            s.blit(sh2, (cx_cri - 11, cy + 4))
            pygame.draw.rect(s, (30, 30, 35), (cx_cri - 5, cy - 14, 10, 14))
            pygame.draw.rect(s, (200, 60, 60), (cx_cri - 6, cy - 26, 12, 14))
            pygame.draw.rect(s, (140, 30, 30), (cx_cri - 6, cy - 26, 12, 2))
            pygame.draw.rect(s, (220, 200, 170), (cx_cri - 4, cy - 34, 8, 8))
            pygame.draw.rect(s, (30, 30, 30), (cx_cri - 4, cy - 36, 8, 3))
            # Bandana / mask
            pygame.draw.rect(s, BLACK, (cx_cri - 4, cy - 30, 8, 3))
            # Gun
            facing = 1 if cx_cri < cx_civ else -1
            gx = cx_cri + facing * 6
            pygame.draw.rect(s, (35, 35, 40), (gx, cy - 20, 8, 3))
            pygame.draw.rect(s, (70, 70, 80), (gx, cy - 20, 8, 1))
            # Marker triangle above criminal
            pygame.draw.polygon(s, RED, [(cx_cri, cy - 44), (cx_cri - 4, cy - 50),
                                         (cx_cri + 4, cy - 50)])
            blit_glow(s, (cx_cri, cy - 47), 6, RED, alpha=120)

        # HUD bar
        bar = pygame.Surface((W, 24), pygame.SRCALPHA)
        bar.fill((0, 0, 0, 180))
        s.blit(bar, (0, 0))
        pygame.draw.line(s, CYAN, (0, 24), (W, 24))
        rem = sum(1 for t in self.bonus_targets if not t["resolved"])
        img = self.font.render(f"TARGETS {rem}/{len(self.bonus_targets)}",
                               False, YELLOW)
        s.blit(img, (10, 6))
        sc = self.font.render(f"SCORE {self.score:06d}", False, WHITE)
        s.blit(sc, (W - sc.get_width() - 6, 6))
        # Crosshair (high-tech)
        cx = self.crosshair[0] // SCALE
        cy = self.crosshair[1] // SCALE
        blit_glow(s, (cx, cy), 12, CYAN, alpha=100)
        pygame.draw.circle(s, CYAN, (cx, cy), 10, 1)
        pygame.draw.circle(s, CYAN, (cx, cy), 16, 1)
        pygame.draw.line(s, CYAN, (cx - 18, cy), (cx - 6, cy), 1)
        pygame.draw.line(s, CYAN, (cx + 6, cy), (cx + 18, cy), 1)
        pygame.draw.line(s, CYAN, (cx, cy - 18), (cx, cy - 6), 1)
        pygame.draw.line(s, CYAN, (cx, cy + 6), (cx, cy + 18), 1)
        pygame.draw.rect(s, CYAN, (cx - 1, cy - 1, 2, 2))

    def _draw_bonus_result(self, s: pygame.Surface) -> None:
        s.fill(BLACK)
        saved, civ = getattr(self, "bonus_summary", (0, 0))
        self._draw_centre_text(s, "BONUS RESULT", self.big, CYAN, -50)
        self._draw_centre_text(s, f"CRIMINALS NEUTRALISED  {saved}", self.font, WHITE, -10)
        self._draw_centre_text(s, f"CIVILIANS HIT          {civ}", self.font,
                               RED if civ else WHITE, 10)
        if civ == 0 and saved == len(self.bonus_targets):
            self._draw_centre_text(s, "PERFECT  +HEALTH", self.font, GREEN, 30)
        self._draw_centre_text(s, "PRESS ENTER", self.font, YELLOW, 60)

    def _draw_game_over(self, s: pygame.Surface) -> None:
        gradient_rect(s, pygame.Rect(0, 0, W, H), (20, 0, 0), (5, 0, 5))
        # Animated red sparks
        for i in range(40):
            sx = (i * 53 + int(self.state_t * 80)) % W
            sy = (i * 37 + int(math.sin(self.state_t + i) * 20)) % H
            s.set_at((sx, sy), (180 + (i % 60), 30, 30))
        img = self.huge.render("GAME OVER", False, RED)
        blit_glow(s, (W // 2, H // 2 - 30), 80, RED, alpha=180)
        s.blit(img, (W // 2 - img.get_width() // 2, H // 2 - 60))
        # Broken robocop
        sx = W // 2
        sy = H - 70
        pygame.draw.rect(s, STEEL_DARK, (sx - 18, sy - 6, 36, 6))  # debris
        pygame.draw.rect(s, STEEL_MID, (sx - 14, sy - 12, 12, 6))
        pygame.draw.rect(s, ARMOR_BLUE, (sx + 4, sy - 14, 14, 8))
        pygame.draw.rect(s, VISOR_GLOW if int(self.state_t * 4) % 3 == 0 else (40, 40, 60),
                         (sx - 12, sy - 10, 6, 2))
        sc = self.big.render(f"FINAL SCORE   {self.score:06d}", False, WHITE)
        s.blit(sc, (W // 2 - sc.get_width() // 2, H // 2 + 30))
        if int(self.state_t * 2) % 2 == 0:
            press = self.font.render("PRESS ENTER TO RESTART", False, YELLOW)
            s.blit(press, (W // 2 - press.get_width() // 2, H // 2 + 70))

    def _draw_ending(self, s: pygame.Surface) -> None:
        gradient_rect(s, pygame.Rect(0, 0, W, H), (5, 10, 35), (40, 5, 60))
        # Sunrise glow
        blit_glow(s, (W // 2, H - 90), 120, (255, 180, 80), alpha=120)
        # City silhouette
        for i in range(0, W, 22):
            bh = 40 + ((i * 7) % 80)
            pygame.draw.rect(s, (10, 12, 25), (i, H - 100 - bh, 20, bh + 100))
            for wy in range(H - 100 - bh + 6, H - 110, 8):
                if ((i + wy) // 8) % 4 == 0:
                    pygame.draw.rect(s, (255, 220, 130), (i + 4, wy, 2, 3))

        # Title
        t = self.huge.render("DETROIT IS SAFE", False, CYAN)
        blit_glow(s, (W // 2, 40), 80, CYAN, alpha=150)
        s.blit(t, (W // 2 - t.get_width() // 2, 20))

        # Walking robocop
        px = int(W * 0.3 + (self.state_t * 30) % (W * 0.6))
        # Spotlight follow
        spot = pygame.Surface((140, 30), pygame.SRCALPHA)
        pygame.draw.ellipse(spot, (255, 200, 100, 90), spot.get_rect())
        s.blit(spot, (px - 70, H - 60))
        draw_robocop(s, px, H - 50, 1, self.state_t * 3, False, False)

        # Story text
        lines = [
            "Dick Jones has been brought to justice.",
            "ED-209 lies in pieces at the foot of OCP tower.",
            "The streets are quiet... for now.",
        ]
        for i, ln in enumerate(lines):
            img = self.font.render(ln, False, WHITE)
            s.blit(img, (W // 2 - img.get_width() // 2, 100 + i * 18))
        # Final score
        fs = self.big.render(f"FINAL SCORE   {self.score:06d}", False, YELLOW)
        blit_glow(s, (W // 2, 180), 60, YELLOW, alpha=140)
        s.blit(fs, (W // 2 - fs.get_width() // 2, 170))
        if int(self.state_t * 2) % 2 == 0:
            press = self.font.render("PRESS ENTER", False, MAGENTA)
            s.blit(press, (W // 2 - press.get_width() // 2, 220))

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self) -> None:
        while True:
            dt = self.clock.tick(FPS) / 1000.0
            dt = min(dt, 1 / 30)
            for ev in pygame.event.get():
                self.handle_event(ev)
            self.read_keys()
            self.update(dt)
            self.draw()


def main() -> None:
    Game().run()


if __name__ == "__main__":
    main()
