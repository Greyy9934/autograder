"""Safe numerical evaluator for validated complexity expressions.

This module evaluates only ASTs produced by the restricted parser.
It never evaluates Python source strings or calls Python eval().
"""
# Module role: Evaluates approved complexity expressions with explicit precision and work limits; mpmath supports very large/small values safely.
# Core concept: Bounded numerical evaluation lets the graph display very fast-growing or very slow-growing functions without allowing unbounded numeric work.

from __future__ import annotations

import ast
import math
from dataclasses import dataclass, field
from typing import Any

import mpmath as mp

from .models import ParsedExpression


@dataclass(frozen=True)
class EvaluationLimits:
    max_input_size: int = 10**9
    max_operations: int = 512
    max_factorial_input: int = 100_000
    max_precision: int = 100
    default_precision: int = 50
    max_absolute_exponent: int = 10**9


@dataclass
class EvaluationResult:
    status: str
    value: mp.mpf | None
    log_value: mp.mpf | None
    input_size: int
    error_code: str | None = None
    message: str = ""
    warnings: list[str] = field(default_factory=list)
    approximations: list[str] = field(default_factory=list)
    operations: int = 0
    precision_digits: int | None = None
    numerical_status: str = "not_evaluated"
    is_approximation: bool = False

    # Function role: Return JSON-friendly output without losing large-value information.
    # Context: method/helper owned by EvaluationResult; it is reached through that object's workflow.
    # Direct call references (conditional/branch-dependent): _format_number.
    def to_dict(self) -> dict[str, Any]:
        """Return JSON-friendly output without losing large-value information."""
        return {
            "status": self.status,
            "value": _format_number(self.value),
            "log_value": _format_number(self.log_value),
            "input_size": self.input_size,
            "error_code": self.error_code,
            "message": self.message,
            "warnings": list(self.warnings),
            "approximations": list(self.approximations),
            "operations": self.operations,
            "precision_digits": self.precision_digits,
            "numerical_status": self.numerical_status,
            "is_approximation": self.is_approximation,
        }


# Function role: Formats a bounded numeric result as stable human-readable text.
# Same-file callers: to_dict.
def _format_number(value: mp.mpf | None) -> str | None:
    if value is None:
        return None
    if mp.isnan(value):
        return "nan"
    if mp.isinf(value):
        return "+inf" if value > 0 else "-inf"
    return mp.nstr(value, 30)


# Function role: Rejects evaluation settings outside the explicit resource and numeric limits.
# Same-file callers: evaluate_complexity_expression.
def _validate_limits(limits: EvaluationLimits) -> None:
    if not isinstance(limits, EvaluationLimits):
        raise ValueError("limits must be an EvaluationLimits instance")

    integer_ranges = {
        "max_input_size": (1, 10**15),
        "max_operations": (1, 100_000),
        "max_factorial_input": (0, 1_000_000),
        "max_precision": (15, 200),
        "default_precision": (15, 200),
        "max_absolute_exponent": (1, 10**12),
    }

    for name, (minimum, maximum) in integer_ranges.items():
        value = getattr(limits, name)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{name} must be an integer")
        if not minimum <= value <= maximum:
            raise ValueError(f"{name} must be between {minimum} and {maximum}")

    if limits.default_precision > limits.max_precision:
        raise ValueError("default_precision cannot exceed max_precision")


# Function role: Count base-2 logarithms needed to bring value down to <= 1.
# Same-file callers: _function.
def _log_star(value: mp.mpf) -> mp.mpf:
    """Count base-2 logarithms needed to bring value down to <= 1."""
    if value <= 1:
        return mp.mpf(0)

    count = 0
    current = value

    while current > 1:
        current = mp.log(current, 2)
        count += 1
        if count > 256:
            raise ArithmeticError("log_star iteration limit exceeded")

    return mp.mpf(count)


# Function role: Small, explicitly approximate inverse-Ackermann growth function.
# Same-file callers: _function.
def _inverse_ackermann_approx(value: mp.mpf) -> mp.mpf:
    """Small, explicitly approximate inverse-Ackermann growth function.

    Uses conservative threshold levels. This is a graphing approximation,
    not an exact symbolic inverse of a particular Ackermann definition.
    """
    if value <= 1:
        return mp.mpf(1)

    thresholds = [
        mp.mpf(1),
        mp.mpf(2),
        mp.mpf(4),
        mp.mpf(16),
        mp.mpf(65536),
        mp.power(2, 65536),
    ]

    for level, threshold in enumerate(thresholds, start=1):
        if value <= threshold:
            return mp.mpf(level)

    return mp.mpf(len(thresholds) + 1)


class _EvaluationFailure(Exception):
    # Function role: Initializes the object and its validated dependencies.
    # Context: method/helper owned by _EvaluationFailure; it is reached through that object's workflow.
    # Same-file callers: __init__.
    # Direct call references (conditional/branch-dependent): __init__.
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class _Evaluator:
    # Function role: Initializes the object and its validated dependencies.
    # Context: method/helper owned by _Evaluator; it is reached through that object's workflow.
    # Same-file callers: __init__.
    def __init__(
        self,
        expression: ParsedExpression,
        input_size: int,
        limits: EvaluationLimits,
    ):
        self.expression = expression
        self.input_size = input_size
        self.limits = limits
        self.operations = 0
        self.warnings: list[str] = []
        self.approximations: list[str] = []

    # Function role: Implements the internal tick helper for evaluator.
    # Context: method/helper owned by _Evaluator; it is reached through that object's workflow.
    # Same-file callers: _function, visit.
    def _tick(self) -> None:
        self.operations += 1
        if self.operations > self.limits.max_operations:
            raise _EvaluationFailure(
                "operation_limit",
                "Expression exceeded the evaluation operation limit.",
            )

    # Function role: Implements the internal finite helper for evaluator.
    # Context: method/helper owned by _Evaluator; it is reached through that object's workflow.
    # Same-file callers: evaluate_complexity_expression, _power, _function, visit.
    def _finite(self, value: mp.mpf) -> mp.mpf:
        if not mp.isfinite(value):
            raise _EvaluationFailure(
                "non_finite_result",
                "Expression produced a non-finite numerical result.",
            )
        return value

    # Function role: Implements the internal power helper for evaluator.
    # Context: method/helper owned by _Evaluator; it is reached through that object's workflow.
    # Same-file callers: visit.
    # Direct call references (conditional/branch-dependent): _finite.
    def _power(self, base: mp.mpf, exponent: mp.mpf) -> mp.mpf:
        # A variable exponent such as 2^n must be allowed to grow with n.
        # The effective ceiling is bounded by both the configured exponent
        # limit and the maximum permitted input size.
        effective_limit = max(
            self.limits.max_absolute_exponent,
            self.input_size,
        )
        effective_limit = min(
            effective_limit,
            10**12,
        )

        if abs(exponent) > effective_limit:
            raise _EvaluationFailure(
                "exponent_limit",
                "Exponent exceeds the input-aware evaluation safety limit.",
            )

        if base == 0 and exponent < 0:
            raise _EvaluationFailure(
                "division_by_zero",
                "Zero cannot be raised to a negative power.",
            )

        if base < 0 and exponent != mp.floor(exponent):
            raise _EvaluationFailure(
                "complex_result",
                "A negative base with a non-integer exponent is outside the real-valued evaluator.",
            )

        try:
            return self._finite(mp.power(base, exponent))
        except (ValueError, ZeroDivisionError, OverflowError) as exc:
            raise _EvaluationFailure("invalid_power", str(exc)) from exc

    # Function role: Implements the internal function helper for evaluator.
    # Context: method/helper owned by _Evaluator; it is reached through that object's workflow.
    # Same-file callers: visit.
    # Direct call references (conditional/branch-dependent): _tick, _finite, _log_star, _inverse_ackermann_approx.
    def _function(self, name: str, argument: mp.mpf) -> mp.mpf:
        self._tick()

        if name in {"log", "ln", "log2", "log10"}:
            if argument <= 0:
                raise _EvaluationFailure(
                    "log_domain",
                    f"{name} requires a positive argument.",
                )
            if name == "log2":
                return self._finite(mp.log(argument, 2))
            if name == "log10":
                return self._finite(mp.log10(argument))
            return self._finite(mp.log(argument))

        if name == "sqrt":
            if argument < 0:
                raise _EvaluationFailure(
                    "sqrt_domain",
                    "sqrt requires a non-negative argument.",
                )
            return self._finite(mp.sqrt(argument))

        if name == "exp":
            return self._finite(mp.exp(argument))

        if name == "factorial":
            if argument < 0 or argument != mp.floor(argument):
                raise _EvaluationFailure(
                    "factorial_domain",
                    "factorial requires a non-negative integer.",
                )
            if argument > self.limits.max_factorial_input:
                raise _EvaluationFailure(
                    "factorial_limit",
                    "Factorial input exceeds the configured limit.",
                )
            return self._finite(mp.factorial(int(argument)))

        if name == "log_star":
            if argument < 0:
                raise _EvaluationFailure(
                    "log_star_domain",
                    "log_star requires a non-negative argument.",
                )
            self.approximations.append(
                "log_star is evaluated as the number of repeated base-2 logarithms."
            )
            return self._finite(_log_star(argument))

        if name == "alpha":
            if argument < 0:
                raise _EvaluationFailure(
                    "alpha_domain",
                    "alpha requires a non-negative argument.",
                )
            self.approximations.append(
                "alpha uses a threshold-based inverse-Ackermann approximation."
            )
            return self._finite(_inverse_ackermann_approx(argument))

        raise _EvaluationFailure(
            "unsupported_function",
            f"Unsupported mathematical function: {name}",
        )

    # Function role: Walks a validated syntax-tree node and evaluates or checks its supported children.
    # Context: method/helper owned by _Evaluator; it is reached through that object's workflow.
    # Same-file callers: evaluate_complexity_expression, visit.
    # Direct call references (conditional/branch-dependent): _tick, visit, _finite, _power, _function.
    def visit(self, node: ast.AST) -> mp.mpf:
        self._tick()

        if isinstance(node, ast.Expression):
            return self.visit(node.body)

        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                raise _EvaluationFailure(
                    "invalid_constant",
                    "Only real numeric constants can be evaluated.",
                )
            return self._finite(mp.mpf(node.value))

        if isinstance(node, ast.Name):
            if node.id == "n":
                return mp.mpf(self.input_size)
            if node.id == "pi":
                return mp.pi
            if node.id == "e":
                return mp.e
            if node.id in self.expression.parameter_values:
                return mp.mpf(self.expression.parameter_values[node.id])
            raise _EvaluationFailure(
                "unknown_symbol",
                f"No value is available for symbol '{node.id}'.",
            )

        if isinstance(node, ast.UnaryOp):
            value = self.visit(node.operand)
            if isinstance(node.op, ast.UAdd):
                return value
            if isinstance(node.op, ast.USub):
                return -value
            raise _EvaluationFailure(
                "unsupported_operator",
                "Unsupported unary operator.",
            )

        if isinstance(node, ast.BinOp):
            left = self.visit(node.left)
            right = self.visit(node.right)

            try:
                if isinstance(node.op, ast.Add):
                    return self._finite(left + right)
                if isinstance(node.op, ast.Sub):
                    return self._finite(left - right)
                if isinstance(node.op, ast.Mult):
                    return self._finite(left * right)
                if isinstance(node.op, ast.Div):
                    if right == 0:
                        raise _EvaluationFailure(
                            "division_by_zero",
                            "Division by zero is undefined.",
                        )
                    return self._finite(left / right)
                if isinstance(node.op, ast.Pow):
                    return self._power(left, right)
                if isinstance(node.op, ast.Mod):
                    if right == 0:
                        raise _EvaluationFailure(
                            "division_by_zero",
                            "Modulo by zero is undefined.",
                        )
                    return self._finite(mp.fmod(left, right))
            except _EvaluationFailure:
                raise
            except (ValueError, ZeroDivisionError, OverflowError) as exc:
                raise _EvaluationFailure("arithmetic_error", str(exc)) from exc

            raise _EvaluationFailure(
                "unsupported_operator",
                "Unsupported binary operator.",
            )

        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or len(node.args) != 1:
                raise _EvaluationFailure(
                    "invalid_function_call",
                    "Invalid mathematical function call.",
                )
            argument = self.visit(node.args[0])
            return self._function(node.func.id, argument)

        raise _EvaluationFailure(
            "unsupported_syntax",
            f"Unsupported AST element: {type(node).__name__}",
        )


# Function role: Evaluates the parsed expression under explicit input, operation, and numeric limits; bounded evaluation prevents pathological expressions from consuming unbounded resources.
# Direct call references (conditional/branch-dependent): _validate_limits, visit, _finite.
def evaluate_complexity_expression(
    expression: ParsedExpression,
    input_size: int,
    *,
    limits: EvaluationLimits = EvaluationLimits(),
    precision: int | None = None,
) -> EvaluationResult:
    """Evaluate a parser-validated expression at one positive input size."""
    if not isinstance(expression, ParsedExpression):
        return EvaluationResult(
            "invalid", None, None, 0,
            "invalid_expression",
            "A validated ParsedExpression is required.",
        )

    try:
        _validate_limits(limits)
    except (TypeError, ValueError) as exc:
        return EvaluationResult(
            "invalid", None, None, 0,
            "invalid_limits", str(exc),
        )

    if isinstance(input_size, bool) or not isinstance(input_size, int):
        return EvaluationResult(
            "invalid", None, None, 0,
            "invalid_input_size",
            "Input size must be a positive integer.",
        )

    if input_size < 1 or input_size > limits.max_input_size:
        return EvaluationResult(
            "invalid", None, None, input_size,
            "input_size_limit",
            "Input size is outside the configured permitted range.",
        )

    if precision is None:
        precision = limits.default_precision

    if (
        isinstance(precision, bool)
        or not isinstance(precision, int)
        or precision < 15
        or precision > limits.max_precision
    ):
        return EvaluationResult(
            "invalid", None, None, input_size,
            "invalid_precision",
            "Precision is outside the configured permitted range.",
        )

    try:
        with mp.workdps(precision):
            evaluator = _Evaluator(expression, input_size, limits)
            value = evaluator.visit(expression.tree)
            value = evaluator._finite(value)

            if value > 0:
                log_value = mp.log(value)
            elif value == 0:
                log_value = mp.ninf
            else:
                log_value = None
                evaluator.warnings.append(
                    "Negative-valued expressions are numerically valid but are not ordinary positive growth functions."
                )

            return EvaluationResult(
                status="completed",
                value=value,
                log_value=log_value,
                input_size=input_size,
                message="Expression evaluated successfully.",
                warnings=evaluator.warnings,
                approximations=evaluator.approximations,
                operations=evaluator.operations,
                precision_digits=precision,
                numerical_status=(
                    "approximate" if evaluator.approximations else "numerical"
                ),
                is_approximation=bool(evaluator.approximations),
            )

    except _EvaluationFailure as exc:
        return EvaluationResult(
            status="invalid",
            value=None,
            log_value=None,
            input_size=input_size,
            error_code=exc.code,
            message=str(exc),
        )
    except (ValueError, ZeroDivisionError, OverflowError, ArithmeticError) as exc:
        return EvaluationResult(
            status="invalid",
            value=None,
            log_value=None,
            input_size=input_size,
            error_code="numerical_error",
            message=f"Numerical evaluation failed safely: {exc}",
        )
    except (MemoryError, RecursionError):
        return EvaluationResult(
            status="invalid",
            value=None,
            log_value=None,
            input_size=input_size,
            error_code="resource_limit",
            message="Evaluation exceeded safe resource limits.",
        )
