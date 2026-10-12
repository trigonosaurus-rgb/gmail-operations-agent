"""Token prices, versioned by date. A call's cost is computed once and stored with it.

When prices change, add the new numbers and bump PRICING_VERSION; stored costs stay
as they were billed.
"""

from dataclasses import dataclass

PRICING_VERSION = "2026-10-12"


@dataclass(frozen=True)
class Price:
    """USD per 1M tokens."""

    input: float
    cached_input: float
    output: float


# Sources (checked 2026-10-12):
# https://developers.openai.com/api/docs/models/gpt-6-luna
# https://developers.openai.com/api/docs/models/gpt-6.1-sol
PRICES: dict[str, Price] = {
    "gpt-6-luna": Price(input=0.10, cached_input=0.01, output=0.50),
    "gpt-6.1-sol": Price(input=2.00, cached_input=0.10, output=10.00),
}


def cost_usd(model: str, input_tokens: int, cached_tokens: int, output_tokens: int) -> float | None:
    """Cost of one call, or None for a model without a known price."""
    price = PRICES.get(model)
    if price is None:
        return None
    uncached = max(input_tokens - cached_tokens, 0)
    total = (
        uncached * price.input + cached_tokens * price.cached_input + output_tokens * price.output
    )
    return total / 1_000_000
