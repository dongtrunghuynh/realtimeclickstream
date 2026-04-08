"""
Cart total calculator for a session's events.

Accumulates price for 'cart' events. 'purchase' events record the final
conversion value. 'view' events do not affect the cart total.

Note: The REES46 dataset does not include 'remove_from_cart' events, but
this implementation is structured to support them if the schema is extended.
"""

import logging

logger = logging.getLogger(__name__)


class CartCalculator:
    """Computes running cart totals from a list of session events."""

    ADDITIVE_TYPES = {"cart"}
    SUBTRACTIVE_TYPES = set()  # add "remove_from_cart" if dataset supports it
    CONVERSION_TYPE = "purchase"

    def compute(self, events: list[dict]) -> float:
        """
        Sum prices for cart-adding events, subtract for cart-removing events.

        Args:
            events: List of event dicts for a single session, ordered by event_time.

        Returns:
            Float cart total (always >= 0).
        """
        total = 0.0
        for event in events:
            event_type = event.get("event_type", "")
            price = _safe_price(event.get("price"))

            if event_type in self.ADDITIVE_TYPES:
                total += price
            elif event_type in self.SUBTRACTIVE_TYPES:
                total = max(0.0, total - price)  # never go below 0
            elif event_type == self.CONVERSION_TYPE:
                # Purchase uses its own price — record separately, don't add
                pass

        return round(total, 2)

    def get_conversion_value(self, events: list[dict]) -> float:
        """
        Sum of prices for purchase events (the actual revenue).
        For this dataset, there's typically 0 or 1 purchase per session.
        """
        return round(
            sum(
                _safe_price(e.get("price"))
                for e in events
                if e.get("event_type") == self.CONVERSION_TYPE
            ),
            2,
        )


def _safe_price(price) -> float:
    """Return float price, defaulting to 0.0 for None/NaN/invalid values."""
    try:
        val = float(price)
        return val if val >= 0 else 0.0
    except (TypeError, ValueError):
        return 0.0
