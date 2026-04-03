# Karship K# (`ksharp`) - K# First Release

Karship K# is a new language prototype focused on:

- fast, readable coding syntax (mix of Lua/Python simplicity + C/C#/C++ style braces)
- secure-by-default runtime behavior for white-hat development
- practical full-stack helpers (DB, SDK, web payloads, Discord bot simulation)
- reusable library files with `use "hello.ksharp"` style imports
- adaptive memory profiles for weak PCs (8GB) through high-end systems
- multi-platform interpreter support via Python runtime

This repository ships the **K# core** first.  
`K++` and `K` are planned for later versions.

## K# Syntax Snapshot

```ksharp
use "libs/hello.ksharp"
let language = "Karship K#"
spark("Hello from", language)
spark(hello("dev"))

forge add(a, b) {
    return a + b
}

let total = 0
each n in range(1, 5) {
    total = total + n
}
spark("total:", total)

let profile = memory.profile()
spark("mode:", profile["mode"], "ram:", profile["total_ram_gb"], "GB")
```

### New K# Words

- `spark(...)`: output text (K# replacement for `print`)
- `use "path/file.ksharp"`: load a library file once and share functions globally
- `let`: mutable variable
- `lock`: immutable variable (const-safe)
- `forge`: function
- `class` / `new`: object system
- `lambda(a, b) => a + b`: lambda expression
- `each ... in ...`: for-each loop
- `memory.alloc(...)` / `memory.free(...)`: manual memory reservation lifecycle
- `memory.profile()` / `memory.set_mode("eco"|"balanced"|"turbo")`: automatic + manual optimization
- `security.hash(...)`: SHA-256 helper
- `db.open(...)`: sqlite database connector
- `discord.create(...)`: bot simulator helper

## Extensions

K# runtime accepts all of these:

- `.ksharp`: full language mode (strict safety + full feature set)
- `.kpp`: performance mode (reduced safety checks for speed)
- `.k`: lightweight scripting mode (imports/classes disabled, reduced runtime surface)

Examples are included:

- `example.ksharp`
- `example.kpp`
- `example.k`

## Quick Start

From repository root:

```bash
python -m ksharp ksharp/example.ksharp
python -m ksharp ksharp/example.kpp
python -m ksharp ksharp/example.k
```

Or install command entrypoint:

```bash
pip install -e .
ksharp ksharp/example.ksharp
kar --version
```

Memory profiles in CLI:

```bash
ksharp --memory-mode auto ksharp/example.ksharp
ksharp --memory-mode eco ksharp/example.kpp
ksharp --memory-mode turbo ksharp/example.k
```

## Kar Ecosystem CLI

Karship now includes a project/workflow CLI:

```bash
kar init .
kar run main.ksharp
kar build
kar mem
kar doctor
kar native
kar install discord.py
kar remove discord.py
kar uninstall discord.py
```

`kar install/remove` supports local project dependencies (tracked in `karship.json`) and global mode via `--global`.

### Native Package Catalog

Karship now ships a larger native `.ksharp` package set for Python/Lua/C++/C# style workflows.

List them anytime:

```bash
kar native
```

Core packages:

- `discord.ksharp` (`discord-ksharp`) - bot + intents + voice command wrappers
- `ytdlp.ksharp` (`ytdlp-ksharp`) - URL/query stream extraction helpers
- `web.ksharp` (`web-ksharp`) - HTTP server and routing helpers
- `db.ksharp` (`db-ksharp`) - sqlite convenience helpers
- `security.ksharp` (`security-ksharp`) - white-hat security helpers
- `game.ksharp` (`game-ksharp`) - game-loop + input helpers
- `anticheat.ksharp` (`anticheat-ksharp`) - event + memory scan helpers
- `sdk.ksharp` (`sdk-ksharp`) - JSON encode/decode helpers
- `system.ksharp` (`system-ksharp`) - hardware/runtime profile helpers
- `memory.ksharp` (`memory-ksharp`) - memory mode + allocation wrappers
- `utils.ksharp` (`utils-ksharp`) - utility helpers (clamp/coalesce/join)
- `collections.ksharp` (`collections-ksharp`) - list operations (`push`, `find`, `copy`)
- `math.ksharp` (`math-ksharp`) - lightweight math helpers
- `devtools.ksharp` (`devtools-ksharp`) - debug/timer/assert helpers

Install examples:

```bash
kar install web.ksharp
kar install db.ksharp
kar install utils.ksharp
kar install collections.ksharp
kar install math.ksharp
```

### discord.ksharp Native Package

Install native Discord helpers for Karship:

```bash
kar init .
kar install discord.ksharp
```

This installs `libs/discord.ksharp` and attempts to install Python bridge dependencies (`discord.py`, `PyNaCl`) for runtime bot + voice support.

Useful commands:

```bash
kar install discord.ksharp --native-only
kar uninstall discord.ksharp
kar uninstall discord.ksharp --global
```

### ytdlp.ksharp Native Package

Install Karship yt-dlp helpers for URL music playback:

```bash
kar install ytdlp.ksharp
```

Use with Discord helpers:

```ksharp
use "discord.ksharp"
use "ytdlp.ksharp"

let bot = discord_create("!")
discord_enable_voice(bot)
discord_music_url(bot, "play")   # supports !play <url> and /play <url>
```

Troubleshooting quick check:

```ksharp
spark(ytdlp_profile())
spark(ytdlp_last_error())
```

Note:
- This package supports legitimate extraction/playback workflows.
- Do not use it to bypass platform protections or violate service terms.

Minimal bot:

```ksharp
use "discord.ksharp"
let bot = discord_create("!")
forge ping_cmd(content) { return "pong" }
discord_command(bot, "ping", ping_cmd)
bot.run("YOUR_BOT_TOKEN")
```

### Permanent Windows Install (PowerShell + CMD)

To make `kar` available forever in new terminals:

```powershell
powershell -ExecutionPolicy Bypass -File tools/install-kar-cli.ps1
```

For all users on the same computer (run PowerShell as Administrator):

```powershell
powershell -ExecutionPolicy Bypass -File tools/install-kar-cli.ps1 -AllUsers
```

## Library Pattern

Create reusable files in your project, for example:

- `ksharp/libs/hello.ksharp`

Then import in any script:

```ksharp
use "libs/hello.ksharp"
spark(hello("world"))
```

Imported modules are cached by runtime, and circular imports are blocked.

## Safe Memory Design

K# auto-detects your machine RAM and picks a recommended mode:

- `eco`: optimized for weaker machines, compact JSON/web outputs, tighter cap
- `balanced`: default middle profile
- `turbo`: higher cap for strong/high-end machines

Manual memory API:

```ksharp
memory.alloc("assets", 64)
spark(memory.profile()["allocated_mb"])
memory.free("assets")
memory.gc()
```

## White-Hat Security Direction

Karship K# is designed for ethical development:

- blocks private-member access with `_` prefix at language level
- includes `security.white_hat_only()` policy helper
- promotes parameterized SQL via `db.exec(sql, [params...])`

## Current Scope

This is a strong foundation, not final perfection:

- production compilers/VM/JIT are not yet implemented
- Unity, ASP.NET, desktop UI, and full SDK pipelines are roadmap items
- K# today is a working interpreter + language core for rapid prototyping

## Logo

Pink K# logo asset:

- `assets/karship_ksharp_logo.svg`
- `assets/vscode_ksharp_theme.json` (keyword color preset)
- `assets/ksharp.png` / `assets/ksharp.ico` for `.ksharp`
- `assets/kpp.png` / `assets/kpp.ico` for `.kpp`
- `assets/k.png` / `assets/k.ico` for `.k`

## File Icon Setup (Windows + VS Code)

Use your custom PNG icons by extension:

- `.ksharp` => `ksharp.png`
- `.kpp` => `kpp.png`
- `.k` => `k.png`

Windows Explorer file icon registration:

```powershell
powershell -ExecutionPolicy Bypass -File tools/register-ksharp-file-icons.ps1
```

VS Code extension icon setup:

```powershell
powershell -ExecutionPolicy Bypass -File tools/install-karship-vscode-extension.ps1 -SetAsActive
```

VS Code extension source folder:

- `karship-vscode/` (single package with language + grammar + icons)
