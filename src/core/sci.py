"""Scientific notation for lab results typed on a plain keyboard.

The vet types `5x10^4`, `5*10^4`, `5e4` or `10^3/uL`; we store and print `5 × 10⁴` and `10³/uL`.
These are ordinary Unicode characters, so they show up the same on screen, on printed reports and in Excel,
and `parse_number` still reads them as numbers for the H / L flags.
"""

import re

# Invisible Unicode marks that keep "5 × 10⁴" left to right inside Persian (right-to-left) text.
# Without them a sentence such as "رشد 5 × 10⁴ CFU/g" shows the number's parts in reverse order.
LRI, PDI = "\u2066", "\u2069"

_SUP = str.maketrans("0123456789+-", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻")
_UNSUP = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻−", "0123456789+--")

_NUM = r"\d+(?:[.,]\d+)?"
# 5x10^4, 5 X 10^-3, 5*10^4, 5×10^4, 5x10⁴
_TIMES_TEN = re.compile(rf"{LRI}?({_NUM})\s*[xX*×]\s*10\s*(?:\^\s*([+-]?\d+)|([⁺⁻]?[⁰¹²³⁴⁵⁶⁷⁸⁹]+)){PDI}?")
# 5e4, 2.5E-3, 1e+06 as a standalone number (not inside a word)
_E_NOTATION = re.compile(rf"(?<![\w.]){_NUM.replace('[.,]', '[.]')}[eE][+-]?\d+(?![\w.])")
# any remaining power: 10^3/uL, m^2
_CARET = re.compile(r"\^\s*([+-]?\d+)")


def superscript(exponent: str | int) -> str:
    text = str(int(str(exponent).translate(_UNSUP)))  # drops a leading "+" and leading zeros
    return text.translate(_SUP)


def _sci(mantissa: str, exponent: str) -> str:
    return f"{LRI}{mantissa} × 10{superscript(exponent)}{PDI}"


def format_scientific(text: str | None) -> str | None:
    """Rewrite keyboard-friendly notation into proper symbols. Other text is left untouched."""
    if text is None:
        return None
    text = str(text)
    text = _TIMES_TEN.sub(lambda m: _sci(m.group(1), m.group(2) or m.group(3)), text)

    def e_note(m: re.Match) -> str:
        mantissa, exponent = re.split(r"[eE]", m.group(0))
        mantissa = mantissa.rstrip("0").rstrip(".") if "." in mantissa else mantissa
        return _sci(mantissa, exponent)

    text = _E_NOTATION.sub(e_note, text)
    text = _CARET.sub(lambda m: superscript(m.group(1)), text)
    return text.replace("+/-", "±").replace("<=", "≤").replace(">=", "≥")


def plain(text: str | None) -> str | None:
    """The text without the invisible direction marks (for comparisons and exports that need raw text)."""
    return None if text is None else str(text).replace(LRI, "").replace(PDI, "")


def parse_number(value) -> float | None:
    """Read a number written as `12.5`, `12,5`, `5 × 10⁴`, `5x10^4` or `5e4`; None if it isn't one."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return None if value != value else float(value)  # NaN -> None
    text = plain(format_scientific(str(value))).strip()
    if not text:
        return None
    m = re.fullmatch(rf"({_NUM})\s*×\s*10([⁺⁻]?[⁰¹²³⁴⁵⁶⁷⁸⁹]+)", text)
    try:
        if m:
            return float(m.group(1).replace(",", ".")) * 10 ** int(m.group(2).translate(_UNSUP))
        return float(text.replace(",", "."))
    except ValueError:
        return None


def format_number(number: float | None) -> str:
    """Short display for a reference limit: 12.5, 5000, or 5 × 10⁴ for large / tiny numbers."""
    if number is None:
        return ""
    if number != 0 and (abs(number) >= 1e5 or abs(number) < 1e-3):
        mantissa, exponent = f"{number:.3e}".split("e")
        mantissa = mantissa.rstrip("0").rstrip(".")
        return _sci(mantissa, exponent)
    return f"{number:g}"
