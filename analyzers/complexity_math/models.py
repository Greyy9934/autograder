"""Typed models shared by the mathematical complexity engine."""
# This file handles models as one part of the app.

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ExpressionLimits:
    max_characters: int = 512
    max_tokens: int = 256
    max_ast_nodes: int = 256
    max_ast_depth: int = 32
    max_numeric_literal: float = 1e100
    max_exponent_literal: float = 10000.0
    max_parameter_count: int = 16


@dataclass(frozen=True)
class ParsedExpression:
    original_notation: str
    normalized_expression: str
    tree: ast.Expression
    symbols: frozenset[str]
    functions: frozenset[str]
    parameters: frozenset[str]
    parameter_values: dict[str, float]
    notation_family: str


@dataclass(frozen=True)
class ParseResult:
    status: str
    expression: ParsedExpression | None
    error_code: str | None
    message: str
    details: dict[str, Any]
