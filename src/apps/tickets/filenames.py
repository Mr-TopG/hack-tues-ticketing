import re
import unicodedata

MAX_TICKET_FILENAME_STEM_LENGTH = 80
WINDOWS_RESERVED_FILENAMES = {
    "aux",
    "clock$",
    "con",
    "nul",
    "prn",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
}


def safe_ticket_filename_stem(value):
    normalized = unicodedata.normalize("NFKC", value or "")
    normalized = re.sub(r"\s+", "_", normalized)
    normalized = re.sub(r"[^\w-]+", "_", normalized)
    normalized = re.sub(r"_+", "_", normalized)
    normalized = normalized.strip("_-")
    normalized = normalized[:MAX_TICKET_FILENAME_STEM_LENGTH]
    normalized = normalized.rstrip("_-")

    if normalized.casefold() in WINDOWS_RESERVED_FILENAMES:
        normalized = f"ticket_{normalized}"
        normalized = normalized[:MAX_TICKET_FILENAME_STEM_LENGTH]

    return normalized


def ticket_download_filename(ticket):
    stem = safe_ticket_filename_stem(ticket.display_name)

    if not stem:
        stem = f"ticket-{ticket.pk}"

    return f"{stem}.pdf"
