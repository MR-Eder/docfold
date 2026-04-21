# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Docfold is a unified Python toolkit for document structuring that provides a single interface to 16+ document processing engines (OCR, PDF extraction, cloud APIs). The core value is engine abstraction with automatic fallback and batch processing.

## Development Commands

```bash
# Setup
pip install -e ".[dev]"                 # Development installation

# Testing
pytest                                  # All tests
pytest tests/ -v                        # Verbose
pytest -k "test_router"                 # Filter by name
pytest --cov=docfold                    # With coverage
pytest -m "not integration"             # Skip integration tests

# Code Quality
ruff check src/ tests/                  # Lint
ruff format src/ tests/                 # Format
mypy src/                               # Type check
```

## Architecture

### Core Abstractions (`src/docfold/engines/base.py`)

- **`DocumentEngine`** — Abstract base class every engine adapter implements
  - Required: `name`, `supported_extensions`, `is_available()`, `process()`
  - Optional: `capabilities` property declares feature support
- **`EngineResult`** — Unified output dataclass all engines must return
- **`OutputFormat`** — Enum: MARKDOWN, HTML, JSON, TEXT

### Engine Router (`src/docfold/engines/router.py`)

Central orchestrator that:

1. Maintains engine registry via `register()` / `get()`
2. Selects best engine via `select(file_path, engine_hint?)` using extension-aware priority chains
3. Processes with automatic fallback when engines fail
4. Supports batch processing with `process_batch()` and bounded concurrency

Selection priority order:

1. Explicit `engine_hint` parameter
2. `ENGINE_DEFAULT` environment variable
3. Extension-aware priority chain (defined in `_EXTENSION_PRIORITY`)
4. Any available engine supporting the extension

### Engine Adapters (`src/docfold/engines/*_engine.py`)

Each engine is isolated — adding new engines doesn't affect existing code. Engines are optional extras loaded at import time. Failed imports are silently handled.

### Evaluation Framework (`src/docfold/evaluation/`)

- `metrics.py` — CER, WER, Table F1, Heading F1, Reading Order (Kendall's tau)
- `runner.py` — `EvaluationRunner` orchestrates benchmarks against ground truth

## Ground Rules

- **Test Driven Development (TDD)**: Always write tests first, then implement the code to make them pass. Never write implementation before tests.

## Adding a New Engine

1. Create `src/docfold/engines/<name>_engine.py` subclassing `DocumentEngine`
2. Add optional dependency group in `pyproject.toml`
3. Register in `cli.py` → `_build_router()`
4. Add tests in `tests/engines/`
5. Update README.md supported engines table

## Key Files

| Path | Purpose |
| - | - |
| `src/docfold/cli.py` | CLI entry point, engine discovery |
| `src/docfold/engines/base.py` | Core abstractions |
| `src/docfold/engines/router.py` | Engine selection, batch processing |
| `src/docfold/evaluation/runner.py` | Benchmark orchestration |
| `tests/fixtures/golden/` | Ground truth test data |

## Workflow Orchestration

### 1. Plan Node Default

- Enter plan mode for ANY non-trivial task (3+ steps or architectural decisions)
- If something goes sideways, STOP and re-plan immediately - don't keep pushing
- Use plan mode for verification steps, not just building
- Write detailed specs upfront to reduce ambiguity

### 2. Subagent Strategy

- Use subagents liberally to keep main context window clean
- Offload research, exploration, and parallel analysis to subagents
- For complex problems, throw more compute at it via subagents
- One task per subagent for focused execution

### 3. Self-Improvement Loop

- After ANY correction from the user: update `tasks/lessons.md` with the pattern
- Write rules for yourself that prevent the same mistake
- Ruthlessly iterate on these lessons until mistake rate drops
- Review lessons at session start for relevant project

### 4. Verification Before Done

- Never mark a task complete without proving it works
- Diff behavior between main and your changes when relevant
- Ask yourself: "Would a staff engineer approve this?"
- Run tests, check logs, demonstrate correctness

### 5. Demand Elegance (Balanced)

- For non-trivial changes: pause and ask "is there a more elegant way?"
- If a fix feels hacky: "Knowing everything I know now, implement the elegant solution"
- Skip this for simple, obvious fixes - don't over-engineer
- Challenge your own work before presenting it

### 6. Autonomous Bug Fixing

- When given a bug report: just fix it. Don't ask for hand-holding
- Point at logs, errors, failing tests - then resolve them
- Zero context switching required from the user
- Go fix failing CI tests without being told how

## Task Management

1. **Plan First**: Write plan to `tasks/todo.md` with checkable items
2. **Verify Plan**: Check in before starting implementation
3. **Track Progress**: Mark items complete as you go
4. **Explain Changes**: High-level summary at each step
5. **Document Results**: Add review section to `tasks/todo.md`
6. **Capture Lessons**: Update `tasks/lessons.md` after corrections

## Core Principles

- **Simplicity First**: Make every change as simple as possible. Impact minimal code.
- **No Laziness**: Find root causes. No temporary fixes. Senior developer standards.
- **Minimal Impact**: Changes should only touch what's necessary. Avoid introducing bugs.
