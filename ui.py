import tkinter as tk
from tkinter import ttk, messagebox
import asyncio
import csv
import json
import os
import threading
from datetime import datetime, timedelta
from api import IBConnection


class TradingUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Futures Trader")
        self.root.geometry("430x780")
        self.root.resizable(True, True)

        self.ib_conn = IBConnection()
        self.loop = None
        self.ib_thread = None
        self._flattening = False  # Flag to prevent multiple flatten calls
        self._tp_input_settled = True
        self._tp_debounce_id = None
        self._had_position = False  # tracks position state for broker stop detection
        self._expect_position_gone = False  # set when we triggered the flatten ourselves
        self.COOLDOWN_MINUTES = 5  # cooldown after each closed trade — change this to adjust
        self._cooldown_end = None
        self.DAILY_PNL_WARNING = (
            800  # DO NOT CHANGE THIS => this means 4 scalps in a row are wrong and your read of the market today is off
        )
        self.DAILY_PNL_TARGET = 1200  # show warning when daily PnL exceeds this amount

        self.create_widgets()
        self._apply_preset("Scalp")
        self.update_flatten_button()

        # Trace variables to update max loss display
        self.symbol_var.trace_add("write", self.update_max_loss)
        self.stop_points_var.trace_add("write", self.update_max_loss)
        self.quantity_var.trace_add("write", self.update_max_loss)
        self.ladder_steps_var.trace_add("write", self.update_max_loss)
        self.update_max_loss()

        # Trace symbol to update execute button and start monitoring
        self.symbol_var.trace_add("write", self.update_execute_button)
        self.symbol_var.trace_add("write", self.on_symbol_changed)

        # Debounce target points so typing doesn't trigger TP mid-edit
        self.target_points_var.trace_add("write", self._on_target_points_changed)

    def create_widgets(self):
        # Use pack layout - bottom section first to keep it visible when shrinking

        # Bottom section (Manage Position) - pack first so it stays visible
        bottom_frame = ttk.Frame(self.root)
        bottom_frame.pack(side="bottom", fill="x", padx=10, pady=(0, 10))

        # PnL label
        self.pnl_label = tk.Label(bottom_frame, text="", font=("Arial", 12, "bold"))
        self.pnl_label.pack(pady=(0, 5))

        # Close Position Frame
        self.close_frame = ttk.LabelFrame(bottom_frame, text="Manage Position", padding=10)
        self.close_frame.pack(fill="x")

        # Button container for side-by-side layout
        btn_frame = ttk.Frame(self.close_frame)
        btn_frame.pack(fill="x")

        self.breakeven_btn = ttk.Button(
            btn_frame, text="Move Stop to Breakeven", command=self.move_stop_to_breakeven, state="disabled"
        )
        self.breakeven_btn.pack(side="left")

        self.flatten_btn = ttk.Button(
            btn_frame, text="Flatten Position", command=self.flatten_position, state="disabled"
        )
        self.flatten_btn.pack(side="right")

        # Top section container
        top_frame = ttk.Frame(self.root)
        top_frame.pack(side="top", fill="x")

        # Status Frame (at very top)
        status_frame = ttk.Frame(top_frame, padding=0)
        status_frame.pack(fill="x", padx=0, pady=(10, 0))

        self.status_label = ttk.Label(status_frame, text="Not Connected", foreground="red")
        self.status_label.pack()

        # Connection Frame
        conn_frame = ttk.LabelFrame(top_frame, text="Connection", padding=10)
        conn_frame.pack(fill="x", padx=10, pady=10)

        self.connect_btn = ttk.Button(conn_frame, text="Connect", command=self.connect)
        self.connect_btn.pack(side="left", padx=5)

        self.refresh_btn = ttk.Button(
            conn_frame, text="Refresh Positions", command=self.refresh_positions, state="disabled"
        )
        self.refresh_btn.pack(side="right", padx=5)

        # Trading Frame
        trade_frame = ttk.LabelFrame(top_frame, text="Trade Futures", padding=10)
        trade_frame.pack(fill="x", padx=10, pady=10)

        # Symbol Selection
        ttk.Label(trade_frame, text="Symbol:").grid(row=0, column=0, sticky="w", pady=5)
        self.symbol_var = tk.StringVar(value="ES")
        self.symbol_combo = ttk.Combobox(
            trade_frame, textvariable=self.symbol_var, values=["ES", "MES", "NQ", "MNQ"], state="readonly", width=10
        )
        self.symbol_combo.grid(row=0, column=1, sticky="w", pady=5)

        # Quantity
        ttk.Label(trade_frame, text="Quantity:").grid(row=1, column=0, sticky="w", pady=5)
        self.quantity_var = tk.StringVar(value="1")
        self.quantity_entry = ttk.Entry(trade_frame, textvariable=self.quantity_var, width=12)
        self.quantity_entry.grid(row=1, column=1, sticky="w", pady=5)

        # Entry Price (optional)
        ttk.Label(trade_frame, text="Entry Price:").grid(row=2, column=0, sticky="w", pady=5)
        self.entry_price_var = tk.StringVar()
        entry_frame = ttk.Frame(trade_frame)
        entry_frame.grid(row=2, column=1, sticky="w", pady=5)
        self.entry_price_entry = ttk.Entry(entry_frame, textvariable=self.entry_price_var, width=12)
        self.entry_price_entry.pack(side="left")
        ttk.Label(entry_frame, text="(leave empty for market)").pack(side="left", padx=5)

        # Ladder
        ttk.Label(trade_frame, text="Ladder (pts):").grid(row=3, column=0, sticky="w", pady=5)
        self.ladder_steps_var = tk.StringVar(value="")
        self.ladder_steps_entry = ttk.Entry(trade_frame, textvariable=self.ladder_steps_var, width=12)
        self.ladder_steps_entry.grid(row=3, column=1, sticky="w", pady=5)

        # Stop Loss Points
        ttk.Label(trade_frame, text="Stop Loss (pts):").grid(row=4, column=0, sticky="w", pady=5)
        self.stop_points_var = tk.StringVar(value="10")
        stop_frame = ttk.Frame(trade_frame)
        stop_frame.grid(row=4, column=1, sticky="w", pady=5)
        self.stop_entry = ttk.Entry(stop_frame, textvariable=self.stop_points_var, width=12)
        self.stop_entry.pack(side="left")
        self.min_stop_label = ttk.Label(stop_frame, text="", foreground="orange")
        self.min_stop_label.pack(side="left")
        self.max_loss_label = ttk.Label(stop_frame, text="Max loss: N/A", foreground="red")
        self.max_loss_label.pack(side="left")

        # Ladder info row
        ladder_info_frame = ttk.Frame(trade_frame)
        ladder_info_frame.grid(row=5, column=0, columnspan=2, pady=(0, 5))
        self.ladder_info_label = ttk.Label(ladder_info_frame, text="", foreground="white")
        self.ladder_info_label.pack()

        # Target points with Take Profit checkbox
        ttk.Label(trade_frame, text="Target (pts):").grid(row=6, column=0, sticky="w", pady=5)
        target_frame = ttk.Frame(trade_frame)
        target_frame.grid(row=6, column=1, sticky="w", pady=5)
        self.target_points_var = tk.StringVar(value="30")
        self.target_entry = ttk.Entry(target_frame, textvariable=self.target_points_var, width=5)
        self.target_entry.pack(side="left")
        self.tp_enabled_var = tk.BooleanVar(value=True)
        self.tp_checkbox = ttk.Checkbutton(target_frame, text="Take Profit", variable=self.tp_enabled_var)
        self.tp_checkbox.pack(side="left", padx=(10, 0))

        # Preset buttons (Medium / Heavy)
        preset_btn_frame = ttk.Frame(trade_frame)
        preset_btn_frame.grid(row=7, column=0, columnspan=2, pady=(10, 20))

        self._color_preset_active = "#2980b9"
        self._color_preset_inactive = "#555555"
        self._active_preset = None
        self._preset_buttons = {}
        self._preset_rects = {}
        for name in ("Light", "Medium", "Heavy", "Scalp"):
            canvas = tk.Canvas(preset_btn_frame, width=70, height=26, highlightthickness=0)
            rect = canvas.create_rectangle(0, 0, 70, 26, fill=self._color_preset_inactive, outline="")
            canvas.create_text(35, 13, text=name, fill="white", font=("Arial", 10))
            canvas.bind("<Button-1>", lambda e, n=name: self._apply_preset(n))
            canvas.pack(side="left", padx=4)
            self._preset_buttons[name] = canvas
            self._preset_rects[name] = rect

        # LONG / SHORT buttons
        exec_btn_frame = ttk.Frame(trade_frame)
        exec_btn_frame.grid(row=8, column=0, columnspan=2, pady=(8, 15))

        self._execute_enabled = False
        self._color_long = "#27ae60"
        self._color_short = "#c0392b"
        self._color_dim = "#555555"

        self.long_btn = tk.Canvas(exec_btn_frame, width=90, height=32, highlightthickness=0)
        self._long_rect = self.long_btn.create_rectangle(0, 0, 90, 32, fill=self._color_dim, outline="")
        self.long_btn.create_text(45, 16, text="LONG", fill="white", font=("Arial", 11, "bold"))
        self.long_btn.bind("<Button-1>", lambda e: self._on_execute_click("LONG"))
        self.long_btn.pack(side="left", padx=(0, 8))

        self.short_btn = tk.Canvas(exec_btn_frame, width=90, height=32, highlightthickness=0)
        self._short_rect = self.short_btn.create_rectangle(0, 0, 90, 32, fill=self._color_dim, outline="")
        self.short_btn.create_text(45, 16, text="SHORT", fill="white", font=("Arial", 11, "bold"))
        self.short_btn.bind("<Button-1>", lambda e: self._on_execute_click("SHORT"))
        self.short_btn.pack(side="left")

        # Daily PnL warning label (hidden until threshold is hit)
        self.pnl_warning_label = tk.Label(self.root, text="", font=("Arial", 10, "bold"))
        self.pnl_warning_label.pack(side="top", pady=(0, 2))

        # Tabbed Info Section (fills remaining space in middle)
        self.info_notebook = ttk.Notebook(self.root)
        self.info_notebook.pack(side="top", fill="both", expand=True, padx=10, pady=10)

        # Execution Log Tab
        exec_frame = ttk.Frame(self.info_notebook, padding=2)
        self.info_notebook.add(exec_frame, text="Execution Log")
        self.exec_text = tk.Text(exec_frame, height=8, state="disabled")
        self.exec_text.pack(fill="both", expand=True)

        # Position Tab
        pos_frame = ttk.Frame(self.info_notebook, padding=2)
        self.info_notebook.add(pos_frame, text="Position")
        self.pos_text = tk.Text(pos_frame, height=8, state="disabled")
        self.pos_text.pack(fill="both", expand=True)

    _PRESETS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "presets.json")

    def _load_presets(self):
        with open(self._PRESETS_FILE) as f:
            return json.load(f)

    def _apply_preset(self, name):
        try:
            presets = self._load_presets()
        except Exception as e:
            messagebox.showerror("Error", f"Could not load presets.json: {e}")
            return
        if name not in presets:
            messagebox.showerror("Error", f"Preset '{name}' not found in presets.json")
            return
        p = presets[name]
        if "symbol" in p:
            self.symbol_var.set(p["symbol"])
        if "quantity" in p:
            self.quantity_var.set(str(p["quantity"]))
        if "ladder" in p:
            self.ladder_steps_var.set(str(p["ladder"]))
        if "stop_loss" in p:
            self.stop_points_var.set(str(p["stop_loss"]))
        # Update button highlights
        self._active_preset = name
        for n, canvas in self._preset_buttons.items():
            color = self._color_preset_active if n == name else self._color_preset_inactive
            canvas.itemconfig(self._preset_rects[n], fill=color)

    def _run_event_loop(self):
        """Run the asyncio event loop in a background thread"""
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def _schedule(self, coro):
        """Schedule a coroutine to run in the background thread"""
        if not self.loop:
            return None
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    def _run_sync(self, coro):
        """Run a coroutine synchronously (blocking) - use sparingly"""
        if not self.loop:
            return None
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return future.result(timeout=30)

    def connect(self):
        host = "127.0.0.1"

        # Create and start the event loop in a background thread
        self.loop = asyncio.new_event_loop()
        self.ib_conn.loop = self.loop
        self.ib_thread = threading.Thread(target=self._run_event_loop, daemon=True)
        self.ib_thread.start()

        # Try live account first (port 7496)
        print("Attempting to connect to Live Account (port 7496)...")
        success = self._run_sync(self.ib_conn.connect(host, 7496))

        if success:
            account_type = "Live Account Connected"
            connected_port = 7496
        else:
            # Try demo account (port 7497)
            print("Live account failed. Attempting Demo Account (port 7497)...")
            success = self._run_sync(self.ib_conn.connect(host, 7497))

            if success:
                account_type = "Demo Account Connected"
                connected_port = 7497
            else:
                messagebox.showerror("Connection Error", "Failed to connect to IB on both ports 7496 and 7497")
                return

        print(f"Successfully connected on port {connected_port}")
        self.status_label.config(text=account_type, foreground="green")
        self.connect_btn.config(state="disabled")
        self.refresh_btn.config(state="normal")

        # Refresh positions
        self.refresh_positions()

        # Display open orders
        self._display_open_orders()

        # Check daily PnL warning once on connect
        self._update_daily_pnl_warning()

        # Start the UI update timer (every 500ms)
        self._start_ui_timer()

        # Start monitoring the selected symbol
        symbol = self.symbol_var.get()
        self._schedule(self.ib_conn.start_monitor(symbol))

    def _on_target_points_changed(self, *_args):
        self._tp_input_settled = False
        if self._tp_debounce_id:
            self.root.after_cancel(self._tp_debounce_id)
        self._tp_debounce_id = self.root.after(1000, self._on_target_points_settled)

    def _on_target_points_settled(self):
        self._tp_input_settled = True
        self._tp_debounce_id = None
        print(f"TP input settled: target = {self.target_points_var.get()}")

    def _update_daily_pnl_warning(self):

        daily_pnl = self.ib_conn.get_daily_pnl()
        if daily_pnl is not None:
            if daily_pnl >= self.DAILY_PNL_TARGET:
                self.pnl_warning_label.config(text="Daily Goal Reached\n Close Laptop and go walk!", fg="green")
            elif daily_pnl <= -self.DAILY_PNL_WARNING:
                self.pnl_warning_label.config(text="Daily Loss Limit Hit\n Close Laptop and go walk!!!", fg="red")
        else:
            self.pnl_warning_label.config(text="")

    def _start_ui_timer(self):
        """Start the periodic UI update timer"""
        self._update_ui_from_cache()
        self.root.after(500, self._start_ui_timer)

    async def _auto_flatten(self, symbol):
        """Auto-flatten position when take profit is hit"""
        try:
            journal_data = self._capture_journal_data(0.0)  # capture before reset
            self._expect_position_gone = True
            result = await self.ib_conn.flatten_position(symbol)
            if result["success"]:
                closed_list = "\n".join(result.get("closed_contracts", []))
                info = f"""
Take Profit Hit! Position Flattened!

Closed Contracts:
{closed_list}

Average Fill: {result['close_price']:.2f}
Orders Cancelled: {result['cancelled_orders']}
"""
                self.root.after(0, lambda: self.update_exec_log(info))
                self._start_cooldown()
                self.root.after(0, self._update_daily_pnl_warning)
                if journal_data:
                    journal_data["close_price"] = result["close_price"]
                    self._compute_journal_pnl(journal_data)
                    self.root.after(0, lambda d=journal_data: self._show_journal_popup(d, "Take Profit"))
            else:
                self._expect_position_gone = False
                self.root.after(0, lambda: self.update_exec_log(f"ERROR: {result['message']}\n"))
        finally:
            self._flattening = False

    def _update_ui_from_cache(self):
        """Update UI elements from cached values (called by timer)"""
        if not self.ib_conn.connected:
            return

        # Update PnL label
        if (
            (self.ib_conn.active_long or self.ib_conn.active_short)
            and self.ib_conn.avg_entry_price > 0
            and self.ib_conn.current_price is not None
        ):
            symbol = self.ib_conn.active_symbol
            current_price = self.ib_conn.current_price
            avg_price = self.ib_conn.avg_entry_price
            qty = self.ib_conn.current_quantity
            multiplier = self.ib_conn.MULTIPLIERS.get(symbol, 50.0)

            if self.ib_conn.active_long:
                pnl = (current_price - avg_price) * qty * multiplier
                points = round((current_price - avg_price) * 4) / 4
            else:  # short
                pnl = (avg_price - current_price) * qty * multiplier
                points = round((avg_price - current_price) * 4) / 4

            if points >= 0:
                self.pnl_label.config(text=f"{points:.2f} pts  |  ${abs(pnl):,.0f}", fg="green")
            else:
                self.pnl_label.config(text=f"{points:.2f} pts  |  ${abs(pnl):,.0f}", fg="red")

            # Get target points value
            try:
                target_points = float(self.target_points_var.get())
            except ValueError:
                target_points = 0

            # Check if take profit is hit (skip while user is editing the field)
            if target_points > 0 and self.tp_enabled_var.get() and not self._flattening and self._tp_input_settled:
                if points >= target_points:
                    self._flattening = True
                    print("Take profit hit! Flattening position...")
                    self.update_exec_log("Take profit hit! Flattening position...\n")
                    self._schedule(self._auto_flatten(symbol))
        else:
            if self._cooldown_end and datetime.now() < self._cooldown_end:
                remaining = int((self._cooldown_end - datetime.now()).total_seconds())
                self.pnl_label.config(text=f"Cooldown: {remaining // 60}:{remaining % 60:02d}", fg="orange")
            else:
                self._cooldown_end = None
                self.pnl_label.config(text="")

        # Detect broker stop: position disappeared without us triggering a flatten
        currently_has_position = self.ib_conn.active_long or self.ib_conn.active_short
        if self._had_position and not currently_has_position:
            if self._expect_position_gone:
                self._expect_position_gone = False
            else:
                # Broker stop fired — capture data with current price as approx exit
                data = self._capture_journal_data(self.ib_conn.current_price or 0.0)
                self._compute_journal_pnl(data)
                self._start_cooldown()
                self._update_daily_pnl_warning()
                self.root.after(100, lambda d=data: self._show_journal_popup(d, "Stop Loss"))
        self._had_position = currently_has_position

        # Update button states
        self.update_flatten_button()
        self.update_execute_button()
        self.update_breakeven_button()

    def _format_trade_info(
        self,
        symbol,
        direction,
        entry_qty,
        entry_price,
        expected_avg,
        stop_qty,
        stop_price,
        stop_points,
        max_loss,
        ladder_orders,
        title="Orders Placed!",
    ):
        """Format trade info for display in Execution Log"""
        stop_action = "SELL" if direction == "LONG" else "BUY"

        ladder_info = ""
        if ladder_orders:
            ladder_info = "\n\nLadder Orders:\n" + "\n".join(
                [f"  - {o['action']} {o['quantity']} {symbol} @ {o['price']:.2f}" for o in ladder_orders]
            )

        return f"""{title}

Symbol: {symbol}
Direction: {direction}
Initial Quantity: {entry_qty} contracts
Entry Price: {entry_price:.2f}
Expected Avg (if all fill): {expected_avg:.2f}

Stop Loss:
{stop_action} {stop_qty} {symbol} @ {stop_price:.2f} (STOP)
Stop Loss: {stop_points:.2f} points
Max Loss: ${max_loss:,.0f}
{ladder_info}

Position will update when orders fill."""

    def _display_open_orders(self):
        """Display open/resting orders in the Execution Log"""
        orders = self._run_sync(self.ib_conn.get_open_orders())
        if not orders:
            self.update_exec_log("No open orders")
            return

        # Group orders by symbol
        by_symbol = {}
        for o in orders:
            sym = o["symbol"]
            if sym not in by_symbol:
                by_symbol[sym] = {"stops": [], "limits": []}
            if o["order_type"] == "STP":
                by_symbol[sym]["stops"].append(o)
            elif o["order_type"] == "LMT":
                by_symbol[sym]["limits"].append(o)

        all_info = []
        multipliers = {"ES": 50.0, "MES": 5.0, "NQ": 20.0, "MNQ": 2.0}

        for sym, sym_orders in by_symbol.items():
            stops = sym_orders["stops"]
            limits = sym_orders["limits"]

            # Determine direction from stop order (SELL stop = LONG, BUY stop = SHORT)
            direction = "LONG" if stops and stops[0]["action"] == "SELL" else "SHORT"

            # Sort limits by price to find entry vs ladder
            if limits:
                limits.sort(key=lambda x: x["price"], reverse=(direction == "LONG"))
                entry_order = limits[0]
                ladder_orders = limits[1:]

                # Include already-filled position in weighted average
                filled_qty = self.ib_conn.current_quantity if self.ib_conn.active_symbol == sym else 0
                filled_avg = self.ib_conn.avg_entry_price if filled_qty > 0 else 0.0

                resting_cost = sum(o["price"] * o["quantity"] for o in limits)
                resting_qty = sum(o["quantity"] for o in limits)
                total_cost = (filled_avg * filled_qty) + resting_cost
                total_qty = filled_qty + resting_qty
                expected_avg = total_cost / total_qty if total_qty > 0 else entry_order["price"]
            else:
                entry_order = {"price": 0, "quantity": 0}
                ladder_orders = []
                expected_avg = 0

            # Calculate stop info
            if stops:
                stop = stops[0]
                stop_price = stop["price"]
                stop_qty = stop["quantity"]
                multiplier = multipliers.get(sym, 50.0)
                if direction == "LONG":
                    stop_points = expected_avg - stop_price
                else:
                    stop_points = stop_price - expected_avg
                max_loss = stop_points * stop_qty * multiplier
            else:
                stop_price = 0
                stop_qty = 0
                stop_points = 0
                max_loss = 0

            info = self._format_trade_info(
                symbol=sym,
                direction=direction,
                entry_qty=entry_order["quantity"],
                entry_price=entry_order["price"],
                expected_avg=expected_avg,
                stop_qty=stop_qty,
                stop_price=stop_price,
                stop_points=stop_points,
                max_loss=max_loss,
                ladder_orders=ladder_orders,
                title=f"Resting Orders for {sym}",
            )
            all_info.append(info)

        self.update_exec_log("\n\n".join(all_info))

    def on_symbol_changed(self, *_args):
        """Called when symbol dropdown changes - start monitoring new symbol"""
        if self.ib_conn.connected:
            symbol = self.symbol_var.get()
            self._schedule(self.ib_conn.start_monitor(symbol))

    def refresh_positions(self):
        """Manually refresh positions from IBKR"""
        if not self.ib_conn.connected:
            messagebox.showerror("Error", "Not connected to IB")
            return

        print("\n*** Manual Refresh Triggered ***\n")

        # Show position sync info
        sync_result = self._run_sync(self.ib_conn.sync_positions())
        if sync_result:
            positions_info = []
            for sym, pos in sync_result["positions"].items():
                if pos != 0:
                    avg = self._run_sync(self.ib_conn.get_avg_entry_price(sym, force_refresh=True))
                    positions_info.append(f"{sym}: {pos} @ {avg:.2f}" if avg > 0 else f"{sym}: {pos}")

            pos_text = "\n".join(positions_info) if positions_info else "No open positions"

            info = f"""Positions:
{pos_text}"""
            self.update_position_info(info)

        self.update_flatten_button()
        self.update_execute_button()
        self.update_breakeven_button()
        self._display_open_orders()

    def _parse_ladder_steps(self, ladder_str):
        """Parse comma-separated ladder steps into a list of floats"""
        steps = []
        for s in ladder_str.split(","):
            s = s.strip()
            if s:
                steps.append(float(s))
        return steps

    def execute_trade(self, direction):
        if not self.ib_conn.connected:
            messagebox.showerror("Error", "Not connected to IB")
            return

        try:
            quantity = int(self.quantity_var.get())
            entry_price_str = self.entry_price_var.get().strip()
            entry_price = float(entry_price_str) if entry_price_str else None
            stop_points = float(self.stop_points_var.get())
            ladder_steps = self._parse_ladder_steps(self.ladder_steps_var.get())

            if quantity <= 0:
                messagebox.showerror("Error", "Quantity must be greater than 0")
                return

            if stop_points <= 0:
                messagebox.showerror("Error", "Stop loss must be greater than 0")
                return

            # if not ladder_steps:
            #     messagebox.showerror("Error", "At least one ladder step is required")
            #     return

            # Disable buttons during execution
            self._execute_enabled = False
            self.long_btn.itemconfig(self._long_rect, fill=self._color_dim)
            self.long_btn.config(cursor="")
            self.short_btn.itemconfig(self._short_rect, fill=self._color_dim)
            self.short_btn.config(cursor="")
            self.update_exec_log("Executing trade...\n")

            # Get selected symbol
            symbol = self.symbol_var.get()

            # Execute trade
            result = self._run_sync(
                self.ib_conn.execute_trade_with_ladder(
                    symbol, direction, entry_price, stop_points, quantity, ladder_steps
                )
            )

            if result["success"]:
                # Calculate max loss
                sym = result["symbol"]
                multiplier = {"ES": 50.0, "MES": 5.0, "NQ": 20.0, "MNQ": 2.0}.get(sym, 50.0)
                max_loss = result["stop_points"] * result["stop_quantity"] * multiplier

                info = self._format_trade_info(
                    symbol=sym,
                    direction=result["direction"],
                    entry_qty=result["quantity"],
                    entry_price=result["fill_price"],
                    expected_avg=result["expected_avg"],
                    stop_qty=result["stop_quantity"],
                    stop_price=result["stop_price"],
                    stop_points=result["stop_points"],
                    max_loss=max_loss,
                    ladder_orders=result.get("ladder_orders", []),
                    title="Orders Placed!",
                )
                self.update_exec_log(info)

                # Force button update - keep execute disabled since we have a position
                self.root.update_idletasks()
                self.update_flatten_button()
                self.update_execute_button()
                print(f"Active long: {self.ib_conn.active_long}, Active short: {self.ib_conn.active_short}")
            else:
                self.update_exec_log(f"ERROR: {result['message']}\n")
                messagebox.showerror("Error", result["message"])
                self.update_execute_button()

        except ValueError:
            messagebox.showerror("Error", "Invalid input values")
            self.update_execute_button()
        except Exception as e:
            messagebox.showerror("Error", f"Unexpected error: {str(e)}")
            self.update_execute_button()

    def update_exec_log(self, text):
        """Update the Execution Log tab"""
        self.exec_text.config(state="normal")
        self.exec_text.delete(1.0, tk.END)
        self.exec_text.insert(1.0, text)
        self.exec_text.config(state="disabled")
        self.info_notebook.select(0)  # Switch to Execution Log tab

    def update_position_info(self, text):
        """Update the Position tab"""
        self.pos_text.config(state="normal")
        self.pos_text.delete(1.0, tk.END)
        self.pos_text.insert(1.0, text)
        self.pos_text.config(state="disabled")
        self.info_notebook.select(1)  # Switch to Position tab

    def _on_execute_click(self, direction):
        if self._execute_enabled:
            self.execute_trade(direction)

    def _pnl_warning_active(self):
        return bool(self.pnl_warning_label.cget("text"))

    def update_execute_button(self, *_args):
        """Update LONG/SHORT button colors based on connection and existing positions."""
        if self._pnl_warning_active():
            self._execute_enabled = False
            self.long_btn.itemconfig(self._long_rect, fill=self._color_dim)
            self.long_btn.config(cursor="")
            self.short_btn.itemconfig(self._short_rect, fill=self._color_dim)
            self.short_btn.config(cursor="")
            return
        selected = self.symbol_var.get()
        has_position_in_selected = (
            self.ib_conn.active_long or self.ib_conn.active_short
        ) and self.ib_conn.active_symbol == selected
        in_cooldown = self._cooldown_end is not None and datetime.now() < self._cooldown_end
        self._execute_enabled = self.ib_conn.connected and not has_position_in_selected and not in_cooldown
        if self._execute_enabled:
            self.long_btn.itemconfig(self._long_rect, fill=self._color_long)
            self.long_btn.config(cursor="hand2")
            self.short_btn.itemconfig(self._short_rect, fill=self._color_short)
            self.short_btn.config(cursor="hand2")
        elif self.ib_conn.connected and self.ib_conn.active_long:
            self.long_btn.itemconfig(self._long_rect, fill=self._color_long)
            self.long_btn.config(cursor="")
            self.short_btn.itemconfig(self._short_rect, fill=self._color_dim)
            self.short_btn.config(cursor="")
        elif self.ib_conn.connected and self.ib_conn.active_short:
            self.long_btn.itemconfig(self._long_rect, fill=self._color_dim)
            self.long_btn.config(cursor="")
            self.short_btn.itemconfig(self._short_rect, fill=self._color_short)
            self.short_btn.config(cursor="")
        else:
            self.long_btn.itemconfig(self._long_rect, fill=self._color_dim)
            self.long_btn.config(cursor="")
            self.short_btn.itemconfig(self._short_rect, fill=self._color_dim)
            self.short_btn.config(cursor="")

    def update_flatten_button(self):
        """Update flatten button state based on active positions"""
        if self.ib_conn.active_long or self.ib_conn.active_short:
            self.flatten_btn.config(state="normal")
        else:
            self.flatten_btn.config(state="disabled")

    def update_breakeven_button(self):
        """Update breakeven button state - only enable if price is favorable"""
        if self._pnl_warning_active():
            self.breakeven_btn.config(state="disabled")
            return
        if not (self.ib_conn.active_long or self.ib_conn.active_short):
            self.breakeven_btn.config(state="disabled")
            return

        symbol = self.ib_conn.active_symbol
        if not symbol:
            self.breakeven_btn.config(state="disabled")
            return

        current_price = self.ib_conn.current_price
        avg_price = self.ib_conn.avg_entry_price

        if not current_price or avg_price <= 0:
            self.breakeven_btn.config(state="disabled")
            return

        # Enable only if price is favorable for breakeven
        if self.ib_conn.active_long and current_price > avg_price:
            self.breakeven_btn.config(state="normal")
        elif self.ib_conn.active_short and current_price < avg_price:
            self.breakeven_btn.config(state="normal")
        else:
            self.breakeven_btn.config(state="disabled")

    def update_max_loss(self, *_args):
        """Calculate and display max loss based on symbol, stop points, and ladder steps"""
        multipliers = {"ES": 50.0, "MES": 5.0, "NQ": 20.0, "MNQ": 2.0}
        try:
            symbol = self.symbol_var.get()
            stop_points = float(self.stop_points_var.get())
            quantity = int(self.quantity_var.get())
            ladder_steps = self._parse_ladder_steps(self.ladder_steps_var.get())
            multiplier = multipliers.get(symbol, 50.0)

            # Calculate max contracts: (number of ladder steps + 1 for initial) × quantity
            num_positions = len(ladder_steps) + 1
            max_contracts = num_positions * quantity

            # Calculate cumulative distances for each ladder level
            cumulative_distances = []
            cumsum = 0
            for step in ladder_steps:
                cumsum += step
                cumulative_distances.append(cumsum)

            # Full ladder = total distance from entry to last ladder
            full_ladder = cumsum

            # Average distance from entry (entry is at 0, then each ladder at cumulative distance)
            avg_distance = sum(cumulative_distances) / num_positions if num_positions > 0 else 0

            # Calculate minimum stop loss needed (must be greater than distance from avg to last ladder)
            min_stop = (full_ladder - avg_distance) + 0.25

            max_loss = stop_points * max_contracts * multiplier

            # Show min stop warning OR max loss (not both)
            if stop_points < min_stop:
                self.min_stop_label.config(text=f"Min stop: {min_stop:.2f} pts!")
                self.max_loss_label.config(text="")
            else:
                self.min_stop_label.config(text="")
                self.max_loss_label.config(text=f"Max loss: ${max_loss:,.0f}")

            # Room after last = distance from last ladder to stop
            # Stop is placed at: expected_avg ± stop_points
            # Expected avg is at: entry ± avg_distance
            # Last ladder is at: entry ± full_ladder
            # Room = stop_points - (full_ladder - avg_distance)
            room_after_last = stop_points - (full_ladder - avg_distance)
            room_after_last = round(room_after_last * 4) / 4  # Round to 0.25 increments

            # Total ladder span = distance from entry to stop
            total_ladder = avg_distance + stop_points

            # Update ladder info label with all relevant info
            self.ladder_info_label.config(
                text=f"Ladder: {total_ladder:.2f} pts | Max Cons: {max_contracts} | Stoploss Room: {room_after_last:.2f} pts"
            )
        except (ValueError, AttributeError):
            self.min_stop_label.config(text="")
            self.max_loss_label.config(text="")
            self.ladder_info_label.config(text="")

    def _start_cooldown(self):
        self._cooldown_end = datetime.now() + timedelta(minutes=self.COOLDOWN_MINUTES)

    # ── Journal ──────────────────────────────────────────────────────────────

    _JOURNAL_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trade_journal.csv")
    _JOURNAL_HEADERS = [
        "Date",
        "Symbol",
        "Direction",
        "Entry Price",
        "Exit Price",
        "Rungs Used",
        "Hold Time",
        "P&L ($)",
        "Exit Reason",
        "Good Chart Level",
        "Pitnoise Confirmation",
    ]

    def _capture_journal_data(self, close_price):
        """Snapshot current position data before it gets reset."""
        conn = self.ib_conn
        symbol = conn.active_symbol or self.symbol_var.get()
        direction = "LONG" if conn.active_long else "SHORT"
        entry_price = conn.avg_entry_price
        quantity = conn.current_quantity
        multiplier = conn.MULTIPLIERS.get(symbol, 50.0)
        initial_qty = conn.initial_quantity or 1
        rungs = max(1, round(quantity / initial_qty)) if quantity > 0 else 1

        hold_time = ""
        if conn.entry_time:
            delta = datetime.now() - conn.entry_time
            secs = int(delta.total_seconds())
            hold_time = f"{secs // 60}m {secs % 60}s"

        return {
            "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "symbol": symbol,
            "direction": direction,
            "entry_price": entry_price,
            "close_price": close_price,
            "rungs": rungs,
            "hold_time": hold_time,
            "pnl": 0.0,
            "multiplier": multiplier,
            "quantity": quantity,
        }

    def _compute_journal_pnl(self, data):
        """Recalculate P&L once close_price is known."""
        ep = data["entry_price"]
        cp = data["close_price"]
        qty = data["quantity"]
        mul = data["multiplier"]
        if ep and cp:
            data["pnl"] = ((cp - ep) if data["direction"] == "LONG" else (ep - cp)) * qty * mul

    def _save_journal(self, data, reason, good_chart, pitnoise):
        """Append one row to the CSV journal."""
        file_exists = os.path.exists(self._JOURNAL_FILE)
        with open(self._JOURNAL_FILE, "a", newline="") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(self._JOURNAL_HEADERS)
            writer.writerow(
                [
                    data["date"],
                    data["symbol"],
                    data["direction"],
                    f"{data['entry_price']:.2f}",
                    f"{data['close_price']:.2f}",
                    data["rungs"],
                    data["hold_time"],
                    f"{data['pnl']:.2f}",
                    reason,
                    "Yes" if good_chart else "No",
                    "Yes" if pitnoise else "No",
                ]
            )
        print(f"Journal saved to {self._JOURNAL_FILE}")

    def _show_journal_popup(self, data, reason):
        """Show the post-trade journal popup."""
        popup = tk.Toplevel(self.root)
        popup.title("Trade Review")
        popup.geometry("320x240")
        popup.resizable(False, False)
        popup.grab_set()  # modal

        pad = {"padx": 16, "pady": 6}

        tk.Label(
            popup,
            text=f"Exit: {reason}  |  {data['symbol']} {data['direction']}  |  P&L: ${data['pnl']:+.0f}",
            font=("Arial", 10),
            fg="#888888",
        ).pack(anchor="w", **pad)

        ttk.Separator(popup, orient="horizontal").pack(fill="x", padx=16, pady=4)

        def yes_no_row(parent, question):
            tk.Label(parent, text=question, font=("Arial", 11, "bold")).pack(anchor="w", padx=16, pady=(6, 2))
            var = tk.BooleanVar(value=True)
            row = tk.Frame(parent)
            row.pack(anchor="w", padx=16)
            tk.Radiobutton(row, text="Yes", variable=var, value=True).pack(side="left")
            tk.Radiobutton(row, text="No", variable=var, value=False).pack(side="left", padx=(12, 0))
            return var

        good_chart_var = yes_no_row(popup, "Good chart level?")
        pitnoise_var = yes_no_row(popup, "Pitnoise confirmation?")

        def on_save():
            self._save_journal(data, reason, good_chart_var.get(), pitnoise_var.get())
            popup.destroy()

        ttk.Button(popup, text="Save", command=on_save).pack(pady=12)

    # ── Flatten ───────────────────────────────────────────────────────────────

    def flatten_position(self):
        """Flatten all positions and cancel resting orders"""
        self.flatten_btn.config(state="disabled")
        self.update_exec_log("Flattening position...\n")

        symbol = self.ib_conn.active_symbol or self.symbol_var.get()
        journal_data = self._capture_journal_data(0.0)  # capture before reset
        self._expect_position_gone = True
        result = self._run_sync(self.ib_conn.flatten_position(symbol))

        if result["success"]:
            closed_list = "\n".join(result.get("closed_contracts", []))
            info = f"""
Position Flattened!

Closed Contracts:
{closed_list}

Average Fill: {result['close_price']:.2f}
Orders Cancelled: {result['cancelled_orders']}

All positions closed and orders cancelled.
            """
            self.update_exec_log(info)
            self._start_cooldown()
            self._update_daily_pnl_warning()
            if journal_data:
                journal_data["close_price"] = result["close_price"]
                self._compute_journal_pnl(journal_data)
                self._show_journal_popup(journal_data, "Manual")
        else:
            self._expect_position_gone = False
            self.update_exec_log(f"ERROR: {result['message']}\n")
            messagebox.showerror("Error", result["message"])

    def move_stop_to_breakeven(self):
        """Move stop loss to breakeven (average cost)"""
        self.breakeven_btn.config(state="disabled")
        self.update_exec_log("Moving stop to breakeven...\n")

        symbol = self.ib_conn.active_symbol
        if not symbol:
            messagebox.showerror("Error", "No active position")
            return

        result = self._run_sync(self.ib_conn.move_stop_to_breakeven(symbol))

        if result["success"]:
            info = f"""
Stop Moved to Breakeven!

Symbol: {result['symbol']}
New Stop Price: {result['stop_price']:.2f}
Stop Quantity: {result['stop_quantity']}
Orders Cancelled: {result['cancelled_orders']}
            """
            self.update_exec_log(info)
        else:
            self.update_exec_log(f"ERROR: {result['message']}\n")
            messagebox.showerror("Error", result["message"])

    def on_closing(self):
        if self.ib_conn.connected:
            self.ib_conn.disconnect()
        if self.loop:
            self.loop.call_soon_threadsafe(self.loop.stop)
        self.root.destroy()


def main():
    root = tk.Tk()
    app = TradingUI(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()


if __name__ == "__main__":
    main()
