# xmerge

Converts structured input sources such as JSON, XML, and Excel files into a single XML output. Conversion rules are written in a small declarative DSL; a Tauri desktop frontend provides a graphical editor for those rules, live preview, and one-click execution of the converter.

## How it works

The repository contains two components that work together:

1. **Converter** — a Python toolkit that parses a `.mapping` script, validates it, and executes it against real input data to produce an XML file.
2. **Desktop frontend** — a Tauri app that edits `.mapping` scripts through tables instead of raw text, auto-saves them, and runs the converter as a child process with stop support (Windows).

The frontend generates the `.mapping` script; the converter consumes it. Both can be used independently — the converter is a plain Python CLI.

**Note:** The desktop frontend was developed with AI assistance (vibe coding) and is not hand-written production code. The Python converter is the manually developed, strictly typed core of this project.

## The DSL

```text
run:
  input: "input/data.json" as json_data
  input: "input/records.xml" as xml_data
  output: "output/result.xml"

  mapping:
    source: json_data.record.entry.value
    target: /Root/Item[Name="value"]/Value

  mapping:
    const: 10
    target: /Root/Item[Name="count"]/Value

  condition: json_data.record.entry.value != 0 and json_data.record.entry.value != null
  mapping:
    source: json_data.record.entry.value
    target: /Root/Item[Name="value"]/Value
```

Syntax reference:

- `input: "<path>" as <alias>` — declare an input file and a name for its data. Aliases must be unique; reserved words (`as`, `and`, `or`, `null`, `true`, `false`) are rejected.
- `output: "<path>"` — exactly one output declaration is required.
- `mapping:` blocks contain exactly one source line and one target line:
  - `source: <alias>.<key>.<key>` reads from JSON/XLSX data.
  - `source: <alias>: /Tag/Tag[Child="text"]/Tag` reads from an XML input.
  - `const: <literal>` writes a fixed value (int, float, string, `true`, `false`, `null`).
  - `target: /Tag/Tag[Child="text"]/...` places the value in the output XML.
- `condition: <expr>` — evaluates `true`/`false`; all following mappings run only while the last evaluated condition is true. A mapping before any condition runs unconditionally.
- Expressions support `==`, `!=`, `<`, `<=`, `>`, `>=`, `and`, `or`, parentheses, and literals. Ordering operators reject strings and `null`; equality with `null` is the idiomatic way to test for missing values.
- Blocks are indentation-based: 2-space steps, tabs rejected.

## Features

- Declarative DSL parsed with an LALR grammar into a typed AST; every node carries a source location (line and column)
- Input formats: JSON, XML, XLSX (via pandas)
- Conditions with `and` / `or`, comparison operators, and short-circuit evaluation
- Errors report the exact line and column of the offending script element, not a stack trace
- Desktop frontend: tabular rule editor with grouped mappings, search/filter, path preview, auto-save, settings persistence next to the executable, and process control (run, stop, open output files with the OS default application)
- Strict type checking (pyright strict mode); PEP 695 type aliases and structural pattern matching throughout the Python code

## Installation

Requires Python 3.12 or newer.

```bash
uv sync            # or: pip install lark pandas
```

The desktop frontend additionally requires Rust and the Tauri CLI.

```bash
npm install
npx tauri dev      # development
npx tauri build     # production build
```

## Usage

Run a mapping script against its inputs:

```bash
python -m mapper example.mapping
```

Or use the pipeline from Python:

```python
from mapper.builder import build_run_definition
from mapper.runtime import Runtime
from mapper.syntax.parser import MappingParser

parser = MappingParser()
run = build_run_definition(parser.parse(script_text))
Runtime().execute(run)
```

The desktop frontend is started like any Tauri app; it expects the converter executable (`converter.exe`) in the working directory it was started from.

## Project layout

```text
src/mapper/
├── ast/            # typed AST: node.py, unions.py, declarations, expressions, XML path types
├── syntax/         # mapping.lark grammar, parser wrapper, indentation postlexer
├── builder.py      # parse tree -> AST (raises DslError on structural problems)
├── runtime.py      # loads inputs, evaluates conditions, applies mappings, writes XML
└── errors.py       # DslError, DslSyntaxError (both carry line/column)
```

Design boundaries:

- `syntax` owns the grammar and produces a raw lark tree.
- `builder` turns the tree into a typed AST and is the only module that knows lark tree shapes.
- `ast` is pure data: frozen dataclasses with locations, no behavior.
- `runtime` consumes only the AST. It never imports the builder or lark.

## Error handling

All script errors carry a source location:

```text
mapper.errors.DslError: input alias 'json_data' is already defined on line 2 (line 3, column 3)
mapper.errors.DslSyntaxError: Indentation must be a multiple of 2 spaces, got 3 (line 4, column 1)
```

Structural bugs in the tool itself (grammar and builder out of sync) raise `RuntimeError`, not `DslError`, so they cannot be mistaken for user script errors.

