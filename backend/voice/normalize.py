"""Turn spoken claim numbers into claim ids."""

import re

CLAIM_DIGITS = 4

DIGITS = {
    "zero": "0",
    "oh": "0",
    "o": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
}
TEENS = {
    "ten": "10",
    "eleven": "11",
    "twelve": "12",
    "thirteen": "13",
    "fourteen": "14",
    "fifteen": "15",
    "sixteen": "16",
    "seventeen": "17",
    "eighteen": "18",
    "nineteen": "19",
}
TENS = {
    "twenty": "2",
    "thirty": "3",
    "forty": "4",
    "fifty": "5",
    "sixty": "6",
    "seventy": "7",
    "eighty": "8",
    "ninety": "9",
}


def spoken_digits(words: list[str]) -> list[str]:
    """Return each run of number words as a string of digits."""
    runs, current = [], ""
    index = 0
    while index < len(words):
        word = words[index]
        following = words[index + 1] if index + 1 < len(words) else ""
        if word in DIGITS:
            current += DIGITS[word]
        elif word in TEENS:
            current += TEENS[word]
        elif word in TENS:
            current += TENS[word] + DIGITS.get(following, "0")
            index += following in DIGITS
        elif word.isdigit():
            current += word
        elif current:
            runs.append(current)
            current = ""
        index += 1
    return [*runs, current] if current else runs


def claim_id(text: str) -> str:
    """Return the claim id in a spoken or typed request, or an empty string."""
    lowered = text.lower()
    if match := re.search(r"\b(?:clm[- ]?)?(\d{4})\b", lowered):
        return f"CLM-{match.group(1)}"
    words = re.findall(r"[a-z]+|\d+", lowered.replace("-", " "))
    for digits in spoken_digits([w for w in words if w not in ("c", "l", "m")]):
        if len(digits) == CLAIM_DIGITS:
            return f"CLM-{digits}"
    return ""
