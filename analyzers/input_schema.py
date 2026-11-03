"""Explicit, deterministic input schemas for generated C-program tests."""
# Module role: Implements the input schema subsystem used by the AutoGrader workflow.

from dataclasses import dataclass
import random


@dataclass(frozen=True)
class IntegerInputSchema:
    token_count: int
    minimum: int
    maximum: int

    # Function role: Validates the constructed data object's invariants and canonicalizes supported fields.
    # Context: method/helper owned by IntegerInputSchema; it is reached through that object's workflow.
    def __post_init__(self):
        # In-function documentation:
        # Parameters: none.
        #   - self/cls: receiver carrying the current object or class state.
        # Returns: the operation result consumed by its caller.
        # Flow: branch on validation or workflow conditions.
        if isinstance(self.token_count, bool) or not isinstance(self.token_count, int) or self.token_count < 1:
            raise ValueError("token_count must be a positive integer")
        if isinstance(self.minimum, bool) or not isinstance(self.minimum, int):
            raise ValueError("minimum must be an integer")
        if isinstance(self.maximum, bool) or not isinstance(self.maximum, int):
            raise ValueError("maximum must be an integer")
        if self.minimum > self.maximum:
            raise ValueError("minimum cannot exceed maximum")

    # Function role: Checks the supplied value against this module's explicit contract and returns a validation result.
    # Context: method/helper owned by IntegerInputSchema; it is reached through that object's workflow.
    def validate(self, text: str) -> bool:
        # In-function documentation:
        # Parameters:
        #   - text: source or display text being parsed or rendered (type annotation: str).
        #   - self/cls: receiver carrying the current object or class state.
        # Returns: a value of declared type bool; alternate return paths may produce the result produced by the delegated helper, a boolean indicating whether the condition passed.
        # Flow: branch on validation or workflow conditions; convert expected failures into controlled results.
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

    # Function role: Produces cases from the supplied schema, random seed, and selected distribution.
    # Context: method/helper owned by IntegerInputSchema; it is reached through that object's workflow.
    def generate(self, rng: random.Random, distribution: str) -> str:
        # In-function documentation:
        # Parameters:
        #   - rng: the rng value used by this operation (type annotation: random.Random).
        #   - distribution: sampling strategy used to generate values (type annotation: str).
        #   - self/cls: receiver carrying the current object or class state.
        # Returns: a value of declared type str.
        # Flow: branch on validation or workflow conditions; return the stage result.
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
