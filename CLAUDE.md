# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Git Workflow

After completing any meaningful unit of work, commit and push to GitHub so progress is never lost:

```bash
cd shooter
git add <specific files>
git commit -m "short description of what changed and why"
git push
```

- Commit after each feature, bug fix, or logical change — not just at the end of a session
- Use clear, specific commit messages (e.g. `"add dasher enemy type"`, `"fix bullet collision off-by-one"`)
- Always push after committing; local-only commits are at risk

## Running the Projects

No build step required — open HTML files directly in a browser:

- **Main game**: `shooter/index.html`
- **Tic Tac Toe**: `tictactoe.html`

There are no dependencies, package managers, or build tools.

## Repository Structure

- `shooter/` — Primary project: a top-down browser shooter game called **VOID ASSAULT**
- `tictactoe.html` — Standalone secondary game
- `Claude mapper dialog.txt` — Original project requirements

## Shooter Game Architecture

The game is pure vanilla JavaScript + HTML5 Canvas, split across four files:

| File | Responsibility |
|------|---------------|
| `game.js` | Main game loop, scene manager, input handling, collision detection, upgrade system |
| `entities.js` | Player, Bullet, Enemy subclasses, Particle, DeathEffect, Starfield |
| `sprites.js` | All rendering — procedural pixel-art drawn with canvas `fillRect` |
| `levels.js` | Level definitions and `WaveManager` (enemy spawning progression) |

### Scene State Machine

`game.js` manages three scenes: `MENU → GAME → GAMEOVER`, routing `update()` and `draw()` calls based on current state.

### Entity Types

- **Player**: Mouse-aimed, WASD/arrow movement, upgradeable fire rate/speed/damage
- **Enemies**: Grunt (fast/weak), Tank (slow/tanky), Dasher (erratic movement), Shooter (ranged, maintains distance)
- **Bullets**: Owned by player or enemy; straight-line physics with lifetime culling

### Level & Wave System

`levels.js` defines 4 story levels plus an endless mode. `WaveManager` controls spawn timing, wave transitions, and level-complete detection. Endless mode scales difficulty exponentially per wave.

### Upgrade System

Between waves, the player picks one of 3 random upgrades: Speed Up, Rapid Fire, Tank Up, Power Shot.

### Persistence

`localStorage` stores high score (`voidAssaultHiScore`) and unlocked levels (`voidAssaultUnlocked`).

### Controls

- **Move**: WASD or Arrow Keys
- **Aim**: Mouse
- **Shoot**: Mouse click / hold

## Environment

- Primary OS: Windows (PowerShell)
- Python and Node.js may not be installed; prefer PowerShell-native solutions for local servers
- Use `Start-Process` or PowerShell HTTP listener for serving files locally

## Historical Map Project (Mapper)

- This is a VB-to-web conversion of a historical map viewer
- Uses PAR files for geodata; keys may contain apostrophes — always escape special characters in JS strings
- Border rendering should use POL segments as open polylines (not polygon strokes) to match original VB behavior
- Coastlines and borders are separate concepts — never conflate them

## UI / Frontend Conventions

- When adding new input methods, preserve existing UI controls (e.g., dropdowns) unless explicitly told to remove them
- For map navigation: use viewport-relative values for pan/zoom, not fixed degree amounts
- After any rendering change, verify that existing features (coastlines, country identification, color mapping) still work
