import json
import xml.etree.ElementTree as ET
from pathlib import Path, PurePath
from typing import Any

import pandas as pd
from openpyxl.utils import column_index_from_string
from openpyxl.utils.cell import coordinate_from_string

from mapper.ast import (
    ComparisonExpr,
    ComparisonOperator,
    ConditionClause,
    ConstantValue,
    DataPathRef,
    DottedPath,
    ExcelPath,
    ExpressionNode,
    InputAlias,
    InputDeclaration,
    LiteralExpr,
    LiteralValue,
    LogicalAndExpr,
    LogicalOrExpr,
    MappingRule,
    MappingSource,
    NameRef,
    OutputDeclaration,
    RunDefinition,
    XmlChildFilterText,
    XmlPath,
    XmlPathSegment,
)

type InputDict = dict[InputAlias, Any]
type JSONValue = dict[str, JSONValue] | list[JSONValue] | str | int | float | bool | None
type OutputArray = tuple[PurePath, ET.Element]
type DataValue = LiteralValue | list[LiteralValue]


class Runtime:
    def execute(self, run: RunDefinition) -> None:
        inputs = self._load_inputs(run.inputs)
        output = self._load_output(run.output)

        active_cond = True
        for statement in run.statements:
            match statement:
                case ConditionClause(expression=expr):
                    result = self._eval(expr, inputs)
                    active_cond = bool(result)
                case MappingRule() if active_cond:
                    self._apply(statement, inputs, output)
                case MappingRule():
                    pass
        try:
            ET.ElementTree(output[1]).write(output[0], encoding="utf-8", xml_declaration=True)
        except OSError as e:
            raise RuntimeError(f"Cannot write output file {output[0]}: {e}") from None

    def _apply(self, rule: MappingRule, inputs: InputDict, output: OutputArray) -> None:
        source_value = self._get_source(rule.source, inputs)
        self._save_2_output(output[1], source_value, rule.target)

    def _load_inputs(self, inputs: list[InputDeclaration]) -> InputDict:
        ret_val: InputDict = {}
        work_dir = Path.cwd()

        for element in inputs:
            path = work_dir / element.file_path
            try:
                match element.file_path.suffix:
                    case ".json":
                        ret_val[element.alias] = self._load_json(path)
                    case ".xml":
                        ret_val[element.alias] = self._load_xml(path)
                    case ".xlsx":
                        ret_val[element.alias] = self._load_excel(path)
                    case _:
                        raise RuntimeError(f"unsupported file type {element.file_path.suffix!r}")
            except FileNotFoundError:
                raise RuntimeError(f"Input '{element.alias}': file not found: {path}") from None
            except PermissionError:
                raise RuntimeError(f"Input '{element.alias}': no permission to read: {path}") from None
            except (json.JSONDecodeError, ET.ParseError) as e:
                raise RuntimeError(f"Input '{element.alias}': invalid XML/JSON in {path}: {e}") from None
            except Exception as e:
                raise RuntimeError(f"Input '{element.alias}': failed to load {path}: {type(e).__name__}: {e}") from None

        return ret_val

    def _load_json(self, file_path: PurePath) -> dict[str, JSONValue]:
        with open(file_path, "r") as file:
            content = json.load(file)

        return content

    def _load_xml(self, file_path: PurePath) -> ET.Element:
        return ET.parse(file_path).getroot()

    def _load_excel(self, file_path: PurePath) -> pd.ExcelFile:
        # return load_workbook(file_path, data_only=True)
        return pd.ExcelFile(file_path)

    def _load_output(self, output: OutputDeclaration) -> OutputArray:
        from os.path import exists

        content = self._load_xml(output.file_path) if exists(output.file_path) else ET.Element(output.file_path.stem)

        return (output.file_path, content)

    def _eval(self, node: ExpressionNode, inputs: InputDict) -> DataValue:
        match node:
            case LiteralExpr(value=value):
                return value
            case DataPathRef(name=NameRef(alias=alias), data_path=DottedPath(keys=keys)):
                return self._dotted(alias, keys, inputs)
            case DataPathRef(name=NameRef(alias=alias), data_path=XmlPath(segments=segments)):
                return self._xml_lookup(alias, segments, inputs)
            case DataPathRef(name=NameRef(alias=alias), data_path=ExcelPath(sheet=sheet, cell=cell, cell_end=cell_end)):
                return self._excel_lookup(alias, sheet, cell, cell_end, inputs)
            case ComparisonExpr(left=l, operator=op, right=r):
                return self._compare(op, l, r, inputs)
            case LogicalAndExpr(left=l, right=r):
                return bool(self._eval(l, inputs)) and bool(self._eval(r, inputs))
            case LogicalOrExpr(left=l, right=r):
                return bool(self._eval(l, inputs)) or bool(self._eval(r, inputs))
            case _:
                raise ValueError(f"Expression {node} not supported")

    def _dotted(self, alias: InputAlias, keys: tuple[str, ...], inputs: InputDict) -> LiteralValue:
        if len(keys) == 1:
            return inputs[alias][keys[0]]
        tmp: InputDict = {}
        try:
            tmp[alias] = inputs[alias][keys[0]]
        except KeyError:
            raise KeyError(f"No route for json path got key: {keys[0]}")
        return self._dotted(alias, keys[1 : len(keys)], tmp)

    def _xml_lookup(self, alias: InputAlias, segments: list[XmlPathSegment], inputs: InputDict) -> LiteralValue: ...

    def _excel_lookup(
        self,
        alias: InputAlias,
        sheet: str,
        cell: str,
        cell_end: str | None,
        inputs: InputDict,
    ) -> DataValue:
        xls = inputs.get(alias)
        if xls is None:
            declared = ", ".join(sorted(inputs)) or "none"
            raise RuntimeError(
                f"Unknown input {alias!r}: no input with this alias is declared (declared inputs: {declared})"
            ) from None

        if sheet not in xls.sheet_names:
            raise RuntimeError(f"Sheet {sheet!r} not found in excel input {alias!r}")
        df = xls.parse(sheet_name=sheet, header=None)

        col, row = self._cell_parts(cell)
        rows, cols = df.shape
        if row >= rows or col >= cols:
            raise RuntimeError(
                f"Excel cell {cell!r} is outside of sheet {sheet!r} "
                f"in input {alias!r}: sheet has {rows} rows and {cols} columns"
            ) from None

        if cell_end is None:
            return str(df.iat[row, col])

        col_end, row_end = self._cell_parts(cell_end)
        if col_end < col or row_end < row:
            raise RuntimeError(f"invalid range {cell}:{cell_end}: end precedes start")
        if row_end >= rows or col_end >= cols:
            raise RuntimeError(
                f"Excel range {cell}:{cell_end} is outside of sheet {sheet!r} "
                f"in input {alias!r}: sheet has {rows} rows and {cols} columns"
            ) from None

        block = df.iloc[row : row_end + 1, col : col_end + 1]
        return [v for v in block.to_numpy().flat]

    def _cell_parts(self, cell: str) -> tuple[int, int]:
        col, row = coordinate_from_string(cell)
        return column_index_from_string(col) - 1, row - 1

    def _compare(
        self,
        operator: ComparisonOperator,
        left: ExpressionNode,
        right: ExpressionNode,
        inputs: InputDict,
    ) -> bool:
        l_value = self._eval(left, inputs)
        r_value = self._eval(right, inputs)
        if isinstance(l_value, list) or isinstance(r_value, list):
            raise ValueError("No list in comparitors")
        self._check_comparison(operator, l_value, r_value)
        match operator:
            case ComparisonOperator.EQUALS:
                return l_value == r_value
            case ComparisonOperator.NOT_EQUALS:
                return l_value != r_value
            case ComparisonOperator.GREATER_OR_EQUAL:
                l_num, r_num = self._orderable(operator, l_value, r_value)
                return l_num >= r_num
            case ComparisonOperator.GREATER_THAN:
                l_num, r_num = self._orderable(operator, l_value, r_value)
                return l_num > r_num
            case ComparisonOperator.LESS_OR_EQUAL:
                l_num, r_num = self._orderable(operator, l_value, r_value)
                return l_num <= r_num
            case ComparisonOperator.LESS_THAN:
                l_num, r_num = self._orderable(operator, l_value, r_value)
                return l_num < r_num
            case _:
                raise TypeError(f"Provided operation '{operator}' not supported!")

    def _check_comparison(self, op: ComparisonOperator, left: LiteralValue, right: LiteralValue) -> None:
        for value in (left, right):
            if isinstance(value, str):
                raise ValueError(f"Cannot use {op.value} with a string value.")
            if value is None:
                raise ValueError(f"Cannot use {op.value} with a null value.")
        if isinstance(left, bool) != isinstance(right, bool):
            raise ValueError(f"Cannot use {op.value} between bool and non-bool values.")

    def _orderable(
        self,
        op: ComparisonOperator,
        left: LiteralValue,
        right: LiteralValue,
    ) -> tuple[int | float, int | float]:
        """Reject values that cannot be ordered; return the pair as numbers."""
        if isinstance(left, (str, bool)) or left is None:
            raise ValueError(f"Cannot use {op.value} with {type(left).__name__} value")
        if isinstance(right, (str, bool)) or right is None:
            raise ValueError(f"Cannot use {op.value} with {type(right).__name__} value")
        return left, right

    def _get_source(self, source: MappingSource, inputs: InputDict) -> DataValue:
        match source:
            case ConstantValue(value=value):
                return value
            case DataPathRef() as ref:
                return self._eval(ref, inputs)
            case _:
                raise RuntimeError(f"Got unexpected source type {source}")

    def _save_2_output(self, output: ET.Element, value: DataValue, path: XmlPath) -> None:
        segments = path.segments
        if segments and segments[0].element_tag == output.tag:
            segments = segments[1:]
        node = output
        for segment in segments:
            node = self._child_or_create(node, segment)
        node.text = str(value)

    def _child_or_create(self, parent: ET.Element, segment: XmlPathSegment) -> ET.Element:
        for child in parent.findall(segment.element_tag):
            if self._matches_filter(child, segment.filter):
                return child
        return ET.SubElement(parent, segment.element_tag)

    def _matches_filter(self, child: ET.Element, filter_: XmlChildFilterText | None) -> bool:
        if filter_ is None:
            return True
        for grandchild in child.findall(filter_.child_tag):  # adjust field names
            if grandchild.text == filter_.expected_text:
                return True
        return False


def main() -> None:
    import argparse

    from mapper.builder import build_run_definition
    from mapper.errors import DslSyntaxError
    from mapper.syntax.parser import MappinParser

    parser = argparse.ArgumentParser(
        prog="mapper",
        description="Execute a mapping definition and produce an XML output.",
    )
    parser.add_argument(
        "mapping",
        type=Path,
        help="Path to the .mapping file to execute",
    )
    parser.add_argument(
        "-C",
        "--chdir",
        type=Path,
        default=None,
        help="Working directory for resolving input and output files (default: cwd)",
    )
    args = parser.parse_args()
    mapping_path = args.mapping.resolve()

    try:
        content: str = mapping_path.read_text("utf-8-sig")
    except OSError as e:
        _fail(mapping_path, e, f"Cannot read mapping file: {e}")
        return

    if args.chdir is not None:
        import os

        try:
            os.chdir(args.chdir)
        except OSError as e:
            _fail(mapping_path, e, f"Cannot change into working directory {args.chdir}: {e}")

    try:
        text = MappinParser().parse(content)
        prog = build_run_definition(text)
    except DslSyntaxError as e:
        _fail(mapping_path, e, f"Syntax error: {e}")
        return
    except Exception as e:
        _fail(mapping_path, e, f"Failed to build mapping: {type(e).__name__}: {e}")
        return

    try:
        Runtime().execute(prog)
    except Exception as e:
        _fail(mapping_path, e, f"{type(e).__name__}: {e}")


def _fail(mapping_path: Path, exc: Exception, message: str) -> None:
    import sys
    import traceback
    from pathlib import Path

    Path(str(mapping_path) + ".log").write_text(traceback.format_exc(), encoding="utf-8")
    print(message, file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    import sys

    sys.exit(main())


# podman run -d --name mqtt-dashboard --restart unless-stopped -p 8080:8080 -v mqtt_data:/app/data mqtt-dashboard
