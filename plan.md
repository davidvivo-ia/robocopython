# RoboCop Python — Plan

A side-scrolling run-and-gun in Python (pygame) inspired by the 1988 Data East
arcade and the Ocean Software ZX Spectrum port of *RoboCop*. The game is
self-contained: all graphics are drawn procedurally with primitives, all sound
is synthesised at runtime, so it has no external asset dependencies beyond
`pygame`.

## 1. References used

- Data East arcade *RoboCop* (1988): 7 platforming stages + 2 first-person
  bonus shooting galleries, Auto-9 pistol with rapid-fire / three-way /
  cobra-cannon (flame) power-ups, auto-melee on contact, ED-209 boss fights.
- Ocean Software ZX Spectrum *RoboCop* (1988): Detroit streets, drug factory,
  junkyard, OCP HQ; hostage rescue first-person sub-game; ED-209 must be
  beaten with fists (immune to bullets).

## 2. Tech stack

- Language: Python 3
- Library: `pygame` (only dependency)
- Single-file entry point: `robocop.py`
- Internal resolution: 480 x 270, scaled 2x to a 960 x 540 window
- 60 FPS, fixed timestep update

## 3. Visual style

- Spectrum-inspired flat palette: black background, neon cyan / magenta /
  yellow / white foregrounds with a single highlight colour per stage.
- RoboCop and enemies drawn as composite rectangles (helmet, visor, torso,
  arm/gun, legs) so they animate at runtime without any sprite files.
- Parallax: 3 layers per stage (far skyline, mid buildings, near floor).

## 4. Game states

`TITLE → STAGE_INTRO → PLAY → (HOSTAGE_BONUS) → STAGE_INTRO → ... → ENDING`
plus `GAME_OVER` and `PAUSE`.

State machine lives in `Game.state`; each state has `update(dt)` and
`draw(surface)` methods.

## 5. Player (RoboCop)

- Stats: 6 health bars (shown as a segmented blue/red strip), 3 lives.
- Movement: walk left/right (90 px/s), crouch, jump (short hop — RoboCop is
  heavy), face direction follows last move.
- Shoot: Auto-9 (single shot, fast), three-way (cone), rapid (high RoF),
  cobra (piercing flame) — power-up timed for 12 s.
- Melee: any enemy within 18 px of RoboCop triggers an automatic fist punch
  that one-shots most grunts; this is the only way to damage ED-209.
- I-frames: 1 s after being hit, sprite flickers.

## 6. Enemies

| Name        | Behaviour                                  | HP | Damage |
|-------------|--------------------------------------------|----|--------|
| Street punk | Walks toward player, fires every 1.5 s     | 1  | 1      |
| Heavy thug  | Crouches and fires bursts of 3             | 2  | 1      |
| Drone       | Hovers, dives, drops bombs                 | 2  | 1      |
| Boddicker   | Mid-boss in junkyard, dashes + shotgun     | 8  | 2      |
| ED-209      | End boss, missiles + stomp, bullet-immune  | 6  | 2      |

## 7. Stages

1. **Detroit Streets** — side-scroll, punks + heavy thugs, drops a 3-way
   power-up at the midpoint.
2. **Hostage Bonus** — first-person crosshair; shoot the criminal, spare the
   civilian; +1 health on perfect clear.
3. **Drug Factory** — vertical crates to crouch behind, rapid-fire pickup.
4. **Junkyard** — tight corridor; mid-boss fight with Boddicker.
5. **OCP HQ** — ED-209 boss; bullets bounce off, must close to melee range.
6. **Ending** — text + animated RoboCop walking toward camera.

Each stage has a scroll length (in pixels), a list of (x, spawn) entries
sorted by x, and a fixed end-of-stage trigger.

## 8. HUD

- Top-left: `HEALTH` bar (6 segments).
- Top-centre: stage name + timer (counts down from 200 s — Spectrum-style).
- Top-right: score (6 digits) and lives (`x N`).
- Active weapon name flashes for 1 s when picked up.

## 9. Input

- Arrow keys / WASD: move + crouch
- Space: shoot
- Z / Left-Shift: jump
- Enter: start / advance
- Esc: pause / quit from title
- Mouse: hostage bonus stage aiming, left-click to fire

## 10. Audio

All synthesised with `pygame.sndarray` from `numpy` sine/square waves at game
start, no external `.wav` files:

- Auto-9 shot: short square blip 880 Hz
- Punch: noise burst
- Hit: descending tone
- Power-up: ascending arpeggio
- Stage clear: short jingle
- Title theme: looping 4-bar square-wave melody (Robocop main motif riff)

`numpy` is optional — if missing, the game falls back to silent mode.

## 11. File layout

```
robocop.py        # entry point + game loop + all classes
plan.md           # this file
```

Single-file keeps it portable and matches the spirit of the original
type-in-and-load 8-bit games.

## 12. Implementation order

1. Window + main loop + state stub.
2. Title screen with blinking "PRESS ENTER".
3. Player rectangle + movement + collisions with ground.
4. Bullets + first enemy type.
5. Camera scroll + parallax background.
6. Power-ups + weapon switching.
7. Hostage bonus level.
8. Boss enemies (Boddicker, ED-209).
9. HUD, score, lives, game over.
10. Synthesised audio.
11. Ending sequence.
12. Polish: screen-shake on hits, sparks, muzzle flash.

## 13. Run

```
pip install pygame numpy
python robocop.py
```

`numpy` is optional and only used for synthesised audio.
