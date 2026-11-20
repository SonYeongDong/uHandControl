"""Saved baseline separate from the editor's unapplied draft and undo history."""
from copy import deepcopy
from pathlib import Path

class DocumentState:
    def __init__(self):
        self.path = None
        self.extensions = {}
        self.saved_cards = ()
        self.saved_extensions = {}

    def dirty(self, cards):
        return tuple(cards) != self.saved_cards or self.extensions != self.saved_extensions

    def mark_saved(self, path, cards):
        self.path = Path(path) if path is not None else None
        self.saved_cards = tuple(cards)
        self.saved_extensions = deepcopy(self.extensions)
