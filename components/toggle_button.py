import tkinter as tk
from tkinter import ttk


class BuySellToggle(ttk.Frame):
    """
    A compact split toggle: left half = Buy (Long), right half = Sell (Short).
    Calls on_change callback with mode string ("LONG" or "SHORT").
    Uses Canvas-based labels for reliable colors on macOS.
    """

    def __init__(self, parent, initial_sell: bool = False, on_change=None):
        super().__init__(parent)

        self._on_change = on_change
        self._is_sell = initial_sell

        # Colors
        self._active_buy_color = "#27ae60"
        self._active_sell_color = "#c0392b"
        self._inactive_color = "#555555"

        # Create canvas-based buttons for reliable colors on macOS
        self._btn_buy = tk.Canvas(self, width=60, height=28, highlightthickness=0)
        self._btn_sell = tk.Canvas(self, width=60, height=28, highlightthickness=0)

        # Draw rectangles and text
        self._buy_rect = self._btn_buy.create_rectangle(0, 0, 60, 28, fill=self._inactive_color, outline="")
        self._buy_text = self._btn_buy.create_text(30, 14, text="LONG", fill="white", font=("Arial", 10, "bold"))

        self._sell_rect = self._btn_sell.create_rectangle(0, 0, 60, 28, fill=self._inactive_color, outline="")
        self._sell_text = self._btn_sell.create_text(30, 14, text="SHORT", fill="white", font=("Arial", 10, "bold"))

        # Bind clicks
        self._btn_buy.bind("<Button-1>", lambda e: self._on_buy_click())
        self._btn_sell.bind("<Button-1>", lambda e: self._on_sell_click())

        # Cursor on hover
        self._btn_buy.config(cursor="hand2")
        self._btn_sell.config(cursor="hand2")

        # Layout side by side
        self._btn_buy.pack(side="left", padx=(0, 2))
        self._btn_sell.pack(side="left")

        # Set initial state
        self.set_mode(sell=initial_sell)

    def _update_styles(self):
        """Update button colors based on current state."""
        if self._is_sell:
            self._btn_buy.itemconfig(self._buy_rect, fill=self._inactive_color)
            self._btn_sell.itemconfig(self._sell_rect, fill=self._active_sell_color)
        else:
            self._btn_buy.itemconfig(self._buy_rect, fill=self._active_buy_color)
            self._btn_sell.itemconfig(self._sell_rect, fill=self._inactive_color)

    def _on_buy_click(self):
        if self._is_sell:
            self._is_sell = False
            self._update_styles()
            if self._on_change:
                self._on_change("LONG")

    def _on_sell_click(self):
        if not self._is_sell:
            self._is_sell = True
            self._update_styles()
            if self._on_change:
                self._on_change("SHORT")

    def is_sell(self) -> bool:
        return self._is_sell

    def is_buy(self) -> bool:
        return not self._is_sell

    def get_mode(self) -> str:
        return "SHORT" if self._is_sell else "LONG"

    def set_mode(self, sell: bool):
        """Set mode programmatically. sell=True selects Sell/Short, sell=False selects Buy/Long."""
        self._is_sell = sell
        self._update_styles()

    def toggle(self):
        """Flip current mode."""
        self.set_mode(not self._is_sell)
        if self._on_change:
            self._on_change(self.get_mode())
