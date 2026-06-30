"""
calendar — Calendar abstraction and concrete implementations.

A :class:`Calendar` defines which dates are business days. Derived classes
add holiday sets on top of the weekend-only base.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date


class Calendar(ABC):
    """Abstract base class for financial calendars."""

    @abstractmethod
    def is_business_day(self, d: date) -> bool:
        """Return ``True`` if *d* is a business day in this calendar."""

    def is_holiday(self, d: date) -> bool:
        """Return ``True`` if *d* is NOT a business day."""
        return not self.is_business_day(d)


class WeekendsOnly(Calendar):
    """
    A calendar that treats Saturday and Sunday as non-business days.

    No public holidays are observed.  Useful as a base or for markets
    where the only non-business days are weekends.
    """

    def is_business_day(self, d: date) -> bool:
        # weekday(): Monday=0 … Friday=4, Saturday=5, Sunday=6
        return d.weekday() < 5
