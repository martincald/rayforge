import ast
import logging
import math
from types import CodeType
from typing import Any

logger = logging.getLogger(__name__)

# Allowed functions and constants in expressions
MATH_CONTEXT = {
    k: v for k, v in math.__dict__.items() if not k.startswith("__")
}

# Expressions arrive in sketch and project files, so they are checked
# before eval: an empty __builtins__ alone does not stop
# ().__class__.__base__.__subclasses__() reaching os.system.
MAX_EXPRESSION_LENGTH = 1000
_ALLOWED_NODES = (
    ast.Expression,
    ast.Constant,
    ast.Name,
    ast.Load,
    ast.BinOp,
    ast.UnaryOp,
    ast.BoolOp,
    ast.Compare,
    ast.IfExp,
    ast.Call,
    ast.keyword,
    ast.Tuple,
    ast.List,
    ast.operator,
    ast.unaryop,
    ast.boolop,
    ast.cmpop,
)
# Attributes that reach a frame, its globals or code, or read
# attributes by name through a format string.
_INTROSPECTION_PREFIXES = ("_", "gi_", "cr_", "ag_", "f_", "tb_", "co_")
_STRING_FORMATTERS = ("format", "format_map")


class UnsafeExpressionError(SyntaxError):
    """An expression that uses more of Python than a formula needs."""


def compile_expression(
    expression: str, allow_attributes: bool = False
) -> CodeType:
    """
    Compile an expression for eval, refusing anything but a formula.

    A formula is constants, names, arithmetic, comparisons and calls,
    nothing that defines a function, makes a generator or names a
    private attribute. Text templates may read public attributes
    (`{today().year}`); numeric expressions never need to.

    Raises:
        SyntaxError: The expression does not parse, or (as
            UnsafeExpressionError) it is more than a formula.
    """
    if len(expression) > MAX_EXPRESSION_LENGTH:
        raise UnsafeExpressionError("expression too long")
    try:
        tree = ast.parse(expression.strip(), mode="eval")
        for node in ast.walk(tree):
            _check_node(node, allow_attributes)
        return compile(tree, "<expression>", "eval")
    except (RecursionError, MemoryError) as e:
        raise UnsafeExpressionError("expression nested too deeply") from e


def _check_node(node: ast.AST, allow_attributes: bool) -> None:
    if isinstance(node, ast.Attribute):
        name = node.attr
        if (
            not allow_attributes
            or name.startswith(_INTROSPECTION_PREFIXES)
            or name in _STRING_FORMATTERS
        ):
            raise UnsafeExpressionError(f"attribute {name!r} is not allowed")
        return
    if not isinstance(node, _ALLOWED_NODES):
        raise UnsafeExpressionError(
            f"{type(node).__name__} is not allowed in an expression"
        )
    if isinstance(node, ast.Name) and node.id.startswith("_"):
        raise UnsafeExpressionError(f"name {node.id!r} is not allowed")
    if isinstance(node, ast.keyword) and node.arg is None:
        raise UnsafeExpressionError("** is not allowed in an expression")


def safe_evaluate(expression: str, context: dict[str, Any]) -> float:
    """
    Evaluates a mathematical expression string using a specific context
    (variable names) and standard math functions.

    Args:
        expression: The string to evaluate (e.g., "width / 2 + 5").
        context: A dictionary of variable names to values.

    Returns:
        float: The calculated value.

    Raises:
        ValueError: If evaluation fails or syntax is invalid.
    """
    if not expression:
        return 0.0

    # Clean whitespace
    expr = expression.strip()

    # Create the evaluation namespace
    # Note: Context overrides math functions if names collide.
    namespace = MATH_CONTEXT.copy()
    namespace.update(context)

    # Add the restricted builtins to the same namespace
    namespace["__builtins__"] = {}

    try:
        # Use Python's eval, passing the unified namespace as globals.
        # Eval will use this for both globals and locals.
        result = eval(compile_expression(expr), namespace)
        return float(result)
    except Exception as e:  # noqa: BLE001 - arbitrary user expression
        logger.error(f"Failed to evaluate expression '{expression}': {e}")
        raise ValueError(f"Invalid expression: {e}")
