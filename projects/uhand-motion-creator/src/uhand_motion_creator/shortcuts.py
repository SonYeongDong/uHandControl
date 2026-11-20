"""Desktop shortcut labels used by the card editor."""
import sys

MACOS = sys.platform == "darwin"
MODIFIER = "⌘" if MACOS else "Ctrl"
PREFIX = "⌘" if MACOS else "Ctrl+"
HISTORY_KEYS = "⌘Z/⇧⌘Z" if MACOS else "Ctrl+Z/Y"
