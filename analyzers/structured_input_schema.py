"""Strict, deterministic schemas for whitespace-separated integer input."""
# Module role: Parses, validates, sizes, and deterministically generates supported integer-token input grammars.

from dataclasses import dataclass
import random
from analyzers.workload_limits import max_generated_array_length


@dataclass(frozen=True)
class StructuredIntegerInputSchema:
    fields: tuple[dict, ...]
    size_field: str | None = None
    version: int = 1

    # Function role: Validates the constructed data object's invariants and canonicalizes supported fields.
    # Context: method/helper owned by StructuredIntegerInputSchema; it is reached through that object's workflow.
    def __post_init__(self):
        if self.version != 1 or not isinstance(self.fields, tuple) or not self.fields:
            raise ValueError("Schema version 1 requires a non-empty fields tuple.")
        if len(self.fields) > 20:
            raise ValueError("At most 20 input fields are supported.")

        known = {}
        for field in self.fields:
            if not isinstance(field, dict):
                raise ValueError("Each field must be an object.")
            name, kind = field.get("name"), field.get("type")
            if not isinstance(name, str) or not name or name in known:
                raise ValueError("Field names must be unique, non-empty strings.")
            if kind not in {"int", "int_array"}:
                raise ValueError(f"Unsupported field type for {name!r}.")

            minimum, maximum = field.get("min"), field.get("max")
            if any(isinstance(x, bool) or not isinstance(x, int)
                   for x in (minimum, maximum)) or minimum > maximum:
                raise ValueError(f"Invalid integer bounds for {name!r}.")

            if kind == "int_array":
                length_from = field.get("length_from")
                if length_from not in known or known[length_from]["type"] != "int":
                    raise ValueError(
                        f"{name!r} must use an earlier integer field as length_from."
                    )
            elif "length_from" in field:
                raise ValueError("Only int_array fields may use length_from.")

            known[name] = field

        if self.size_field is not None:
            if self.size_field not in known:
                raise ValueError("size_field must name a declared input field.")
            if known[self.size_field]["type"] not in {"int", "int_array"}:
                raise ValueError("size_field must name an int or int_array field.")

    # Function role: Builds a validated model from the external dictionary representation.
    # Context: method/helper owned by StructuredIntegerInputSchema; it is reached through that object's workflow.
    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict) or set(data) - {"version", "fields", "size_field"}:
            raise ValueError("Invalid structured input schema object.")
        fields = data.get("fields")
        if not isinstance(fields, list):
            raise ValueError("Schema fields must be a list.")
        return cls(
            fields=tuple(dict(field) for field in fields),
            size_field=data.get("size_field"),
            version=data.get("version", 1),
        )

    # Function role: Serializes the internal model to the stable plain-dictionary shape used by API and persistence boundaries.
    # Context: method/helper owned by StructuredIntegerInputSchema; it is reached through that object's workflow.
    def to_dict(self):
        return {
            "version": self.version,
            "fields": [dict(field) for field in self.fields],
            "size_field": self.size_field,
        }

    # Function role: Parses input according to the declared grammar and rejects missing, extra, or out-of-range values.
    # Context: method/helper owned by StructuredIntegerInputSchema; it is reached through that object's workflow.
    # Same-file callers: validate, input_size.
    def parse(self, text):
        if not isinstance(text, str):
            raise ValueError("Input must be text.")
        tokens = text.split()
        position = 0
        values = {}

        for field in self.fields:
            name = field["name"]
            count = 1
            if field["type"] == "int_array":
                count = values[field["length_from"]]
                if count < 0:
                    raise ValueError(f"Array length {name!r} cannot be negative.")

            if position + count > len(tokens):
                raise ValueError(f"Input is missing values for {name!r}.")

            try:
                parsed = [int(token, 10) for token in tokens[position:position + count]]
            except ValueError as exc:
                raise ValueError(f"Field {name!r} contains a non-integer token.") from exc
            position += count

            if any(not field["min"] <= value <= field["max"] for value in parsed):
                raise ValueError(f"Field {name!r} contains a value outside its bounds.")
            values[name] = parsed[0] if field["type"] == "int" else parsed

        if position != len(tokens):
            raise ValueError("Input contains unexpected extra values.")
        return values

    # Function role: Checks the supplied value against this module's explicit contract and returns a validation result.
    # Context: method/helper owned by StructuredIntegerInputSchema; it is reached through that object's workflow.
    # Same-file callers: generate.
    # Direct call references (conditional/branch-dependent): parse.
    def validate(self, text):
        try:
            self.parse(text)
            return True
        except (TypeError, ValueError):
            return False

    # Function role: Implements input size for structured input schema using this module's input and result contracts.
    # Context: method/helper owned by StructuredIntegerInputSchema; it is reached through that object's workflow.
    # Direct call references (conditional/branch-dependent): parse.
    def input_size(self, text):
        values = self.parse(text)
        if self.size_field:
            selected = values[self.size_field]
            return len(selected) if isinstance(selected, list) else selected
        return sum(
            len(values[field["name"]]) if field["type"] == "int_array" else 1
            for field in self.fields
        )

    # Function role: Produces cases from the supplied schema, random seed, and selected distribution.
    # Context: method/helper owned by StructuredIntegerInputSchema; it is reached through that object's workflow.
    # Direct call references (conditional/branch-dependent): validate.
    def generate(
        self,
        rng: random.Random,
        distribution="uniform",
        *,
        max_array_length: int = 512,
    ):
        if distribution not in {
            "uniform", "boundary_biased", "duplicate_heavy",
            "sorted", "reverse_sorted",
        }:
            raise ValueError("Unsupported distribution.")

        if (
            isinstance(max_array_length, bool)
            or not isinstance(max_array_length, int)
            or max_array_length < 1
        ):
            raise ValueError("max_array_length must be a positive integer.")

        length_fields = {
            field["length_from"] for field in self.fields
            if field["type"] == "int_array"
        }
        schema_cap = max_generated_array_length(self)
        if schema_cap is not None:
            max_array_length = min(max_array_length, schema_cap)
        values = {}
        tokens = []

        for field in self.fields:
            name = field["name"]
            low, high = field["min"], field["max"]
            if field["type"] == "int" and name in length_fields:
                if low > max_array_length:
                    raise ValueError(
                        f"Minimum array length for {name!r} exceeds the local "
                        f"test-generation limit ({max_array_length})."
                    )
                high = min(high, max_array_length)
            count = 1 if field["type"] == "int" else values[field["length_from"]]

            if distribution == "boundary_biased":
                choices = sorted({low, min(low + 1, high), max(high - 1, low), high})
                generated = [rng.choice(choices) for _ in range(count)]
            elif distribution == "duplicate_heavy":
                generated = [rng.randint(low, high)] * count
            else:
                generated = [rng.randint(low, high) for _ in range(count)]
                if distribution in {"sorted", "reverse_sorted"} and field["type"] == "int_array":
                    generated.sort(reverse=(distribution == "reverse_sorted"))

            values[name] = generated[0] if field["type"] == "int" else generated
            tokens.extend(map(str, generated))

        result = " ".join(tokens) + "\n"
        if not self.validate(result):
            raise ValueError("Internal error: generated input failed schema validation.")
        return result
