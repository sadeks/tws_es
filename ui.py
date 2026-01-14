import tkinter as tk
from tkinter import ttk, messagebox
import asyncio
from api import IBConnection


class TradingUI:
    def __init__(self, root):
        self.root = root
        self.root.title("ES/MES Futures Trader")
        self.root.geometry("485x680")

        self.ib_conn = IBConnection()
        self.loop = asyncio.new_event_loop()

        self.create_widgets()
        self.update_close_buttons()

    def create_widgets(self):
        # Connection Frame
        conn_frame = ttk.LabelFrame(self.root, text="Connection", padding=10)
        conn_frame.grid(row=0, column=0, padx=10, pady=10, sticky="ew")

        self.connect_btn = ttk.Button(conn_frame, text="Connect", command=self.connect)
        self.connect_btn.pack(side="left", padx=5)

        self.refresh_btn = ttk.Button(
            conn_frame, text="Refresh Positions", command=self.refresh_positions, state="disabled"
        )
        self.refresh_btn.pack(side="right", padx=5)

        self.status_label = ttk.Label(conn_frame, text="Not Connected", foreground="red")
        self.status_label.pack(side="left", padx=10)

        # Trading Frame
        trade_frame = ttk.LabelFrame(self.root, text="Trade ES Futures", padding=10)
        trade_frame.grid(row=1, column=0, padx=10, pady=10, sticky="ew")

        # Direction
        ttk.Label(trade_frame, text="Direction:").grid(row=0, column=0, sticky="w", pady=5)
        self.direction_var = tk.StringVar(value="LONG")
        direction_frame = ttk.Frame(trade_frame)
        direction_frame.grid(row=0, column=1, sticky="w", pady=5)
        ttk.Radiobutton(direction_frame, text="LONG", variable=self.direction_var, value="LONG").pack(
            side="left", padx=5
        )
        ttk.Radiobutton(direction_frame, text="SHORT", variable=self.direction_var, value="SHORT").pack(
            side="left", padx=5
        )

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

        # Stop Loss Points
        ttk.Label(trade_frame, text="Stop Loss (pts):").grid(row=3, column=0, sticky="w", pady=5)
        self.stop_points_var = tk.StringVar(value="10")
        self.stop_entry = ttk.Entry(trade_frame, textvariable=self.stop_points_var, width=12)
        self.stop_entry.grid(row=3, column=1, sticky="w", pady=5)

        # Ladder Interval
        ttk.Label(trade_frame, text="Ladder Interval (pts):").grid(row=4, column=0, sticky="w", pady=5)
        self.ladder_interval_var = tk.StringVar(value="5")
        self.ladder_interval_entry = ttk.Entry(trade_frame, textvariable=self.ladder_interval_var, width=12)
        self.ladder_interval_entry.grid(row=4, column=1, sticky="w", pady=5)

        # Max Contracts
        ttk.Label(trade_frame, text="Max Contracts:").grid(row=5, column=0, sticky="w", pady=5)
        self.max_contracts_var = tk.StringVar(value="3")
        self.max_contracts_entry = ttk.Entry(trade_frame, textvariable=self.max_contracts_var, width=12)
        self.max_contracts_entry.grid(row=5, column=1, sticky="w", pady=5)

        # Execute Button
        self.execute_btn = ttk.Button(trade_frame, text="EXECUTE TRADE", command=self.execute_trade, state="disabled")
        self.execute_btn.grid(row=6, column=0, columnspan=2, pady=15)

        # Info Frame
        info_frame = ttk.LabelFrame(self.root, text="Trade Info", padding=10)
        info_frame.grid(row=2, column=0, padx=10, pady=10, sticky="ew")

        self.info_text = tk.Text(info_frame, height=8, width=50, state="disabled")
        self.info_text.pack()

        # Close Position Frame
        close_frame = ttk.LabelFrame(self.root, text="Close Position", padding=10)
        close_frame.grid(row=3, column=0, padx=10, pady=10, sticky="ew")

        button_frame = ttk.Frame(close_frame)
        button_frame.pack()

        self.close_long_btn = ttk.Button(
            button_frame, text="Close Long", command=self.close_long, state="disabled", width=15
        )
        self.close_long_btn.pack(side="left", padx=5)

        self.close_short_btn = ttk.Button(
            button_frame, text="Close Short", command=self.close_short, state="disabled", width=15
        )
        self.close_short_btn.pack(side="left", padx=5)

    def connect(self):
        host = "127.0.0.1"

        # Try live account first (port 7496)
        print("Attempting to connect to Live Account (port 7496)...")
        success = self.loop.run_until_complete(self.ib_conn.connect(host, 7496))

        if success:
            account_type = "Live Account Connected"
            connected_port = 7496
        else:
            # Try demo account (port 7497)
            print("Live account failed. Attempting Demo Account (port 7497)...")
            success = self.loop.run_until_complete(self.ib_conn.connect(host, 7497))

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
        self.execute_btn.config(state="normal")

        # Show position sync info
        sync_result = self.loop.run_until_complete(self.ib_conn.sync_positions())
        if sync_result:
            # Get average entry price if there's a position
            avg_price = 0.0
            if self.ib_conn.current_quantity > 0:
                avg_price = self.loop.run_until_complete(self.ib_conn.get_avg_entry_price(force_refresh=True))

            info = f"""
Connected to IB!

ES Position: {sync_result['es_position']}
Average Entry Price: {f'{avg_price:.2f}' if avg_price > 0 else 'N/A'}
MES Resting Orders: {sync_result['mes_orders']}

Status: {'LONG' if sync_result['active_long'] else 'SHORT' if sync_result['active_short'] else 'No Position'}
            """
            self.update_info(info)

            # Check if we need to place MES hedge (at max contracts with no hedge)
            try:
                max_contracts = int(self.max_contracts_var.get())
                stop_points = float(self.stop_points_var.get())

                print("\n=== Auto-Hedge Check ===")
                print(f"Current ES Quantity: {self.ib_conn.current_quantity}")
                print(f"Max Contracts Setting: {max_contracts}")
                print(f"Has Hedge: {sync_result.get('has_hedge', False)}")
                print(f"Should place hedge: {self.ib_conn.current_quantity >= max_contracts and self.ib_conn.current_quantity > 0 and not sync_result.get('has_hedge', False)}")
                print("========================\n")

                if (
                    self.ib_conn.current_quantity >= max_contracts
                    and self.ib_conn.current_quantity > 0
                    and not sync_result.get("has_hedge", False)
                ):

                    # Need to place MES hedge
                    direction = "LONG" if sync_result["active_long"] else "SHORT"

                    # Get avg entry price from ES positions (force refresh to get accurate value)
                    avg_entry = self.loop.run_until_complete(self.ib_conn.get_avg_entry_price(force_refresh=True))

                    if avg_entry > 0:
                        mes_action = "SELL" if direction == "LONG" else "BUY"

                        if direction == "LONG":
                            stop_price = avg_entry - stop_points
                        else:
                            stop_price = avg_entry + stop_points

                        stop_price = round(stop_price * 4) / 4
                        mes_quantity = self.ib_conn.current_quantity * 10

                        print("\n!!! PLACING MES HEDGE !!!")
                        print(f"Action: {mes_action}")
                        print(f"Quantity: {mes_quantity}")
                        print(f"Stop Price: {stop_price}")
                        print(f"Based on avg entry: {avg_entry:.2f}\n")

                        # Get MES contract
                        if not self.ib_conn.mes_contract:
                            self.ib_conn.mes_contract = self.loop.run_until_complete(
                                self.ib_conn.get_front_month_contract("MES")
                            )

                        # Place the hedge
                        self.loop.run_until_complete(
                            self.ib_conn.place_stop_order(
                                self.ib_conn.mes_contract, mes_action, mes_quantity, stop_price
                            )
                        )

                        self.ib_conn.mes_hedge_placed = True

                        info += f"\n\nMES Hedge Auto-Placed:\n{mes_action} {mes_quantity} @ {stop_price} (STOP)\nBased on avg entry: {avg_entry:.2f}"
                        self.update_info(info)
                        messagebox.showinfo(
                            "Hedge Placed",
                            f"MES hedge automatically placed!\n{mes_action} {mes_quantity} @ {stop_price}\nBased on avg entry: {avg_entry:.2f}",
                        )
                    else:
                        print("Cannot place hedge: avg_entry is 0")
                else:
                    print("No hedge needed - conditions not met")
            except Exception as e:
                print(f"Error checking/placing hedge: {e}")
                import traceback

                traceback.print_exc()

        self.update_close_buttons()

    def refresh_positions(self):
        """Manually refresh positions from IBKR"""
        if not self.ib_conn.connected:
            messagebox.showerror("Error", "Not connected to IB")
            return

        print("\n*** Manual Refresh Triggered ***\n")

        # Show position sync info
        sync_result = self.loop.run_until_complete(self.ib_conn.sync_positions())
        if sync_result:
            # Get average entry price if there's a position
            avg_price = 0.0
            if self.ib_conn.current_quantity > 0:
                avg_price = self.loop.run_until_complete(self.ib_conn.get_avg_entry_price(force_refresh=True))

            info = f"""
Connected to IB!

ES Position: {sync_result['es_position']}
Average Entry Price: {f'{avg_price:.2f}' if avg_price > 0 else 'N/A'}
MES Resting Orders: {sync_result['mes_orders']}

Status: {'LONG' if sync_result['active_long'] else 'SHORT' if sync_result['active_short'] else 'No Position'}
            """
            self.update_info(info)

            # Check if we need to place MES hedge (at max contracts with no hedge)
            try:
                max_contracts = int(self.max_contracts_var.get())
                stop_points = float(self.stop_points_var.get())

                print("\n=== Auto-Hedge Check ===")
                print(f"Current ES Quantity: {self.ib_conn.current_quantity}")
                print(f"Max Contracts Setting: {max_contracts}")
                print(f"Has Hedge: {sync_result.get('has_hedge', False)}")
                print(f"Should place hedge: {self.ib_conn.current_quantity >= max_contracts and self.ib_conn.current_quantity > 0 and not sync_result.get('has_hedge', False)}")
                print("========================\n")

                if (
                    self.ib_conn.current_quantity >= max_contracts
                    and self.ib_conn.current_quantity > 0
                    and not sync_result.get("has_hedge", False)
                ):

                    # Need to place MES hedge
                    direction = "LONG" if sync_result["active_long"] else "SHORT"

                    # Get avg entry price from ES positions (force refresh to get accurate value)
                    avg_entry = self.loop.run_until_complete(self.ib_conn.get_avg_entry_price(force_refresh=True))

                    if avg_entry > 0:
                        mes_action = "SELL" if direction == "LONG" else "BUY"

                        if direction == "LONG":
                            stop_price = avg_entry - stop_points
                        else:
                            stop_price = avg_entry + stop_points

                        stop_price = round(stop_price * 4) / 4
                        mes_quantity = self.ib_conn.current_quantity * 10

                        print("\n!!! PLACING MES HEDGE !!!")
                        print(f"Action: {mes_action}")
                        print(f"Quantity: {mes_quantity}")
                        print(f"Stop Price: {stop_price}")
                        print(f"Based on avg entry: {avg_entry:.2f}\n")

                        # Get MES contract
                        if not self.ib_conn.mes_contract:
                            self.ib_conn.mes_contract = self.loop.run_until_complete(
                                self.ib_conn.get_front_month_contract("MES")
                            )

                        # Place the hedge
                        self.loop.run_until_complete(
                            self.ib_conn.place_stop_order(
                                self.ib_conn.mes_contract, mes_action, mes_quantity, stop_price
                            )
                        )

                        self.ib_conn.mes_hedge_placed = True

                        info += f"\n\nMES Hedge Auto-Placed:\n{mes_action} {mes_quantity} @ {stop_price} (STOP)\nBased on avg entry: {avg_entry:.2f}"
                        self.update_info(info)
                        messagebox.showinfo(
                            "Hedge Placed",
                            f"MES hedge automatically placed!\n{mes_action} {mes_quantity} @ {stop_price}\nBased on avg entry: {avg_entry:.2f}",
                        )
                    else:
                        print("Cannot place hedge: avg_entry is 0")
                else:
                    print("No hedge needed - conditions not met")
            except Exception as e:
                print(f"Error checking/placing hedge: {e}")
                import traceback

                traceback.print_exc()

        self.update_close_buttons()
        messagebox.showinfo("Refresh Complete", "Positions refreshed from IBKR!")

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

            # Execute trade
            result = self.loop.run_until_complete(
                self.ib_conn.execute_trade_with_ladder(
                    direction, entry_price, stop_points, quantity, ladder_interval, max_contracts
                )
            )

            if result["success"]:
                # Display trade execution info
                ladder_info = ""
                if result.get("ladder_orders"):
                    ladder_info = "\n\nLadder Orders Placed:\n" + "\n".join([f"  - {o['action']} 1 ES @ {o['price']}" for o in result["ladder_orders"]])

                info = f"""
Trade Executed Successfully!

Direction: {result['direction']}
Initial Quantity: {result['quantity']} ES contracts
Initial Fill: {result['es_fill']:.2f}
Expected Avg (if all fill): {result['expected_avg']:.2f}

MES Hedge Placed:
{'SELL' if direction == 'LONG' else 'BUY'} {result['mes_quantity']} MES @ {result['mes_stop']} (STOP)
Stop Loss: {result['stop_points']} points
{ladder_info}

MES hedge is resting from the start, protecting max position.
                """
                self.update_info(info)
                messagebox.showinfo("Success", "Trade executed! MES hedge placed upfront.")

                # Force button update
                self.root.update_idletasks()
                self.update_close_buttons()
                print(f"Active long: {self.ib_conn.active_long}, Active short: {self.ib_conn.active_short}")
            else:
                self.update_info(f"ERROR: {result['message']}\n")
                messagebox.showerror("Error", result["message"])

            # Re-enable button
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

    def update_close_buttons(self):
        """Update close button states based on active positions"""
        # Close Long enabled if: ES LONG position OR MES LONG position
        has_long_side = self.ib_conn.active_long or self.ib_conn.mes_position > 0
        if has_long_side:
            self.close_long_btn.config(state="normal")
        else:
            self.close_long_btn.config(state="disabled")

        # Close Short enabled if: ES SHORT position OR MES SHORT position
        has_short_side = self.ib_conn.active_short or self.ib_conn.mes_position < 0
        if has_short_side:
            self.close_short_btn.config(state="normal")
        else:
            self.close_short_btn.config(state="disabled")

    def close_long(self):
        """Close long position"""
        self.close_long_btn.config(state="disabled")
        self.update_info("Closing long side...\n")

        result = self.loop.run_until_complete(self.ib_conn.close_position("LONG"))

        if result["success"]:
            closed_list = "\n".join(result.get('closed_contracts', []))
            info = f"""
Position Closed!

Direction: LONG
Closed Contracts:
{closed_list}

Average Fill: {result['close_price']:.2f}
Orders Cancelled: {result['cancelled_orders']}

Position successfully closed.
            """
            self.update_info(info)
            messagebox.showinfo("Success", "Long side closed!")
            # Refresh positions to update button states
            self.loop.run_until_complete(self.ib_conn.sync_positions())
            self.update_close_buttons()
        else:
            self.update_info(f"ERROR: {result['message']}\n")
            messagebox.showerror("Error", result["message"])
            self.update_close_buttons()

    def close_short(self):
        """Close short position"""
        self.close_short_btn.config(state="disabled")
        self.update_info("Closing short side...\n")

        result = self.loop.run_until_complete(self.ib_conn.close_position("SHORT"))

        if result["success"]:
            closed_list = "\n".join(result.get('closed_contracts', []))
            info = f"""
Position Closed!

Direction: SHORT
Closed Contracts:
{closed_list}

Average Fill: {result['close_price']:.2f}
Orders Cancelled: {result['cancelled_orders']}

Position successfully closed.
            """
            self.update_info(info)
            messagebox.showinfo("Success", "Short side closed!")
            # Refresh positions to update button states
            self.loop.run_until_complete(self.ib_conn.sync_positions())
            self.update_close_buttons()
        else:
            self.update_info(f"ERROR: {result['message']}\n")
            messagebox.showerror("Error", result["message"])
            self.update_close_buttons()

    def on_closing(self):
        if self.ib_conn.connected:
            self.ib_conn.disconnect()
        self.root.destroy()


def main():
    root = tk.Tk()
    app = TradingUI(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()


if __name__ == "__main__":
    main()
