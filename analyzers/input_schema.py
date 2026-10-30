"""Explicit, deterministic input schemas for generated C-program tests."""

from dataclasses import dataclass
import random


@dataclass(frozen=True)
class IntegerInputSchema:
    token_count: int
    minimum: int
    maximum: int

    def __post_init__(self):
        if isinstance(self.token_count, bool) or not isinstance(self.token_count, int) or self.token_count < 1:
            raise ValueError("token_count must be a positive integer")
        if isinstance(self.minimum, bool) or not isinstance(self.minimum, int):
            raise ValueError("minimum must be an integer")
        if isinstance(self.maximum, bool) or not isinstance(self.maximum, int):
            raise ValueError("maximum must be an integer")
        if self.minimum > self.maximum:
            raise ValueError("minimum cannot exceed maximum")

    def validate(self, text: str) -> bool:
        if not isinstance(text, str):
            return False
        try:
            tokens = text.split()
            if len(tokens) != self.token_count:
                return False
            values = [int(token) for token in tokens]
            return all(self.minimum <= value <= self.maximum for value in values)
        except ValueError:
            return False

    def generate(self, rng: random.Random, distribution: str) -> str:
        if distribution == "uniform":
            values = [rng.randint(self.minimum, self.maximum) for _ in range(self.token_count)]
        elif distribution == "boundary_biased":
            boundaries = sorted(set((
                self.minimum,
                min(self.minimum + 1, self.maximum),
                0 if self.minimum <= 0 <= self.maximum else self.minimum,
                max(self.maximum - 1, self.minimum),
                self.maximum,
            )))
            values = [rng.choice(boundaries) for _ in range(self.token_count)]
        elif distribution == "duplicate_heavy":
            value = rng.randint(self.minimum, self.maximum)
            values = [value] * self.token_count
        elif distribution in ("sorted", "reverse_sorted"):
            values = [rng.randint(self.minimum, self.maximum) for _ in range(self.token_count)]
            values.sort(reverse=(distribution == "reverse_sorted"))
        else:
            raise ValueError("Unsupported distribution")
        return " ".join(map(str, values)) + "\n"
