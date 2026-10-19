"""Custom PyRIT converters."""

from pyrit.converter import ConverterResult
from pyrit.converter.converter import Converter

# Cyrillic letters that render like Latin ones. Swapping a few is enough to slip past keyword filters
# while the model still reads the text normally.
HOMOGLYPHS = str.maketrans({"a": "\u0430", "e": "\u0435", "o": "\u043e", "i": "\u0456", "c": "\u0441", "p": "\u0440"})


class HomoglyphConverter(Converter):
    """Deterministic Latin-to-Cyrillic lookalike substitution (a light, readable confusable attack)."""

    SUPPORTED_INPUT_TYPES = ("text",)
    SUPPORTED_OUTPUT_TYPES = ("text",)

    async def convert_async(self, *, prompt: str, input_type: str = "text") -> ConverterResult:
        if not self.input_supported(input_type):
            raise ValueError("Input type not supported")
        return ConverterResult(output_text=prompt.translate(HOMOGLYPHS), output_type="text")
