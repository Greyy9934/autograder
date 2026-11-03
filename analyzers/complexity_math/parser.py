"""Restricted parser for AI-provided asymptotic expressions.

This module never evaluates Python code. It converts mathematical notation
into a validated AST with strict syntax, symbol, depth and size limits.
"""
# It checks math formulas without treating them as code to execute.

from __future__ import annotations

import ast
import math
import re
import tokenize
from io import StringIO
from typing import Iterable

from .models import ExpressionLimits, ParsedExpression, ParseResult


ALLOWED_FUNCTIONS = frozenset({
    "log", "ln", "log2", "log10", "sqrt", "factorial",
    "exp", "log_star", "alpha",
})

ALLOWED_CONSTANTS = frozenset({"pi", "e"})
RESERVED_NAMES = frozenset({"O", "Theta", "Omega", "BigO", "BigTheta", "BigOmega"})

DEFAULT_LIMITS = ExpressionLimits()


def _validate_limits(limits: ExpressionLimits) -> None:
    """Reject invalid or unsafe parser resource configurations."""
    # Checks limits.
    # What the inputs mean:
    # - limits: the limits used for this step.
    # What it gives back: It does its work and does not return a value.
    if not isinstance(limits, ExpressionLimits):
        raise ExpressionParseError(
            "invalid_limits", "Limits must be an ExpressionLimits instance."
        )

    integer_limits = {
        "max_characters": (1, 10000),
        "max_tokens": (1, 5000),
        "max_ast_nodes": (1, 5000),
        "max_ast_depth": (1, 100),
        "max_parameter_count": (0, 100),
    }

    for name, (minimum, maximum) in integer_limits.items():
        value = getattr(limits, name)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ExpressionParseError(
                "invalid_limits", f"{name} must be an integer."
            )
        if not minimum <= value <= maximum:
            raise ExpressionParseError(
                "invalid_limits",
                f"{name} must be between {minimum} and {maximum}.",
            )

    for name in ("max_numeric_literal", "max_exponent_literal"):
        value = getattr(limits, name)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or value <= 0
        ):
            raise ExpressionParseError(
                "invalid_limits", f"{name} must be a finite positive number."
            )


class ExpressionParseError(ValueError):
    def __init__(self, code: str, message: str):
        # Helps with init inside init.
        # What the inputs mean:
        # - code: the code used for this step.
        # - message: the message used for this step.
        # - self/cls: the current object this function belongs to.
        # What it gives back: It returns the result that the next step needs.
        super().__init__(message)
        self.code = code


def _strip_asymptotic_wrapper(text: str) -> tuple[str, str]:
    """Strip one balanced outer asymptotic wrapper.

    Only a wrapper that encloses the entire expression is removed.
    Nested parentheses are checked explicitly.
    """
    # Handles strip asymptotic wrapper as a supporting part of parser .
    # What the inputs mean:
    # - text: the text being parsed or shown.
    # What it gives back: It returns a small group of related values.
    text = text.strip()

    wrappers = {
        "O": "big_o",
        "Theta": "theta",
        "Ω": "omega",
        "Omega": "omega",
        "Θ": "theta",
    }

    match = re.match(
        r"^\s*(BigO|BigTheta|BigOmega|Theta|Omega|O|Θ|Ω)\s*\(",
        text,
        flags=re.IGNORECASE,
    )

    if not match:
        return text, "unspecified"

    wrapper_name = match.group(1)
    family = wrappers.get(wrapper_name)
    if family is None:
        family = {
            "bigo": "big_o",
            "bigtheta": "theta",
            "bigomega": "omega",
        }.get(wrapper_name.lower(), "unspecified")

    opening = match.end() - 1
    depth = 0
    closing = None

    for index in range(opening, len(text)):
        char = text[index]

        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1

            if depth < 0:
                raise ExpressionParseError(
                    "malformed_wrapper",
                    "Unexpected closing parenthesis in asymptotic wrapper.",
                )

            if depth == 0:
                closing = index
                break

    if closing is None:
        raise ExpressionParseError(
            "malformed_wrapper",
            "Asymptotic wrapper has an unclosed parenthesis.",
        )

    if text[closing + 1:].strip():
        raise ExpressionParseError(
            "malformed_wrapper",
            "Unexpected content after the asymptotic wrapper.",
        )

    inner = text[opening + 1:closing].strip()

    if not inner:
        raise ExpressionParseError(
            "empty_expression",
            "Asymptotic wrapper cannot contain an empty expression.",
        )

    return inner, family


def _normalize(text: str) -> str:
    """Normalize mathematical notation without corrupting function names."""
    # Handles normalize as a supporting part of parser .
    # What the inputs mean:
    # - text: the text being parsed or shown.
    # What it gives back: It returns text.
    text = text.strip()
    text = text.replace("−", "-").replace("×", "*").replace("·", "*")
    text = text.replace("÷", "/").replace("π", "pi")
    # Log-base subscripts are common in algorithm analysis notation.
    text = text.replace("₁₀", "_10").replace("₂", "_2")

    # Normalize square roots before stripping the outer O/Theta/Omega wrapper.
    text = re.sub(r"√\s*\(([^()]*)\)", r"sqrt(\1)", text)
    text = re.sub(r"√\s*([A-Za-z][A-Za-z0-9_]*)", r"sqrt(\1)", text)

    for char, replacement in {
        "⁰": "**0", "¹": "**1", "²": "**2", "³": "**3",
        "⁴": "**4", "⁵": "**5", "⁶": "**6", "⁷": "**7",
        "⁸": "**8", "⁹": "**9",
    }.items():
        text = text.replace(char, replacement)

    text, _ = _strip_asymptotic_wrapper(text)

    # Expand conventional unparenthesized log chains before the simpler
    # single-log shorthand below.  For example, "log log n" becomes
    # log(log(n)) rather than a multiplication involving an unknown symbol.
    log_token = r"(?:log(?:_2|_10)?|ln)"
    log_chain = re.compile(
        rf"\b((?:{log_token}\s+)+)([A-Za-z][A-Za-z0-9_]*)\b",
        flags=re.IGNORECASE,
    )

    def expand_log_chain(match: re.Match[str]) -> str:
        # Helps with expand log chain inside expand log chain.
        # What the inputs mean:
        # - match: the match used for this step.
        # What it gives back: It returns text.
        functions = re.findall(log_token, match.group(1), flags=re.IGNORECASE)
        expression = match.group(2)
        for function in reversed(functions):
            normalized_function = {
                "ln": "log",
                "log_2": "log2",
                "log_10": "log10",
            }.get(function.lower(), "log")
            expression = f"{normalized_function}({expression})"
        return expression

    text = log_chain.sub(expand_log_chain, text)

    text = re.sub(r"\blog_2\s*(?=\()", "log2", text, flags=re.IGNORECASE)
    text = re.sub(r"\blog_10\s*(?=\()", "log10", text, flags=re.IGNORECASE)
    text = re.sub(
        r"\blog_2\s+([A-Za-z][A-Za-z0-9_]*)\b",
        r"log2(\1)", text, flags=re.IGNORECASE
    )
    text = re.sub(
        r"\blog_10\s+([A-Za-z][A-Za-z0-9_]*)\b",
        r"log10(\1)", text, flags=re.IGNORECASE
    )
    text = re.sub(r"\bln\s*\(", "log(", text, flags=re.IGNORECASE)
    text = re.sub(
        r"\bln\s+([A-Za-z][A-Za-z0-9_]*)",
        r"log(\1)", text, flags=re.IGNORECASE
    )
    text = re.sub(
        r"\blog\s+([A-Za-z][A-Za-z0-9_]*)",
        r"log(\1)", text, flags=re.IGNORECASE
    )

    text = text.replace("^", "**")

    text = re.sub(
        r"(?<![A-Za-z0-9_])([A-Za-z_][A-Za-z0-9_]*)!",
        r"factorial(\1)", text
    )
    text = re.sub(r"(\([^()]*\))!", r"factorial(\1)", text)

    text = re.sub(r"\s+", "", text)

    function_names = r"(?:log10|log2|log|sqrt|factorial|exp)"
    text = re.sub(
        rf"(?<=[0-9n)])(?=(?:{function_names})\()",
        "*", text
    )
    text = re.sub(r"(?<=[0-9)])(?=n\b)", "*", text)
    text = re.sub(r"(?<=\))(?=[A-Za-z])", "*", text)

    # Canonicalize the common equivalent polynomial spelling.
    # This narrow rule does not rewrite arbitrary products.
    text = re.sub(
        r"(?<![A-Za-z0-9_])n\*n(?![A-Za-z0-9_])",
        "n**2",
        text,
    )

    return text


def _walk_and_validate(
    root: ast.AST,
    limits: ExpressionLimits,
    supplied_parameters: dict[str, float],
) -> tuple[frozenset[str], frozenset[str], frozenset[str]]:
    # Helps with walk and validate inside walk and validate.
    # What the inputs mean:
    # - root: the root used for this step.
    # - limits: the limits used for this step.
    # - supplied_parameters: the supplied parameters used for this step.
    # What it gives back: It returns a small group of related values.
    nodes = list(ast.walk(root))
    if len(nodes) > limits.max_ast_nodes:
        raise ExpressionParseError("too_many_nodes", "Expression contains too many syntax nodes.")

    symbols: set[str] = set()
    functions: set[str] = set()
    parameters: set[str] = set()
    allowed_binary = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod)
    allowed_unary = (ast.UAdd, ast.USub)

    def visit(node: ast.AST, depth: int = 0) -> None:
        # Handles walk and validate as a supporting part of parser .
        # What the inputs mean:
        # - node: the current piece of the formula being checked.
        # - depth: the depth used for this step.
        # What it gives back: It does its work and does not return a value.
        if depth > limits.max_ast_depth:
            raise ExpressionParseError("too_deep", "Expression nesting exceeds the permitted depth.")

        if isinstance(node, ast.Expression):
            visit(node.body, depth + 1)
            return

        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                raise ExpressionParseError("invalid_constant", "Only real numeric constants are supported.")
            value = float(node.value)
            if not math.isfinite(value) or abs(value) > limits.max_numeric_literal:
                raise ExpressionParseError("numeric_literal_limit", "Numeric literal exceeds the permitted range.")
            return

        if isinstance(node, ast.Name):
            name = node.id
            if name in {"n", *ALLOWED_CONSTANTS}:
                symbols.add(name)
                return
            if name in ALLOWED_FUNCTIONS:
                raise ExpressionParseError("function_without_call", f"Function '{name}' must be called.")
            if name in RESERVED_NAMES:
                raise ExpressionParseError("invalid_wrapper", "Asymptotic wrapper is not valid inside an expression.")
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,31}", name):
                raise ExpressionParseError("invalid_symbol", "Invalid symbol name.")
            if name not in supplied_parameters:
                raise ExpressionParseError("unknown_symbol", f"Unknown symbol or missing parameter: {name}")
            parameters.add(name)
            symbols.add(name)
            return

        if isinstance(node, ast.BinOp):
            if not isinstance(node.op, allowed_binary):
                raise ExpressionParseError("unsupported_operator", "Unsupported mathematical operator.")
            visit(node.left, depth + 1)
            visit(node.right, depth + 1)
            if isinstance(node.op, ast.Pow) and isinstance(node.right, ast.Constant):
                if abs(float(node.right.value)) > limits.max_exponent_literal:
                    raise ExpressionParseError("exponent_limit", "Exponent exceeds the permitted limit.")
            return

        if isinstance(node, ast.UnaryOp):
            if not isinstance(node.op, allowed_unary):
                raise ExpressionParseError("unsupported_operator", "Unsupported unary operator.")
            visit(node.operand, depth + 1)
            return

        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in ALLOWED_FUNCTIONS:
                raise ExpressionParseError("unsupported_function", "Function is not in the approved mathematical function set.")
            if node.keywords or len(node.args) != 1:
                raise ExpressionParseError("invalid_function_arguments", "Mathematical functions require exactly one positional argument.")
            functions.add(node.func.id)
            visit(node.args[0], depth + 1)
            return

        raise ExpressionParseError(
            "unsupported_syntax",
            f"Unsupported syntax element: {type(node).__name__}",
        )

    visit(root)
    return frozenset(symbols), frozenset(functions), frozenset(parameters)


def parse_complexity_expression(
    notation: str,
    *,
    parameters: dict[str, float] | None = None,
    limits: ExpressionLimits = DEFAULT_LIMITS,
) -> ParseResult:
    """Parse and validate an asymptotic expression without executing it."""
    # Checks that a written complexity formula uses only the math this app knows how to handle.
    # What the inputs mean:
    # - notation: the complexity formula written as text.
    # - parameters: the named number values used in a formula.
    # - limits: the limits used for this step.
    # What it gives back: It returns the Parse Result result.
    if not isinstance(notation, str):
        return ParseResult("invalid", None, "invalid_type", "Notation must be a string.", {})

    if not notation.strip():
        return ParseResult("invalid", None, "empty_expression", "Notation cannot be empty.", {})

    try:
        _validate_limits(limits)
    except ExpressionParseError as exc:
        return ParseResult("invalid", None, exc.code, str(exc), {})

    if len(notation) > limits.max_characters:
        return ParseResult("invalid", None, "expression_too_long", "Notation exceeds the character limit.", {})

    if parameters is None:
        parameter_values = {}
    elif not isinstance(parameters, dict):
        return ParseResult(
            "invalid", None, "invalid_parameters",
            "Parameters must be a dictionary of numeric values.", {}
        )
    else:
        parameter_values = parameters

    if len(parameter_values) > limits.max_parameter_count:
        return ParseResult("invalid", None, "too_many_parameters", "Too many parameters were supplied.", {})

    for key, value in parameter_values.items():
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,31}", key):
            return ParseResult("invalid", None, "invalid_parameter_name", "Invalid parameter name.", {})
        if key in {"n", *ALLOWED_FUNCTIONS, *ALLOWED_CONSTANTS}:
            return ParseResult("invalid", None, "reserved_parameter_name", f"Reserved parameter name: {key}", {})
        try:
            valid_value = (
                not isinstance(value, bool)
                and isinstance(value, (int, float))
                and math.isfinite(float(value))
                and abs(float(value)) <= limits.max_numeric_literal
            )
        except (TypeError, ValueError, OverflowError):
            valid_value = False

        if not valid_value:
            return ParseResult(
                "invalid", None, "invalid_parameter_value",
                f"Parameter '{key}' must be a finite numeric value within the configured limit.", {}
            )

    try:
        body, family = _strip_asymptotic_wrapper(notation.strip())
        normalized = _normalize(notation)

        token_count = sum(1 for token in tokenize.generate_tokens(StringIO(normalized).readline)
                          if token.type not in {tokenize.ENDMARKER, tokenize.NEWLINE, tokenize.NL})
        if token_count > limits.max_tokens:
            raise ExpressionParseError("too_many_tokens", "Expression contains too many tokens.")

        try:
            tree = ast.parse(normalized, mode="eval")
        except (SyntaxError, ValueError) as exc:
            raise ExpressionParseError("syntax_error", "Expression could not be parsed as supported mathematical notation.") from exc

        symbols, functions, used_parameters = _walk_and_validate(tree, limits, parameter_values)

        parsed = ParsedExpression(
            original_notation=notation,
            normalized_expression=normalized,
            tree=tree,
            symbols=symbols,
            functions=functions,
            parameters=used_parameters,
            parameter_values={key: float(value) for key, value in parameter_values.items()},
            notation_family=family,
        )
        return ParseResult("completed", parsed, None, "Expression parsed and validated.", {
            "token_count": token_count,
            "node_count": sum(1 for _ in ast.walk(tree)),
            "parameter_count": len(used_parameters),
        })

    except ExpressionParseError as exc:
        return ParseResult("invalid", None, exc.code, str(exc), {})
    except tokenize.TokenError as exc:
        return ParseResult("invalid", None, "token_error", str(exc), {})
    except (RecursionError, MemoryError):
        return ParseResult(
            "invalid", None, "resource_limit",
            "Expression exceeded safe parser resource limits.", {}
        )
    except (SyntaxError, IndentationError, ValueError, OverflowError):
        return ParseResult(
            "invalid", None, "syntax_error",
            "Expression could not be parsed safely.", {}
        )
