from typing import NewType, Union

InputAlias = NewType("InputAlias", str)
LiteralValue = Union[int, float, str, bool, None]
