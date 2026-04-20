# KSharp

KSharp is a small interpreted programming language project in the Karship repository. It ships a lexer, parser, interpreter, and a `kar` command-line tool for running `.ksharp`, `.kpp`, and `.k` source files.

## Install

Install from PyPI:

```bash
pip install karship
```

Install from the repository while developing locally:

```bash
pip install -e .
```

## Run a `.ksharp` File with `kar`

Run a file directly:

```bash
kar hello.ksharp
```

The explicit subcommand still works too:

```bash
kar run hello.ksharp
```

## Hello World

Create `hello.ksharp`:

```ksharp
spark("Hello, world!")
```

Run it:

```bash
kar hello.ksharp
```

## Standalone Build

Install the build tools:

```bash
pip install .[build]
```

Build a one-file executable with PyInstaller:

```bash
python -m PyInstaller --clean --noconfirm kar.spec
```

On Windows this produces `dist/kar.exe`. On Linux it produces `dist/kar`. PyInstaller builds platform-native binaries, so the Windows executable must be built on Windows and the Linux executable must be built on Linux.
