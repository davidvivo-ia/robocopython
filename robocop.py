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

W, H = 480, 270
SCALE = 2
WIN_W, WIN_H = W * SCALE, H * SCALE
FPS = 60
GROUND_Y = H - 40

# Spectrum-ish palette
BLACK = (0, 0, 0)
WHITE = (235, 235, 235)
CYAN = (0, 220, 220)
MAGENTA = (220, 0, 220)
YELLOW = (235, 220, 0)
RED = (220, 30, 30)
GREEN = (30, 200, 60)
BLUE = (40, 90, 220)
DARK = (15, 18, 30)
GREY = (110, 110, 120)
ORANGE = (240, 140, 30)

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

def draw_robocop(surf: pygame.Surface, x: int, y: int, facing: int,
                 walking_phase: float, crouching: bool, flicker: bool) -> None:
    """Draw RoboCop as composite rectangles. (x, y) is feet-centre."""
    if flicker and int(walking_phase * 20) % 2 == 0:
        return
    body_col = (190, 195, 205)
    visor_col = CYAN
    accent = BLUE
    h = 22 if crouching else 30
    top = y - h
    # Legs
    leg_off = int(math.sin(walking_phase * 8) * 2) if not crouching else 0
    pygame.draw.rect(surf, body_col, (x - 5, y - 10, 4, 10 - (8 if crouching else 0)))
    pygame.draw.rect(surf, body_col, (x + 1, y - 10, 4, 10 - (8 if crouching else 0)))
    if not crouching:
        pygame.draw.rect(surf, body_col, (x - 5, y - 10 - leg_off, 4, 2))
        pygame.draw.rect(surf, body_col, (x + 1, y - 10 + leg_off, 4, 2))
    # Torso
    pygame.draw.rect(surf, body_col, (x - 6, top + 6, 12, h - 12))
    pygame.draw.rect(surf, accent, (x - 6, top + 6, 12, 2))
    # Head/helmet
    pygame.draw.rect(surf, body_col, (x - 5, top, 10, 7))
    # Visor
    pygame.draw.rect(surf, visor_col, (x - 4, top + 2, 8, 2))
    # Arm with gun
    arm_y = top + 8 if not crouching else top + 6
    if facing >= 0:
        pygame.draw.rect(surf, body_col, (x + 4, arm_y, 5, 3))
        pygame.draw.rect(surf, GREY, (x + 8, arm_y, 5, 2))
    else:
        pygame.draw.rect(surf, body_col, (x - 9, arm_y, 5, 3))
        pygame.draw.rect(surf, GREY, (x - 13, arm_y, 5, 2))


def draw_punk(surf: pygame.Surface, x: int, y: int, phase: float,
              colour: tuple[int, int, int], facing: int) -> None:
    pygame.draw.rect(surf, colour, (x - 4, y - 22, 8, 14))
    pygame.draw.rect(surf, (40, 40, 60), (x - 4, y - 24, 8, 4))  # hair
    leg_off = int(math.sin(phase * 8) * 2)
    pygame.draw.rect(surf, (40, 40, 60), (x - 4, y - 10, 3, 10 - leg_off))
    pygame.draw.rect(surf, (40, 40, 60), (x + 1, y - 10, 3, 10 + leg_off))
    # Gun
    gx = x + (4 if facing >= 0 else -9)
    pygame.draw.rect(surf, GREY, (gx, y - 18, 5, 2))


def draw_ed209(surf: pygame.Surface, x: int, y: int, phase: float) -> None:
    body = (170, 110, 30)
    dark = (90, 60, 15)
    # Legs
    sway = int(math.sin(phase * 4) * 3)
    pygame.draw.rect(surf, dark, (x - 18, y - 24, 8, 24 + sway))
    pygame.draw.rect(surf, dark, (x + 10, y - 24, 8, 24 - sway))
    pygame.draw.polygon(surf, dark, [(x - 22, y), (x - 6, y), (x - 14, y + 4)])
    pygame.draw.polygon(surf, dark, [(x + 6, y), (x + 22, y), (x + 14, y + 4)])
    # Body
    pygame.draw.rect(surf, body, (x - 20, y - 44, 40, 22))
    pygame.draw.rect(surf, dark, (x - 20, y - 44, 40, 4))
    # Head/sensors
    pygame.draw.rect(surf, body, (x - 10, y - 56, 20, 12))
    pygame.draw.rect(surf, RED, (x - 7, y - 52, 4, 3))
    pygame.draw.rect(surf, RED, (x + 3, y - 52, 4, 3))
    # Gun arms
    pygame.draw.rect(surf, dark, (x - 30, y - 38, 12, 6))
    pygame.draw.rect(surf, dark, (x + 18, y - 38, 12, 6))


def draw_boddicker(surf: pygame.Surface, x: int, y: int, phase: float, facing: int) -> None:
    pygame.draw.rect(surf, (60, 60, 80), (x - 6, y - 26, 12, 16))
    pygame.draw.rect(surf, (220, 200, 170), (x - 4, y - 30, 8, 5))  # face
    pygame.draw.rect(surf, (180, 180, 180), (x - 4, y - 31, 8, 2))  # glasses
    leg_off = int(math.sin(phase * 8) * 2)
    pygame.draw.rect(surf, (40, 40, 60), (x - 5, y - 10, 4, 10 - leg_off))
    pygame.draw.rect(surf, (40, 40, 60), (x + 1, y - 10, 4, 10 + leg_off))
    gx = x + (5 if facing >= 0 else -11)
    pygame.draw.rect(surf, GREY, (gx, y - 20, 6, 3))


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
            return pygame.Rect(int(self.x - 22), int(self.y - 56), 44, 56)
        if self.kind == "boddicker":
            return pygame.Rect(int(self.x - 7), int(self.y - 32), 14, 32)
        if self.kind == "drone":
            return pygame.Rect(int(self.x - 10), int(self.y - 8), 20, 16)
        return pygame.Rect(int(self.x - 5), int(self.y - 26), 10, 26)

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
                for i in range(3):
                    game.delayed.append((0.12 * i, lambda fx=self.x + self.facing * 8,
                                          fy=self.y - 16, f=self.facing:
                                         game.spawn_enemy_bullet(fx, fy, f * 180, 0)))
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
            draw_punk(surf, sx, sy, self.phase, self.colour, self.facing)
            pygame.draw.rect(surf, BLACK, (sx - 4, sy - 24, 8, 3))  # helmet band
        elif self.kind == "drone":
            pygame.draw.ellipse(surf, self.colour, (sx - 10, sy - 6, 20, 12))
            pygame.draw.rect(surf, RED, (sx - 2, sy - 1, 4, 2))
            pygame.draw.rect(surf, GREY, (sx - 12, sy - 8, 4, 2))
            pygame.draw.rect(surf, GREY, (sx + 8, sy - 8, 4, 2))
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
    WIDTH = 12
    HEIGHT = 30

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
        muzzle_x = self.x + self.facing * 12
        muzzle_y = self.y - (16 if self.crouching else 18)
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
    return Stage("OCP HQ", 700, palette, [], boss="ed209")


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
        self.font = pygame.font.SysFont("couriernew", 12, bold=True)
        self.big = pygame.font.SysFont("couriernew", 28, bold=True)
        self.huge = pygame.font.SysFont("couriernew", 48, bold=True)
        self.audio = Audio()

        self.state = "TITLE"
        self.state_t = 0.0

        self.player = Player()
        self.bullets: list[Bullet] = []
        self.enemies: list[Enemy] = []
        self.powerups: list[PowerUp] = []
        self.sparks: list[Spark] = []
        self.delayed: list[tuple[float, Callable[[], None]]] = []
        self.cam_x = 0.0
        self.score = 0
        self.shake_t = 0.0
        self.shake_amp = 0.0
        self.weapon_flash: tuple[str, float] | None = None
        self.stage_index = 0
        self.stages = [stage_streets(), stage_factory(), stage_junkyard(), stage_ocp()]
        self.stage = self.stages[0]
        self.spawned: set[int] = set()
        self.boss_spawned = False
        self.stage_timer = 200.0
        self.input = {"left": False, "right": False, "down": False,
                      "jump": False, "shoot": False}
        self.bonus_targets: list[dict] = []
        self.bonus_t = 0.0
        self.bonus_score = 0
        self.crosshair = (W // 2, H // 2)
        self.mouse_fired = False
        self.message: tuple[str, float] | None = None

        self.start_stage(0)

    # ------------------------------------------------------------------
    # State / stage management
    # ------------------------------------------------------------------

    def set_state(self, s: str) -> None:
        self.state = s
        self.state_t = 0.0

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

    def spawn_enemy_bullet(self, x: float, y: float, vx: float, vy: float,
                           colour: tuple[int, int, int] = RED,
                           gravity: bool = False) -> None:
        b = Bullet(x, y, vx, vy, False, colour=colour)
        if gravity:
            b.life = 3.0
            b.size = 3
            b.colour = ORANGE
            b.damage = 2
            b.pierce = False
            b.friendly = False
            # We'll hack gravity in update via special flag — store on attr
            b.size = 3
            setattr(b, "gravity", True)
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
                    self.__init__()
                elif self.state == "ENDING":
                    self.__init__()
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
            if getattr(b, "gravity", False):
                b.vy += 380 * dt
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
                    if e.rect.collidepoint(b.x, b.y):
                        e.hit(b.damage, self)
                        if not b.pierce:
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

        # Activate targets
        for t in self.bonus_targets:
            if t["resolved"]:
                continue
            if self.bonus_t < t["t_appear"]:
                continue
            if self.bonus_t > t["t_appear"] + t["duration"]:
                t["resolved"] = True
                continue
            if self.mouse_fired:
                # Check criminal hit
                if abs(cx - t["criminal_x"]) < 16 and abs(cy - t["y"] + 16) < 24:
                    t["resolved"] = True
                    t["hit_criminal"] = True
                    self.bonus_score += 500
                    self.score += 500
                    self.audio.play("shot")
                elif abs(cx - t["civilian_x"]) < 16 and abs(cy - t["y"] + 16) < 24:
                    t["resolved"] = True
                    t["hit_civilian"] = True
                    self.audio.play("hit")
        if self.mouse_fired:
            self.audio.play("shot")
            self.mouse_fired = False

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
        s.fill(BLACK)
        # Scanline background
        for i in range(0, H, 4):
            pygame.draw.line(s, (10, 10, 25), (0, i), (W, i))
        title = self.huge.render("ROBOCOP", False, CYAN)
        s.blit(title, (W // 2 - title.get_width() // 2, 40))
        sub = self.font.render("PYTHON EDITION  -  inspired by Ocean / Data East 1988",
                               False, MAGENTA)
        s.blit(sub, (W // 2 - sub.get_width() // 2, 90))
        # Big rectangle robocop
        draw_robocop(s, W // 2, 200, 1, self.state_t, False, False)
        # Stats / blink
        if int(self.state_t * 2) % 2 == 0:
            press = self.font.render("PRESS ENTER TO SERVE THE PUBLIC TRUST",
                                     False, YELLOW)
            s.blit(press, (W // 2 - press.get_width() // 2, 230))
        ctrl = self.font.render("ARROWS move  SPACE fire  Z jump  DOWN crouch",
                                False, WHITE)
        s.blit(ctrl, (W // 2 - ctrl.get_width() // 2, 250))

    def _draw_stage_intro(self, s: pygame.Surface) -> None:
        s.fill(BLACK)
        self._draw_centre_text(s, f"STAGE {self.stage_index + 1}", self.big, CYAN, -30)
        self._draw_centre_text(s, self.stage.name, self.huge, WHITE, 10)
        self._draw_centre_text(s, "PRESS ENTER", self.font, YELLOW, 60)
        # Three Prime Directives
        dirs = [
            "1. SERVE THE PUBLIC TRUST",
            "2. PROTECT THE INNOCENT",
            "3. UPHOLD THE LAW",
        ]
        for i, d in enumerate(dirs):
            img = self.font.render(d, False, MAGENTA)
            s.blit(img, (W // 2 - img.get_width() // 2, 200 + i * 14))

    def _draw_play(self, s: pygame.Surface) -> None:
        far, mid, near = self.stage.palette
        s.fill(far)
        # Parallax skyline
        cam = self.cam_x
        for i in range(-1, W // 30 + 2):
            bx = (i * 40 - int(cam * 0.2) % 40)
            pygame.draw.rect(s, mid, (bx, GROUND_Y - 90, 30, 90))
            pygame.draw.rect(s, far, (bx + 6, GROUND_Y - 80, 4, 4))
            pygame.draw.rect(s, far, (bx + 16, GROUND_Y - 70, 4, 4))
        for i in range(-1, W // 50 + 2):
            bx = (i * 60 - int(cam * 0.5) % 60)
            pygame.draw.rect(s, near, (bx, GROUND_Y - 60, 50, 60))
            for wy in range(0, 50, 10):
                pygame.draw.rect(s, mid, (bx + 4, GROUND_Y - 56 + wy, 6, 4))
                pygame.draw.rect(s, mid, (bx + 14, GROUND_Y - 56 + wy, 6, 4))
                pygame.draw.rect(s, mid, (bx + 24, GROUND_Y - 56 + wy, 6, 4))
                pygame.draw.rect(s, mid, (bx + 34, GROUND_Y - 56 + wy, 6, 4))
        # Ground
        pygame.draw.rect(s, (40, 40, 50), (0, GROUND_Y, W, H - GROUND_Y))
        for i in range(-1, W // 16 + 2):
            x = i * 20 - int(cam) % 20
            pygame.draw.line(s, (70, 70, 90), (x, GROUND_Y), (x, H), 1)

        # Power-ups
        for p in self.powerups:
            sx = int(p.x - cam)
            sy = int(p.y)
            bob = int(math.sin(self.state_t * 4 + p.x) * 2)
            col = {
                WEAPON_TRIPLE: CYAN, WEAPON_RAPID: WHITE,
                WEAPON_COBRA: ORANGE, "health": GREEN,
            }.get(p.kind, YELLOW)
            pygame.draw.rect(s, col, (sx - 6, sy - 12 + bob, 12, 12))
            label = {WEAPON_TRIPLE: "3", WEAPON_RAPID: "R",
                     WEAPON_COBRA: "C", "health": "+"}.get(p.kind, "?")
            img = self.font.render(label, False, BLACK)
            s.blit(img, (sx - img.get_width() // 2, sy - 12 + bob))

        # Enemies
        for e in self.enemies:
            e.draw(s, int(cam))

        # Bullets
        for b in self.bullets:
            r = b.rect.move(-int(cam), 0)
            pygame.draw.rect(s, b.colour, r)

        # Player
        if self.player.alive:
            draw_robocop(s, int(self.player.x - cam), int(self.player.y),
                         self.player.facing, self.player.phase,
                         self.player.crouching, self.player.iframes > 0)
            if self.player.punch_t > 0:
                px = int(self.player.x - cam) + self.player.facing * 14
                py = int(self.player.y) - 18
                pygame.draw.circle(s, WHITE, (px, py), 4)

        # Sparks
        for sp in self.sparks:
            pygame.draw.rect(s, sp.colour, (int(sp.x - cam), int(sp.y), 2, 2))

        # HUD
        self._draw_hud(s)

    def _draw_hud(self, s: pygame.Surface) -> None:
        pygame.draw.rect(s, BLACK, (0, 0, W, 18))
        pygame.draw.line(s, CYAN, (0, 18), (W, 18))
        # Health
        for i in range(self.player.max_hp):
            col = RED if i < self.player.hp else (40, 40, 50)
            pygame.draw.rect(s, col, (8 + i * 10, 5, 8, 8))
        # Stage name
        img = self.font.render(self.stage.name, False, WHITE)
        s.blit(img, (W // 2 - img.get_width() // 2, 3))
        # Timer (below stage name)
        t = max(0, int(self.stage_timer))
        timg = self.font.render(f"TIME {t:03d}", False,
                                YELLOW if t > 30 else RED)
        s.blit(timg, (W // 2 - timg.get_width() // 2, 22))
        # Score / lives
        sc = self.font.render(f"SCORE {self.score:06d}  x{self.player.lives}",
                              False, WHITE)
        s.blit(sc, (W - sc.get_width() - 6, 5))
        # Weapon
        wp = self.font.render(f"[{self.player.weapon}]", False, CYAN)
        s.blit(wp, (8, 22))
        if self.weapon_flash:
            kind, t = self.weapon_flash
            if int(t * 6) % 2 == 0:
                img = self.big.render(kind, False, YELLOW)
                s.blit(img, (W // 2 - img.get_width() // 2, 40))
        if self.message:
            txt, t = self.message
            if int(t * 4) % 2 == 0:
                img = self.big.render(txt, False, RED)
                s.blit(img, (W // 2 - img.get_width() // 2, 60))

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
        s.fill((20, 10, 20))
        # First-person room
        pygame.draw.polygon(s, (40, 25, 50),
                            [(0, 0), (W, 0), (W - 60, H), (60, H)])
        pygame.draw.rect(s, (60, 40, 70), (40, H - 60, W - 80, 60))
        # Targets
        for t in self.bonus_targets:
            if t["resolved"]:
                continue
            if self.bonus_t < t["t_appear"]:
                continue
            if self.bonus_t > t["t_appear"] + t["duration"]:
                continue
            cy = t["y"]
            # Civilian
            pygame.draw.rect(s, WHITE, (t["civilian_x"] - 6, cy - 26, 12, 18))
            pygame.draw.rect(s, (220, 200, 170),
                             (t["civilian_x"] - 4, cy - 32, 8, 6))
            # Criminal (behind, with gun)
            pygame.draw.rect(s, (200, 60, 60), (t["criminal_x"] - 6, cy - 26, 12, 18))
            pygame.draw.rect(s, (50, 50, 50),
                             (t["criminal_x"] - 4, cy - 32, 8, 6))
            pygame.draw.rect(s, GREY, (t["criminal_x"] + 5, cy - 18, 6, 2))
        # HUD
        rem = sum(1 for t in self.bonus_targets if not t["resolved"])
        img = self.font.render(f"TARGETS {rem}/{len(self.bonus_targets)}",
                               False, YELLOW)
        s.blit(img, (10, 6))
        sc = self.font.render(f"SCORE {self.score:06d}", False, WHITE)
        s.blit(sc, (W - sc.get_width() - 6, 6))
        # Crosshair
        cx = self.crosshair[0] // SCALE
        cy = self.crosshair[1] // SCALE
        pygame.draw.circle(s, CYAN, (cx, cy), 8, 1)
        pygame.draw.line(s, CYAN, (cx - 12, cy), (cx + 12, cy), 1)
        pygame.draw.line(s, CYAN, (cx, cy - 12), (cx, cy + 12), 1)
        pygame.mouse.set_visible(False)

    def _draw_bonus_result(self, s: pygame.Surface) -> None:
        pygame.mouse.set_visible(True)
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
        s.fill(BLACK)
        self._draw_centre_text(s, "GAME OVER", self.huge, RED, -20)
        self._draw_centre_text(s, f"FINAL SCORE {self.score:06d}", self.font, WHITE, 30)
        if int(self.state_t * 2) % 2 == 0:
            self._draw_centre_text(s, "PRESS ENTER", self.font, YELLOW, 60)

    def _draw_ending(self, s: pygame.Surface) -> None:
        s.fill(BLACK)
        for i in range(0, H, 4):
            pygame.draw.line(s, (5, 10, 25), (0, i), (W, i))
        self._draw_centre_text(s, "DETROIT IS SAFE", self.big, CYAN, -60)
        # Walking robocop
        px = int(W * 0.5 + math.sin(self.state_t * 1.5) * 60)
        draw_robocop(s, px, H - 60, 1, self.state_t * 2, False, False)
        lines = [
            "Dick Jones has been brought to justice.",
            "ED-209 lies in pieces at the foot of OCP tower.",
            "The streets are quiet, for now.",
            "",
            f"FINAL SCORE  {self.score:06d}",
        ]
        for i, ln in enumerate(lines):
            img = self.font.render(ln, False, WHITE if i != 4 else YELLOW)
            s.blit(img, (W // 2 - img.get_width() // 2, 130 + i * 14))
        if int(self.state_t * 2) % 2 == 0:
            self._draw_centre_text(s, "PRESS ENTER", self.font, MAGENTA, 100)

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
