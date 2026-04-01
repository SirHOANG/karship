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
- `each ... in ...`: for-each loop
- `memory.alloc(...)` / `memory.free(...)`: manual memory reservation lifecycle
- `memory.profile()` / `memory.set_mode("eco"|"balanced"|"turbo")`: automatic + manual optimization
- `security.hash(...)`: SHA-256 helper
- `db.open(...)`: sqlite database connector
- `discord.create(...)`: bot simulator helper

## Extensions

K# runtime accepts all of these:

- `.ksharp`
- `.kpp`
- `.k`

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
```

Memory profiles in CLI:

```bash
ksharp --memory-mode auto ksharp/example.ksharp
ksharp --memory-mode eco ksharp/example.kpp
ksharp --memory-mode turbo ksharp/example.k
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
