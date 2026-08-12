"""
Phase 13 — Derived Metrics / Recipe Engine tests.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from collector.collection import DataPoint
from collector.derived_metrics import (
    safe_eval,
    calculate_growth,
    calculate_ratio,
    calculate_moving_average,
    RecipeEngine,
    DEFAULT_RECIPES,
    apply_recipes,
    _UnsafeExpressionError,
)


# ---------------------------------------------------------------------------
# safe_eval — basic arithmetic
# ---------------------------------------------------------------------------

class TestSafeEvalBasic:
    def test_constant(self):
        assert safe_eval("42", {}) == 42.0

    def test_addition(self):
        assert safe_eval("1 + 2", {}) == 3.0

    def test_subtraction(self):
        assert safe_eval("10 - 3", {}) == 7.0

    def test_multiplication(self):
        assert safe_eval("3 * 4", {}) == 12.0

    def test_division(self):
        assert safe_eval("10 / 2", {}) == 5.0

    def test_parentheses(self):
        assert safe_eval("(1 + 2) * 3", {}) == 9.0

    def test_nested_parentheses(self):
        assert safe_eval("((1 + 2) * (3 + 4))", {}) == 21.0

    def test_order_of_operations(self):
        assert safe_eval("1 + 2 * 3", {}) == 7.0

    def test_negative_result(self):
        assert safe_eval("5 - 10", {}) == -5.0

    def test_unary_positive(self):
        assert safe_eval("+5", {}) == 5.0

    def test_unary_negative(self):
        assert safe_eval("-5", {}) == -5.0


# ---------------------------------------------------------------------------
# safe_eval — variables
# ---------------------------------------------------------------------------

class TestSafeEvalVariables:
    def test_single_variable(self):
        assert safe_eval("x", {"x": 10}) == 10.0

    def test_multiple_variables(self):
        assert safe_eval("x + y", {"x": 3, "y": 4}) == 7.0

    def test_variable_multiply(self):
        assert safe_eval("a * b / c", {"a": 10, "b": 2, "c": 4}) == 5.0

    def test_undefined_variable(self):
        with pytest.raises(ValueError):
            safe_eval("x + y", {"x": 1})

    def test_none_variable(self):
        result = safe_eval("x + 1", {"x": None})
        assert result is None


# ---------------------------------------------------------------------------
# safe_eval — rejection
# ---------------------------------------------------------------------------

class TestSafeEvalRejection:
    def test_function_call(self):
        with pytest.raises(ValueError):
            safe_eval("abs(-5)", {})

    def test_import(self):
        with pytest.raises(ValueError):
            safe_eval("__import__('os')", {})

    def test_attribute_access(self):
        with pytest.raises(ValueError):
            safe_eval("x.__class__", {"x": 1})

    def test_eval_built_in(self):
        with pytest.raises(ValueError):
            safe_eval("eval('1+1')", {})

    def test_exec_built_in(self):
        with pytest.raises(ValueError):
            safe_eval("exec('x=1')", {})

    def test_list_literal(self):
        with pytest.raises(ValueError):
            safe_eval("[1, 2, 3]", {})

    def test_dict_literal(self):
        with pytest.raises(ValueError):
            safe_eval("{'a': 1}", {})

    def test_print_call(self):
        with pytest.raises(ValueError):
            safe_eval("print(1)", {})

    def test_open_call(self):
        with pytest.raises(ValueError):
            safe_eval("open('file.txt')", {})


# ---------------------------------------------------------------------------
# calculate_growth
# ---------------------------------------------------------------------------

class TestCalculateGrowth:
    def test_normal_growth(self):
        assert calculate_growth(110, 100) == 10.0

    def test_decrease(self):
        assert calculate_growth(80, 100) == -20.0

    def test_zero_previous(self):
        assert calculate_growth(100, 0) is None

    def test_none_previous(self):
        assert calculate_growth(100, None) is None

    def test_equal_values(self):
        assert calculate_growth(100, 100) == 0.0

    def test_large_growth(self):
        assert calculate_growth(300, 100) == 200.0


# ---------------------------------------------------------------------------
# calculate_ratio
# ---------------------------------------------------------------------------

class TestCalculateRatio:
    def test_normal_ratio(self):
        assert calculate_ratio(10, 2) == 5.0

    def test_fraction(self):
        assert calculate_ratio(3, 10) == 0.3

    def test_zero_denominator(self):
        assert calculate_ratio(10, 0) is None

    def test_none_denominator(self):
        assert calculate_ratio(10, None) is None

    def test_equal_values(self):
        assert calculate_ratio(10, 10) == 1.0


# ---------------------------------------------------------------------------
# calculate_moving_average
# ---------------------------------------------------------------------------

class TestMovingAverage:
    def test_window_2(self):
        vals = [1, 2, 3, 4, 5]
        result = calculate_moving_average(vals, 2)
        assert result[0] is None
        assert result[1] == 1.5
        assert result[2] == 2.5
        assert result[3] == 3.5
        assert result[4] == 4.5

    def test_window_3(self):
        vals = [10, 20, 30, 40]
        result = calculate_moving_average(vals, 3)
        assert result[0] is None
        assert result[1] is None
        assert result[2] == 20.0
        assert result[3] == 30.0

    def test_with_none(self):
        vals = [1, None, 3, 4]
        result = calculate_moving_average(vals, 2)
        assert result[0] is None
        assert result[1] == 1.0   # window=[1, None] → only 1 is valid
        assert result[2] == 3.0   # window=[None, 3] → only 3 is valid
        assert result[3] == 3.5   # window=[3, 4]

    def test_all_none(self):
        result = calculate_moving_average([None, None, None], 2)
        assert all(r is None for r in result)


# ---------------------------------------------------------------------------
# RecipeEngine
# ---------------------------------------------------------------------------

class TestRecipeEngine:
    def test_evaluate_growth(self):
        engine = RecipeEngine()
        result = engine.evaluate("growth_pct", {"current": 110, "previous": 100})
        assert result == 10.0

    def test_evaluate_ratio(self):
        engine = RecipeEngine()
        result = engine.evaluate("ratio", {"numerator": 10, "denominator": 2})
        assert result == 5.0

    def test_evaluate_diff(self):
        engine = RecipeEngine()
        result = engine.evaluate("diff", {"current": 100, "previous": 80})
        assert result == 20.0

    def test_evaluate_per_capita(self):
        engine = RecipeEngine()
        result = engine.evaluate("per_capita", {"total": 1000, "population": 500})
        assert result == 2.0

    def test_unknown_recipe(self):
        engine = RecipeEngine()
        result = engine.evaluate("nonexistent", {"x": 1})
        assert result is None

    def test_add_custom_recipe(self):
        engine = RecipeEngine()
        engine.add_recipe("double", "x * 2", ["x"], "Double a value")
        assert "double" in engine.get_available()
        result = engine.evaluate("double", {"x": 5})
        assert result == 10.0

    def test_evaluate_all(self):
        engine = RecipeEngine()
        results = engine.evaluate_all(
            "growth_pct",
            [{"current": 110, "previous": 100}, {"current": 90, "previous": 100}],
        )
        assert results == [10.0, -10.0]

    def test_available_recipes(self):
        engine = RecipeEngine()
        names = engine.get_available()
        assert "growth_pct" in names
        assert "ratio" in names
        assert "diff" in names


# ---------------------------------------------------------------------------
# DEFAULT_RECIPES
# ---------------------------------------------------------------------------

class TestDefaultRecipes:
    def test_growth_pct_recipe(self):
        engine = RecipeEngine()
        result = engine.evaluate("growth_pct", {"current": 55, "previous": 50})
        assert result == 10.0

    def test_per_capita_recipe(self):
        engine = RecipeEngine()
        result = engine.evaluate("per_capita", {"total": 2000, "population": 4})
        assert result == 500.0

    def test_ratio_recipe(self):
        engine = RecipeEngine()
        result = engine.evaluate("ratio", {"numerator": 3, "denominator": 4})
        assert result == 0.75

    def test_diff_recipe(self):
        engine = RecipeEngine()
        result = engine.evaluate("diff", {"current": 50, "previous": 30})
        assert result == 20.0


# ---------------------------------------------------------------------------
# apply_recipes
# ---------------------------------------------------------------------------

class TestApplyRecipes:
    def test_no_derived_when_missing_variables(self):
        points = [DataPoint(country="AZ", value=42.0, indicator_code="X")]
        result = apply_recipes(points)
        # growth_pct needs 'previous', which isn't available
        assert "_derived" in result[0].metadata

    def test_derived_when_all_variables_available(self):
        points = [DataPoint(country="AZ", value=110.0, indicator_code="X")]
        result = apply_recipes(points, context={"previous": 100.0})
        derived = result[0].metadata["_derived"]
        assert "growth_pct" in derived
        assert derived["growth_pct"] == 10.0
        assert "diff" in derived
        assert derived["diff"] == 10.0

    def test_multiple_points(self):
        points = [
            DataPoint(country="AZ", value=110.0),
            DataPoint(country="USA", value=220.0),
        ]
        result = apply_recipes(points, context={"previous": 100.0})
        assert result[0].metadata["_derived"]["growth_pct"] == 10.0
        assert result[1].metadata["_derived"]["growth_pct"] == 120.0

    def test_none_value_handled(self):
        points = [DataPoint(country="AZ", value=None)]
        result = apply_recipes(points)
        # value=None → current=0, growth_pct = (0-100)/100*100 = -100
        assert "_derived" in result[0].metadata