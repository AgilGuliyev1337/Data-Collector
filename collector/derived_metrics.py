"""
Phase 13 — Derived Metrics / Recipe Engine.

AST-based safe evaluator (NO eval()) for formula computation.

Supported operations: +, -, *, /, parentheses, numbers, variables.
No function calls, imports, or attribute access allowed.

Recipes:
- growth_pct: (current - previous) / previous * 100
- per_capita: total / population
- ratio: numerator / denominator
- diff: current - previous
- cumsum: cumulative sum (special)
"""

import ast
import logging
from dataclasses import dataclass, field
from typing import Optional

from collector.collection import DataPoint

logger = logging.getLogger("collector.derived")

# ---------------------------------------------------------------------------
# Safe arithmetic evaluator
# ---------------------------------------------------------------------------


class _UnsafeExpressionError(ValueError):
    """Raised when an expression contains unsafe constructs."""


class _Evaluator(ast.NodeVisitor):
    """Validate that an AST only contains safe arithmetic operations."""

    _ALLOWED_NODES = (
        ast.Expression, ast.BinOp, ast.UnaryOp,
        ast.Add, ast.Sub, ast.Mult, ast.Div,
        ast.Pow, ast.Mod, ast.FloorDiv,
        ast.Constant, ast.Num, ast.Name,
    )
    _ALLOWED_OPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod, ast.FloorDiv)
    _ALLOWED_UNARY = (ast.UAdd, ast.USub)

    def visit(self, node):
        if not isinstance(node, self._ALLOWED_NODES):
            raise _UnsafeExpressionError(
                f"Unsafe node type: {type(node).__name__}"
            )
        super().visit(node)

    def visit_UnaryOp(self, node):
        if not isinstance(node.op, self._ALLOWED_UNARY):
            raise _UnsafeExpressionError(f"Unsafe unary op: {type(node.op).__name__}")
        self.visit(node.operand)

    def visit_BinOp(self, node):
        if not isinstance(node.op, self._ALLOWED_OPS):
            raise _UnsafeExpressionError(f"Unsafe bin op: {type(node.op).__name__}")
        self.visit(node.left)
        self.visit(node.right)

    def visit_Name(self, node):
        if not isinstance(node.ctx, type(ast.Name("x", ast.Load()).ctx)):
            raise _UnsafeExpressionError("Write access not allowed")


def safe_eval(expression: str, variables: dict) -> float:
    """Safely evaluate an arithmetic expression with variables.

    Uses AST parsing to reject function calls, imports, attributes, etc.

    Args:
        expression: Arithmetic expression string.
            Variables are substituted from `variables` dict.
            Example: "(current - previous) / previous * 100"
        variables: Mapping of variable names to float values.

    Returns:
        Computed float value.

    Raises:
        ValueError: If expression contains unsafe constructs.
        ZeroDivisionError: If division by zero.
    """
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as e:
        raise ValueError(f"Invalid expression syntax: {e}") from e

    # Validate safety
    evaluator = _Evaluator()
    evaluator.visit(tree)

    # Evaluate safely
    def _eval_node(node):
        if isinstance(node, ast.Expression):
            return _eval_node(node.body)
        elif isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                return float(node.value)
            raise ValueError(f"Unsupported constant: {node.value}")
        elif isinstance(node, ast.Num):  # Legacy Python
            return float(node.n)
        elif isinstance(node, ast.Name):
            if node.id in variables:
                val = variables[node.id]
                if val is None:
                    return None
                return float(val)
            raise ValueError(f"Undefined variable: {node.id}")
        elif isinstance(node, ast.BinOp):
            left = _eval_node(node.left)
            right = _eval_node(node.right)
            if left is None or right is None:
                return None
            if isinstance(node.op, ast.Add):
                return left + right
            elif isinstance(node.op, ast.Sub):
                return left - right
            elif isinstance(node.op, ast.Mult):
                return left * right
            elif isinstance(node.op, ast.Div):
                if right == 0:
                    return None  # Safe division by zero
                return left / right
            elif isinstance(node.op, ast.Pow):
                return left ** right
            elif isinstance(node.op, ast.Mod):
                if right == 0:
                    return None
                return left % right
            elif isinstance(node.op, ast.FloorDiv):
                if right == 0:
                    return None
                return left // right
        elif isinstance(node, ast.UnaryOp):
            operand = _eval_node(node.operand)
            if operand is None:
                return None
            if isinstance(node.op, ast.UAdd):
                return +operand
            elif isinstance(node.op, ast.USub):
                return -operand
        raise ValueError(f"Unsupported node: {type(node).__name__}")

    result = _eval_node(tree)
    if result is None:
        return None
    return float(result)


# ---------------------------------------------------------------------------
# Convenience calculation functions
# ---------------------------------------------------------------------------


def calculate_growth(current: float, previous: float) -> Optional[float]:
    """Calculate percentage growth rate.

    Args:
        current: Current period value.
        previous: Previous period value.

    Returns:
        Percentage change, or None if previous is zero.
    """
    if previous is None or previous == 0:
        return None
    return (current - previous) / abs(previous) * 100


def calculate_ratio(numerator: float, denominator: float) -> Optional[float]:
    """Calculate a simple ratio.

    Args:
        numerator: Top of the ratio.
        denominator: Bottom of the ratio.

    Returns:
        Ratio value, or None if denominator is zero.
    """
    if denominator is None or denominator == 0:
        return None
    return numerator / denominator


def calculate_moving_average(
    values: list[Optional[float]], window: int
) -> list[Optional[float]]:
    """Calculate moving average with given window size.

    Args:
        values: Sequence of values (may contain None).
        window: Number of points to average.

    Returns:
        List of moving averages. First window-1 values are None.
    """
    result: list[Optional[float]] = []
    for i in range(len(values)):
        if i < window - 1:
            result.append(None)
            continue

        window_values = []
        for j in range(i - window + 1, i + 1):
            v = values[j]
            if v is not None:
                window_values.append(v)

        if not window_values:
            result.append(None)
        else:
            result.append(sum(window_values) / len(window_values))

    return result


# ---------------------------------------------------------------------------
# RecipeEngine
# ---------------------------------------------------------------------------


@dataclass
class Recipe:
    """A named formula with its parameters."""
    name: str
    formula: str
    variables: list[str]
    description: str = ""


DEFAULT_RECIPES = {
    "growth_pct": Recipe(
        name="growth_pct",
        formula="(current - previous) / previous * 100",
        variables=["current", "previous"],
        description="Percentage growth rate",
    ),
    "per_capita": Recipe(
        name="per_capita",
        formula="total / population",
        variables=["total", "population"],
        description="Per capita calculation",
    ),
    "ratio": Recipe(
        name="ratio",
        formula="numerator / denominator",
        variables=["numerator", "denominator"],
        description="Simple ratio",
    ),
    "diff": Recipe(
        name="diff",
        formula="current - previous",
        variables=["current", "previous"],
        description="Absolute difference",
    ),
    "cumsum": Recipe(
        name="cumsum",
        formula="running_total",
        variables=["running_total"],
        description="Cumulative sum (special handling)",
    ),
}


class RecipeEngine:
    """Evaluate named recipes against variable sets."""

    def __init__(self, recipes: dict[str, Recipe] | None = None):
        self.recipes = recipes or dict(DEFAULT_RECIPES)

    def add_recipe(self, name: str, formula: str, variables: list[str],
                   description: str = ""):
        """Add or override a recipe."""
        self.recipes[name] = Recipe(
            name=name, formula=formula, variables=variables,
            description=description,
        )

    def evaluate(self, name: str, variables: dict) -> Optional[float]:
        """Evaluate a named recipe.

        Args:
            name: Recipe name.
            variables: Variable values dict.

        Returns:
            Computed value, or None on error.
        """
        recipe = self.recipes.get(name)
        if not recipe:
            logger.warning("Unknown recipe: %s", name)
            return None

        try:
            return safe_eval(recipe.formula, variables)
        except (_UnsafeExpressionError, ValueError) as e:
            logger.error("Recipe '%s' evaluation error: %s", name, e)
            return None
        except ZeroDivisionError:
            return None

    def evaluate_all(self, name: str,
                     variable_sets: list[dict]) -> list[Optional[float]]:
        """Evaluate a recipe across multiple variable sets.

        Args:
            name: Recipe name.
            variable_sets: List of variable dicts.

        Returns:
            List of computed values (one per variable set).
        """
        return [self.evaluate(name, vs) for vs in variable_sets]

    def get_available(self) -> list[str]:
        """List available recipe names."""
        return list(self.recipes.keys())


# ---------------------------------------------------------------------------
# Apply recipes to DataPoints
# ---------------------------------------------------------------------------


def apply_recipes(
    points: list[DataPoint],
    recipes: dict[str, Recipe] | None = None,
    context: dict | None = None,
) -> list[DataPoint]:
    """Apply recipe engine to DataPoints, adding derived values to metadata.

    Args:
        points: DataPoints to process.
        recipes: Optional custom recipes (uses DEFAULT_RECIPES if None).
        context: Additional context variables available to all recipes.

    Returns:
        Same points with '_derived' metadata added.
    """
    engine = RecipeEngine(recipes or dict(DEFAULT_RECIPES))
    ctx = context or {}

    for dp in points:
        variables = {**ctx, "current": dp.value or 0}
        derived: dict = {}

        for name in engine.get_available():
            recipe = engine.recipes[name]
            # Check all variables are available
            available = {k: v for k, v in variables.items() if k in recipe.variables}
            if len(available) == len(recipe.variables):
                result = engine.evaluate(name, available)
                if result is not None:
                    derived[name] = result

        dp.metadata["_derived"] = dp.metadata.get("_derived", {})
        dp.metadata["_derived"].update(derived)

    return points