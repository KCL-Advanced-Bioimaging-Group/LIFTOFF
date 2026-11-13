# Maintained Python quality policy

Run `python tools/quality.py` from a development environment installed with
`python -m pip install -e ".[dev]"`. The command returns nonzero when any required
check fails. It discovers all maintained `*.py` files, including application
modules, both decoder/parser helpers, launchers, validation utilities, build
tools, and tests. It excludes generated environments, caches, build products,
and Git internals. Historical research text is retained as `.py.txt` and is not
executable application code.

The committed `pyproject.toml` pins Ruff 0.16.9, Pylint 4.1.1, and Pyrefly 1.3.2.
Ruff checks formatting, correctness, imports, modern syntax, naming, and style;
Pylint checks maintainability and code analysis; Pyrefly checks types, including
unannotated function bodies. The gate includes Pyrefly warnings and promotes
unnecessary type conversions and unreachable code to errors. A numerical Pylint
score alone is insufficient: there must be no actionable diagnostics.

The policy follows [PEP 8](https://peps.python.org/pep-0008/): four spaces,
consistent imports and names, at most 79 characters for code and 72 for flowing
comments/docstrings. Ruff formatting and W505 enforce those limits. Qt-required
event names retain their framework spelling through function-local `N802`
exceptions. Established public callback and decoder signatures remain compatible.
No maintained module is exempted from the quality command.

Explicit interfaces include immutable dataset metadata, typed histogram arrays,
export options, Qt worker results, progress/cancellation callbacks, ROI/channel
models, and native pointer/array boundaries. Runtime conversion and shape/range
checks complement static typing at ctypes and external-file boundaries. Typed
Qt signal and table adapters narrow extension-module contracts without replacing
the application objects with untyped stand-ins.

## Narrow documented exceptions

| Location | Exception | Reason |
| --- | --- | --- |
| Qt event overrides in canvas, plot, workspace | Ruff N802 per function | Qt dispatch requires the exact CamelCase event name. |
| `DatasetInfo`, `WorkspaceLayout` | Pylint R0902 at the class | Flat declared metadata and Qt-owned controls preserve existing interfaces; state fields are explicit. |
| `ImageCanvas` | Pylint R0904 at the class | One QWidget owns its event overrides and published image/ROI/navigation controls. |
| `NativeDecodeResult` | Pylint R0903 at the class | Passive ctypes C ABI structure has fields rather than application methods. |
| ROI histogram, native decode, raw selection, ICS batch APIs | Pylint R0913 / R0917 only at the affected definition | Existing call signatures remain compatible; internal orchestration uses typed job objects. |
| Worker and batch-export exception boundaries | Pylint W0718 per handler | Unexpected worker exceptions become explicit user-visible failures after cleanup, rather than escaping a Qt thread. |

Pylint design limits are explicit: eight arguments, 25 locals/attributes, 15
branches, and 80 statements. Similarity checking ignores signatures and reports
duplicates of 12 meaningful lines. The GUI has been separated into focused
components and shared export behavior, rather than suppressing whole modules.
There are no `type: ignore` directives or blanket lint disables.

Functional and scientific regressions are required after refactoring. Clean
lint output does not validate photon selection, file formats, or GUI behavior.
The final logs and test evidence are linked from the parity report.

Primary tool references: [Ruff configuration](https://docs.astral.sh/ruff/configuration/),
[Pylint usage](https://pylint.pycqa.org/en/latest/user_guide/usage/run.html), and
[Pyrefly configuration](https://pyrefly.org/en/docs/configuration/).
