from __future__ import annotations
from abc import ABC, abstractmethod


class BaseStrategy(ABC):
    """
    Abstract base class for all Hyper-Engine trading strategies.

    Every strategy must:
    1. Inherit from BaseStrategy
    2. Implement generate_signal()
    3. Never place orders directly — signal only

    The execution engine calls generate_signal() and decides what to do.
    The strategy just says what it sees.
    """

    # Valid signal values — nothing else is allowed
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"

    @abstractmethod
    def generate_signal(self, closes: list[float]) -> str:
        """
        Generates a trading signal from a list of close prices.

        Args:
            closes: List of closing prices, oldest first.
                    Must have enough data for the strategy's indicators.

        Returns:
            One of: "BUY", "SELL", "HOLD"

        This method must be implemented by every strategy.
        It must never place orders, make API calls, or have side effects.
        Pure function: same input always produces same output.
        """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name for this strategy. e.g. 'EMA Crossover 9/21'"""

    @property
    @abstractmethod
    def min_periods(self) -> int:
        """
        Minimum number of closes needed before a signal can be generated.
        If len(closes) < min_periods, generate_signal() must return HOLD.
        """

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name!r})"
