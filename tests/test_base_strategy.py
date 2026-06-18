import pytest
from strategies.base_strategy import BaseStrategy
from strategies.ema_strategy import EMAStrategy


def test_base_strategy_constants():
    assert BaseStrategy.BUY == "BUY"
    assert BaseStrategy.SELL == "SELL"
    assert BaseStrategy.HOLD == "HOLD"


def test_cannot_instantiate_base_strategy_directly():
    """BaseStrategy is abstract — cannot be instantiated."""
    with pytest.raises(TypeError):
        BaseStrategy()


def test_ema_strategy_is_base_strategy():
    s = EMAStrategy()
    assert isinstance(s, BaseStrategy)


def test_base_strategy_has_generate_signal():
    assert hasattr(BaseStrategy, "generate_signal")


def test_base_strategy_has_name_property():
    assert hasattr(BaseStrategy, "name")


def test_base_strategy_has_min_periods_property():
    assert hasattr(BaseStrategy, "min_periods")


def test_concrete_strategy_name_is_string():
    s = EMAStrategy()
    assert isinstance(s.name, str)


def test_concrete_strategy_min_periods_is_int():
    s = EMAStrategy()
    assert isinstance(s.min_periods, int)


def test_repr_contains_class_name():
    s = EMAStrategy()
    assert "EMAStrategy" in repr(s)
