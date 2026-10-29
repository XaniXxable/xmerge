import re
from pathlib import PurePosixPath
from typing import Final

from lark import Token, Tree

from mapper.ast import (
    ComparisonExpr,
    ComparisonOperator,
    ConditionClause,
    ConditionExpr,
    ConstantValue,
    DataPathRef,
    DottedPath,
    ExcelPath,
    InputAlias,
    InputDeclaration,
    LiteralExpr,
    LiteralValue,
    LogicalAndExpr,
    LogicalOrExpr,
    MappingRule,
    MappingSource,
    NameRef,
    Node,
    OutputDeclaration,
    RunDefinition,
    RunStatement,
    XmlChildFilterText,
    XmlPath,
    XmlPathSegment,
)
from mapper.errors import DslError

type ParseNode = Token | Tree[Token]

# Words the lexer treats as keywords inside conditions: not usable as input aliases.
RESERVED_ALIASES: Final[frozenset[str]] = frozenset({"as", "and", "or", "null", "true", "false"})

_STRING_ESCAPES: Final[dict[str, str]] = {
    '"': '"',
    "\\": "\\",
    "n": "\n",
    "t": "\t",
    "r": "\r",
}

_XML_NAME: Final[str] = r"[A-Za-z_][\w.\-]*(?::[A-Za-z_][\w.\-]*)?"
# One path segment: /tag  or  /tag[Child="text"]  (single or double quotes).
_XML_SEGMENT: Final[re.Pattern[str]] = re.compile(
    rf"""/(?P<tag>{_XML_NAME})
         (?:\[(?P<child>{_XML_NAME})=(?:"(?P<dq>[^"]*)"|'(?P<sq>[^']*)')\])?""",
    re.VERBOSE,
)


# ---- public entry point ---------------------------------------------------------
def build_run_definition(tree: Tree[Token]) -> RunDefinition:
    """Turn the parse tree of a whole script into a RunDefinition.

    Raises DslError for structural problems the grammar cannot express
    (duplicate aliases, missing/multiple output, malformed XML paths, ...).
    """
    run = _expect_tree(_children(tree, 1)[0])
    run_location = _tree_location(run, Node(1, 1))

    inputs: list[InputDeclaration] = []
    output: OutputDeclaration | None = None
    statements: list[RunStatement] = []
    for child in run.children:
        statement = _expect_tree(child)
        match str(statement.data):
            case "input":
                inputs.append(_build_input(statement, run_location))
            case "output":
                output = _build_output(statement, run_location)
            case "condition":
                statements.append(_build_condition(statement, run_location))
            case "mapping":
                statements.append(_build_mapping(statement, run_location))
            case other:
                raise _out_of_sync(f"unknown statement {other!r}")

    if output is None:
        raise DslError("No output file declared", node=run_location)

    return RunDefinition(run_location.line, run_location.column, inputs=inputs, output=output, statements=statements)


def _children(tree: Tree[Token], count: int) -> list[ParseNode]:
    if len(tree.children) != count:
        raise _out_of_sync(f"{str(tree.data)!r} has {len(tree.children)} children, expected {count}")
    return list(tree.children)


# ---- statements -----------------------------------------------------------------
def _build_input(tree: Tree[Token], fallback: Node) -> InputDeclaration:
    children = tree.children
    if len(children) not in (1, 2):
        raise _out_of_sync(f"'input' has {len(children)} children")
    alias = _alias_from_token(_expect_token(children[1])) if len(children) == 2 else None
    location = _tree_location(tree, fallback)

    if alias is None:
        raise DslError("No alias name for input.", node=location)

    return InputDeclaration(
        file_path=_file_path(_expect_token(children[0])),
        alias=alias,
        line=location.line,
        column=location.column,
    )


def _build_output(tree: Tree[Token], fallback: Node) -> OutputDeclaration:
    path_token = _expect_token(_children(tree, 1)[0])
    location = _tree_location(tree, fallback)
    return OutputDeclaration(
        file_path=_file_path(path_token),
        column=location.column,
        line=location.line,
    )


def _build_condition(tree: Tree[Token], fallback: Node) -> ConditionClause:
    location = _tree_location(tree, fallback)
    return ConditionClause(
        expression=_build_condition_expr(_children(tree, 1)[0], location),
        line=location.line,
        column=location.column,
    )


def _build_mapping(tree: Tree[Token], fallback: Node) -> MappingRule:
    location = _tree_location(tree, fallback)
    source_ParseNode, target_ParseNode = _children(tree, 2)
    source_tree = _expect_tree(source_ParseNode)
    source: MappingSource
    match str(source_tree.data):
        case "source_field":
            child = _children(source_tree, 1)[0]
            source = _build_data_ref(_expect_tree(child))
        case "const_field":
            child = _expect_tree(_children(source_tree, 1)[0])
            child_location = _tree_location(child, location)
            source = ConstantValue(
                value=_literal_value(child),
                line=child_location.line,
                column=child_location.column,
            )
        case other:
            raise _out_of_sync(f"unknown mapping field {other!r}")
    target_token = _expect_token(_children(_expect_tree(target_ParseNode), 1)[0])
    return MappingRule(
        source=source,
        target=_parse_xml_path(target_token),
        line=location.line,
        column=location.column,
    )


# ---- data references ------------------------------------------------------------
def _build_data_ref(tree: Tree[Token]) -> DataPathRef:
    """`data_ref` wraps either a `dotted_ref` or an `xml_ref`."""
    ref = tree
    match str(ref.data):
        case "dotted_ref":
            return _build_dotted_ref(ref)
        case "xml_ref":
            alias_ParseNode, path_ParseNode = _children(ref, 2)
            alias_token = _expect_token(alias_ParseNode)
            location = _token_location(alias_token)
            alias = InputAlias(str(alias_token))
            return DataPathRef(
                name=NameRef(alias=alias, line=location.line, column=location.column),
                data_path=_parse_xml_path(_expect_token(path_ParseNode)),
                line=location.line,
                column=location.column,
            )
        case "excel_ref":
            children = ref.children
            if len(children) not in (3, 4):
                raise _out_of_sync(f"'excel_ref' has {len(children)} children, expected 3 or 4")
            alias_token = _expect_token(children[0])
            sheet_token = _expect_token(children[1])
            cell_token = _expect_token(children[2])
            raw = str(cell_token).upper()
            start, sep, end = raw.partition(":")
            cell = start
            cell_end = end if sep else None
            location = _token_location(alias_token)
            alias = InputAlias(str(alias_token))
            excel_path = ExcelPath(
                cell=cell,
                sheet=str(sheet_token),
                cell_end=cell_end,
                line=location.line,
                column=location.column,
            )
            return DataPathRef(
                name=NameRef(alias=alias, line=location.line, column=location.column),
                data_path=excel_path,
                line=location.line,
                column=location.column,
            )
        case other:
            raise _out_of_sync(f"unknown data reference {other!r}")


def _build_dotted_ref(tree: Tree[Token]) -> DataPathRef:
    """`json.data.it`: the first name is the input alias, the rest are data keys."""
    names = [_expect_token(c) for c in tree.children]
    if len(names) < 2:
        raise _out_of_sync("'dotted_ref' needs an alias and at least one key")
    alias_token, *key_tokens = names
    location = _token_location(alias_token)
    alias = InputAlias(str(alias_token))
    return DataPathRef(
        name=NameRef(alias=alias, line=location.line, column=location.column),
        data_path=DottedPath(
            keys=tuple(str(t) for t in key_tokens),
            line=location.line,
            column=location.column,
        ),
        line=location.line,
        column=location.column,
    )


# ---- condition expressions ------------------------------------------------------
def _build_condition_expr(node: ParseNode, fallback: Node) -> ConditionExpr:
    if isinstance(node, Token):
        location = _token_location(node)
        return LiteralExpr(value=_literal_value(node), line=location.line, column=location.column)
    location = _tree_location(node, fallback)
    match str(node.data):
        case "true" | "false" | "null":
            return LiteralExpr(value=_literal_value(node), line=location.line, column=location.column)
        case "dotted_ref":
            return _build_dotted_ref(node)
        case "cmp":
            left, operator, right = _children(node, 3)
            return ComparisonExpr(
                operator=ComparisonOperator(str(_expect_token(operator))),
                left=_build_condition_expr(left, location),
                right=_build_condition_expr(right, location),
                line=location.line,
                column=location.column,
            )
        case "and_":
            left, right = _children(node, 2)
            return LogicalAndExpr(
                left=_build_condition_expr(left, location),
                right=_build_condition_expr(right, location),
                line=location.line,
                column=location.column,
            )
        case "or_":
            left, right = _children(node, 2)
            return LogicalOrExpr(
                left=_build_condition_expr(left, location),
                right=_build_condition_expr(right, location),
                line=location.line,
                column=location.column,
            )
        case "literal":
            return LiteralExpr(value=_literal_value(node), line=location.line, column=location.column)
        case other:
            raise _out_of_sync(f"unknown expression {other!r}")


# ---- literals -------------------------------------------------------------------
def _literal_value(node: ParseNode) -> LiteralValue:
    if isinstance(node, Token):
        match node.type:
            case "INT":
                return int(node)
            case "FLOAT":
                return float(node)
            case "STRING":
                return _string_value(node)
            case other:
                raise _out_of_sync(f"unexpected literal token {other}")
    match str(node.data):
        case "true":
            return True
        case "false":
            return False
        case "null":
            return None
        case "literal":
            return _literal_value(_children(node, 1)[0])
        case other:
            raise _out_of_sync(f"unexpected literal node {other!r}")


def _string_value(token: Token) -> str:
    """Strip the quotes and resolve escapes (\\" \\\\ \\n \\t \\r); anything else is an error."""
    inner = str(token)[1:-1]
    result: list[str] = []
    index = 0
    while index < len(inner):
        char = inner[index]
        if char != "\\":
            result.append(char)
            index += 1
            continue
        escaped = inner[index + 1] if index + 1 < len(inner) else ""
        if escaped not in _STRING_ESCAPES:
            location = _token_location(token, offset=1 + index)
            raise DslError(
                f"unknown escape sequence '\\{escaped}' in string",
                node=location,
            )
        result.append(_STRING_ESCAPES[escaped])
        index += 2
    return "".join(result)


def _file_path(token: Token) -> PurePosixPath:
    text = _string_value(token)
    if not text.strip():
        raise DslError("file path must not be empty", node=_token_location(token))
    if "\\" in text:
        raise DslError(
            "file paths use '/' as separator; backslashes are not allowed",
            node=_token_location(token),
        )
    return PurePosixPath(text)


def _alias_from_token(token: Token) -> InputAlias:
    name = str(token)
    if name in RESERVED_ALIASES:
        raise DslError(
            f"{name!r} is a reserved word and cannot be used as an alias",
            node=_token_location(token),
        )
    return InputAlias(name)


# ---- XML paths ------------------------------------------------------------------
def _parse_xml_path(token: Token) -> XmlPath:
    """`/Vehicle/Item[Name="x"]/Value` -> typed segments.

    Supported per segment: an element name and at most one `[Child="text"]` filter.
    """
    location = _token_location(token)
    raw = str(token).rstrip()
    segments: list[XmlPathSegment] = []
    position = 0
    while position < len(raw):
        match = _XML_SEGMENT.match(raw, position)
        if match is None:
            raise DslError(
                f'invalid XML path at {raw[position:]!r}; expected /tag or /tag[Child="text"] segments',
                node=_token_location(token, offset=position),
            )
        child = match.group("child")
        text = match.group("dq") if match.group("dq") is not None else match.group("sq")
        segments.append(
            XmlPathSegment(
                element_tag=match.group("tag"),
                filter=None
                if child is None
                else XmlChildFilterText(
                    child_tag=child, expected_text=text or "", line=location.line, column=location.column
                ),
                line=location.line,
                column=location.column,
            )
        )
        position = match.end()
    return XmlPath(
        segments=segments,
        line=location.line,
        column=location.column,
    )


# ---- tree plumbing ----------------------------------------------------------------


def _expect_tree(ParseNode: ParseNode) -> Tree[Token]:
    if isinstance(ParseNode, Tree):
        return ParseNode
    raise _out_of_sync(f"expected a subtree, found token {ParseNode.type}")


def _expect_token(node: ParseNode) -> Token:
    if isinstance(node, Token):
        return node
    raise _out_of_sync(f"expected a token, found subtree {str(node.data)!r}")


def _token_location(token: Token, offset: int = 0) -> Node:
    return Node(line=token.line or 1, column=(token.column or 1) + offset)


def _tree_location(tree: Tree[Token], fallback: Node) -> Node:
    meta = tree.meta
    if meta.empty:
        return fallback
    return Node(line=meta.line, column=meta.column)


def _out_of_sync(detail: str) -> RuntimeError:
    """The tree does not look like the grammar says: a bug here, not in the script."""
    return RuntimeError(f"builder is out of sync with mapping.lark: {detail}")


def main() -> None:
    from pathlib import Path

    from mapper.syntax.parser import MappinParser

    content = (Path.cwd() / "example.mapping").read_text("utf-8-sig")
    parser = MappinParser()

    text = parser.parse(content)
    prog = build_run_definition(text)
    print(prog)


if __name__ == "__main__":
    import sys

    sys.exit(main())
