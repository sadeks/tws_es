import tkinter as tk
from tkinter import ttk, messagebox
import asyncio
import threading
from api import IBConnection
from components import BuySellToggle


class TradingUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Futures Trader")
        self.root.geometry("475x780")
        self.root.resizable(True, True)

        self.ib_conn = IBConnection()
        self.loop = None
        self.ib_thread = None

        self.create_widgets()
        self.update_flatten_button()

        # Trace variables to update max loss display
        self.symbol_var.trace_add("write", self.update_max_loss)
        self.stop_points_var.trace_add("write", self.update_max_loss)
        self.max_contracts_var.trace_add("write", self.update_max_loss)
        self.quantity_var.trace_add("write", self.update_max_loss)
        self.ladder_interval_var.trace_add("write", self.update_max_loss)
        self.update_max_loss()

        # Trace symbol to update execute button and start monitoring
        self.symbol_var.trace_add("write", self.update_execute_button)
        self.symbol_var.trace_add("write", self.on_symbol_changed)

    def create_widgets(self):
        # Status Frame (at very top)
        status_frame = ttk.Frame(self.root, padding=0)
        status_frame.grid(row=0, column=0, padx=0, pady=(10, 0), sticky="ew")

        self.status_label = ttk.Label(status_frame, text="Not Connected", foreground="red")
        self.status_label.pack()

        # Connection Frame
        conn_frame = ttk.LabelFrame(self.root, text="Connection", padding=10)
        conn_frame.grid(row=1, column=0, padx=10, pady=10, sticky="ew")

        self.connect_btn = ttk.Button(conn_frame, text="Connect", command=self.connect)
        self.connect_btn.pack(side="left", padx=5)

        self.refresh_btn = ttk.Button(
            conn_frame, text="Refresh Positions", command=self.refresh_positions, state="disabled"
        )
        self.refresh_btn.pack(side="right", padx=5)

        # Trading Frame
        trade_frame = ttk.LabelFrame(self.root, text="Trade Futures", padding=10)
        trade_frame.grid(row=2, column=0, padx=10, pady=10, sticky="ew")

        # Symbol Selection
        ttk.Label(trade_frame, text="Symbol:").grid(row=0, column=0, sticky="w", pady=5)
        self.symbol_var = tk.StringVar(value="ES")
        self.symbol_combo = ttk.Combobox(
            trade_frame, textvariable=self.symbol_var, values=["ES", "MES", "NQ", "MNQ"], state="readonly", width=10
        )
        self.symbol_combo.grid(row=0, column=1, sticky="w", pady=5)

        # Direction
        ttk.Label(trade_frame, text="Direction:").grid(row=1, column=0, sticky="w", pady=5)
        self.direction_var = tk.StringVar(value="LONG")
        self.direction_toggle = BuySellToggle(
            trade_frame, initial_sell=False, on_change=lambda mode: self.direction_var.set(mode)
        )
        self.direction_toggle.grid(row=1, column=1, sticky="w", pady=5)

        # Quantity
        ttk.Label(trade_frame, text="Quantity:").grid(row=2, column=0, sticky="w", pady=5)
        self.quantity_var = tk.StringVar(value="1")
        self.quantity_entry = ttk.Entry(trade_frame, textvariable=self.quantity_var, width=12)
        self.quantity_entry.grid(row=2, column=1, sticky="w", pady=5)

        # Entry Price (optional)
        ttk.Label(trade_frame, text="Entry Price:").grid(row=3, column=0, sticky="w", pady=5)
        self.entry_price_var = tk.StringVar()
        entry_frame = ttk.Frame(trade_frame)
        entry_frame.grid(row=3, column=1, sticky="w", pady=5)
        self.entry_price_entry = ttk.Entry(entry_frame, textvariable=self.entry_price_var, width=12)
        self.entry_price_entry.pack(side="left")
        ttk.Label(entry_frame, text="(leave empty for market)").pack(side="left", padx=5)

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

        # Ladder Interval
        ttk.Label(trade_frame, text="Ladder Interval (pts):").grid(row=5, column=0, sticky="w", pady=5)
        self.ladder_interval_var = tk.StringVar(value="5")
        ladder_frame = ttk.Frame(trade_frame)
        ladder_frame.grid(row=5, column=1, sticky="w", pady=5)
        self.ladder_interval_entry = ttk.Entry(ladder_frame, textvariable=self.ladder_interval_var, width=12)
        self.ladder_interval_entry.pack(side="left")
        self.full_ladder_label = ttk.Label(ladder_frame, text="Full ladder: N/A", foreground="white")
        self.full_ladder_label.pack(side="left", padx=5)

        # Max Contracts
        ttk.Label(trade_frame, text="Max Contracts:").grid(row=6, column=0, sticky="w", pady=5)
        self.max_contracts_var = tk.StringVar(value="3")
        max_frame = ttk.Frame(trade_frame)
        max_frame.grid(row=6, column=1, sticky="w", pady=5)
        self.max_contracts_entry = ttk.Entry(max_frame, textvariable=self.max_contracts_var, width=12)
        self.max_contracts_entry.pack(side="left")
        self.room_label = ttk.Label(max_frame, text="Room after last: N/A", foreground="white")
        self.room_label.pack(side="left", padx=5)

        # Execute Button
        self.execute_btn = ttk.Button(trade_frame, text="EXECUTE TRADE", command=self.execute_trade, state="disabled")
        self.execute_btn.grid(row=7, column=0, columnspan=2, pady=15)

        # Info Frame
        info_frame = ttk.LabelFrame(self.root, text="Trade Info", padding=10)
        info_frame.grid(row=3, column=0, padx=10, pady=10, sticky="ew")

        self.info_text = tk.Text(info_frame, height=8, width=50, state="disabled")
        self.info_text.pack()

        # PnL label above the Manage Position section
        pnl_frame = ttk.Frame(self.root)
        pnl_frame.grid(row=4, column=0, padx=10, pady=(10, 0), sticky="ew")
        self.pnl_label = tk.Label(pnl_frame, text="", font=("Arial", 12, "bold"))
        self.pnl_label.pack()

        # Close Position Frame
        self.close_frame = ttk.LabelFrame(self.root, text="Manage Position", padding=10)
        self.close_frame.grid(row=5, column=0, padx=10, pady=(0, 10), sticky="ew")

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

        # Start the UI update timer (every 500ms)
        self._start_ui_timer()

        # Start monitoring the selected symbol
        symbol = self.symbol_var.get()
        self._schedule(self.ib_conn.start_monitor(symbol))

    def _start_ui_timer(self):
        """Start the periodic UI update timer"""
        self._update_ui_from_cache()
        self.root.after(500, self._start_ui_timer)

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
            else:  # short
                pnl = (avg_price - current_price) * qty * multiplier

            if pnl >= 0:
                self.pnl_label.config(text=f"PNL +${pnl:,.0f}", fg="green")
            else:
                self.pnl_label.config(text=f"PNL -${abs(pnl):,.0f}", fg="red")
        else:
            self.pnl_label.config(text="")

        # Update button states
        self.update_flatten_button()
        self.update_execute_button()
        self.update_breakeven_button()

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

            info = f"""
Positions:
{pos_text}
            """
            self.update_info(info)

        self.update_flatten_button()
        self.update_execute_button()
        self.update_breakeven_button()

    def execute_trade(self):
        if not self.ib_conn.connected:
            messagebox.showerror("Error", "Not connected to IB")
            return

        try:
            direction = self.direction_var.get()
            quantity = int(self.quantity_var.get())
            entry_price_str = self.entry_price_var.get().strip()
            entry_price = float(entry_price_str) if entry_price_str else None
            stop_points = float(self.stop_points_var.get())
            ladder_interval = float(self.ladder_interval_var.get())
            max_contracts = int(self.max_contracts_var.get())

            if quantity <= 0:
                messagebox.showerror("Error", "Quantity must be greater than 0")
                return

            if stop_points <= 0:
                messagebox.showerror("Error", "Stop loss must be greater than 0")
                return

            if ladder_interval <= 0:
                messagebox.showerror("Error", "Ladder interval must be greater than 0")
                return

            if max_contracts <= 0:
                messagebox.showerror("Error", "Max contracts must be greater than 0")
                return

            # Disable button during execution
            self.execute_btn.config(state="disabled")
            self.update_info("Executing trade...\n")

            # Get selected symbol
            symbol = self.symbol_var.get()

            # Execute trade
            result = self._run_sync(
                self.ib_conn.execute_trade_with_ladder(
                    symbol, direction, entry_price, stop_points, quantity, ladder_interval, max_contracts
                )
            )

            if result["success"]:
                # Display trade execution info
                sym = result["symbol"]
                ladder_info = ""
                if result.get("ladder_orders"):
                    ladder_info = "\n\nLadder Orders Placed:\n" + "\n".join(
                        [f"  - {o['action']} {o['quantity']} {sym} @ {o['price']}" for o in result["ladder_orders"]]
                    )

                info = f"""
Trade Executed Successfully!

Symbol: {sym}
Direction: {result['direction']}
Initial Quantity: {result['quantity']} contracts
Initial Fill: {result['fill_price']:.2f}
Expected Avg (if all fill): {result['expected_avg']:.2f}

Stop Loss Placed:
{'SELL' if direction == 'LONG' else 'BUY'} {result['stop_quantity']} {sym} @ {result['stop_price']} (STOP)
Stop Loss: {result['stop_points']} points
{ladder_info}
                """
                self.update_info(info)

                # Force button update - keep execute disabled since we have a position
                self.root.update_idletasks()
                self.update_flatten_button()
                self.update_execute_button()
                print(f"Active long: {self.ib_conn.active_long}, Active short: {self.ib_conn.active_short}")
            else:
                self.update_info(f"ERROR: {result['message']}\n")
                messagebox.showerror("Error", result["message"])
                # Re-enable button only on failure
                self.execute_btn.config(state="normal")

        except ValueError:
            messagebox.showerror("Error", "Invalid input values")
            self.execute_btn.config(state="normal")
        except Exception as e:
            messagebox.showerror("Error", f"Unexpected error: {str(e)}")
            self.execute_btn.config(state="normal")

    def update_info(self, text):
        self.info_text.config(state="normal")
        self.info_text.delete(1.0, tk.END)
        self.info_text.insert(1.0, text)
        self.info_text.config(state="disabled")

    def update_execute_button(self, *_args):
        """Update execute button state based on connection and existing positions"""
        # Disable if any position exists (must flatten first)
        has_any_position = self.ib_conn.active_long or self.ib_conn.active_short

        # Disable if: not connected or any position exists
        if self.ib_conn.connected and not has_any_position:
            self.execute_btn.config(state="normal")
        else:
            self.execute_btn.config(state="disabled")

    def update_flatten_button(self):
        """Update flatten button state based on active positions"""
        if self.ib_conn.active_long or self.ib_conn.active_short:
            self.flatten_btn.config(state="normal")
        else:
            self.flatten_btn.config(state="disabled")

    def update_breakeven_button(self):
        """Update breakeven button state - only enable if price is favorable"""
        if not (self.ib_conn.active_long or self.ib_conn.active_short):
            self.breakeven_btn.config(state="disabled")
            return

        symbol = self.ib_conn.active_symbol
        if not symbol:
            self.breakeven_btn.config(state="disabled")
            return

        # Use cached current price from monitor
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
        """Calculate and display max loss based on symbol, stop points, and max contracts"""
        multipliers = {"ES": 50.0, "MES": 5.0, "NQ": 20.0, "MNQ": 2.0}
        try:
            symbol = self.symbol_var.get()
            stop_points = float(self.stop_points_var.get())
            max_contracts = int(self.max_contracts_var.get())
            quantity = int(self.quantity_var.get())
            ladder_interval = float(self.ladder_interval_var.get())
            multiplier = multipliers.get(symbol, 50.0)

            # Calculate minimum stop loss needed
            # num_ladders = how many additional entries after initial
            num_ladders = (max_contracts - quantity) // quantity
            # Min stop = distance from expected avg to lowest ladder + buffer
            # Expected avg is at: entry - (ladder_interval * num_ladders) / 2
            # Lowest ladder is at: entry - (ladder_interval * num_ladders)
            # Distance = (ladder_interval * num_ladders) / 2
            min_stop = (ladder_interval * num_ladders) / 2 + 0.25

            max_loss = stop_points * max_contracts * multiplier

            # Show min stop warning OR max loss (not both)
            if stop_points < min_stop:
                self.min_stop_label.config(text=f"Min stop: {min_stop:.2f} pts!")
                self.max_loss_label.config(text="")
            else:
                self.min_stop_label.config(text="")
                self.max_loss_label.config(text=f"Max loss: ${max_loss:,.0f}")

            # Calculate ladder distance info
            ladder_span = ladder_interval * num_ladders
            room_after_last = stop_points - (ladder_span / 2)
            full_ladder = (ladder_span / 2) + stop_points

            self.room_label.config(text=f"Room after last: {room_after_last:.1f} pts")
            self.full_ladder_label.config(text=f"Full ladder: {full_ladder:.1f} pts")
        except (ValueError, AttributeError):
            self.min_stop_label.config(text="")
            self.max_loss_label.config(text="")
            self.room_label.config(text="Room after last: N/A")
            self.full_ladder_label.config(text="Full ladder: N/A")

    def flatten_position(self):
        """Flatten all positions and cancel resting orders"""
        self.flatten_btn.config(state="disabled")
        self.update_info("Flattening position...\n")

        symbol = self.ib_conn.active_symbol or self.symbol_var.get()
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
            self.update_info(info)
        else:
            self.update_info(f"ERROR: {result['message']}\n")
            messagebox.showerror("Error", result["message"])

    def move_stop_to_breakeven(self):
        """Move stop loss to breakeven (average cost)"""
        self.breakeven_btn.config(state="disabled")
        self.update_info("Moving stop to breakeven...\n")

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
            self.update_info(info)
        else:
            self.update_info(f"ERROR: {result['message']}\n")
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
