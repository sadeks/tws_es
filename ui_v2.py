import sys
import asyncio
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QComboBox, QLineEdit, QPushButton, QTextEdit, QGroupBox,
    QFormLayout, QMessageBox
)
from PyQt6.QtGui import QFont
from api import IBConnection


class BuySellToggle(QWidget):
    """A compact split toggle: left half = Long, right half = Short."""

    modeChanged = pyqtSignal(str)  # Emits "LONG" or "SHORT"

    def __init__(self, parent=None, initial_sell: bool = False):
        super().__init__(parent)

        self._btn_buy = QPushButton("LONG")
        self._btn_sell = QPushButton("SHORT")

        self._btn_buy.setCheckable(True)
        self._btn_sell.setCheckable(True)
        self._btn_buy.setFixedSize(60, 28)
        self._btn_sell.setFixedSize(60, 28)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._btn_buy)
        layout.addWidget(self._btn_sell)
        layout.addStretch()

        self._btn_buy.toggled.connect(self._on_buy_toggled)
        self._btn_sell.toggled.connect(self._on_sell_toggled)

        self._update_styles()
        self.set_mode(sell=initial_sell)

    def _update_styles(self):
        self._btn_buy.setStyleSheet("""
            QPushButton {
                border: 1px solid #888;
                border-top-left-radius: 3px;
                border-bottom-left-radius: 3px;
                border-right: none;
                color: white;
                font-weight: bold;
                font-size: 11px;
                background: #555555;
            }
            QPushButton:checked {
                background: #27ae60;
                color: white;
            }
        """)
        self._btn_sell.setStyleSheet("""
            QPushButton {
                border: 1px solid #888;
                border-top-right-radius: 3px;
                border-bottom-right-radius: 3px;
                border-left: none;
                color: white;
                font-weight: bold;
                font-size: 11px;
                background: #555555;
            }
            QPushButton:checked {
                background: #c0392b;
                color: white;
            }
        """)

    def _on_buy_toggled(self, checked: bool):
        if checked:
            if self._btn_sell.isChecked():
                self._btn_sell.blockSignals(True)
                self._btn_sell.setChecked(False)
                self._btn_sell.blockSignals(False)
            self.modeChanged.emit("LONG")

    def _on_sell_toggled(self, checked: bool):
        if checked:
            if self._btn_buy.isChecked():
                self._btn_buy.blockSignals(True)
                self._btn_buy.setChecked(False)
                self._btn_buy.blockSignals(False)
            self.modeChanged.emit("SHORT")

    def is_sell(self) -> bool:
        return self._btn_sell.isChecked()

    def get_mode(self) -> str:
        return "SHORT" if self._btn_sell.isChecked() else "LONG"

    def set_mode(self, sell: bool):
        if sell:
            self._btn_sell.setChecked(True)
            self._btn_buy.setChecked(False)
        else:
            self._btn_buy.setChecked(True)
            self._btn_sell.setChecked(False)


class TradingUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Futures Trader")
        self.setFixedSize(475, 780)

        self.ib_conn = IBConnection()
        self.loop = asyncio.new_event_loop()

        self.direction = "LONG"

        self.create_widgets()
        self.update_flatten_button()
        self.update_max_loss()

    def create_widgets(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)

        # Status Label
        self.status_label = QLabel("Not Connected")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("color: red; font-weight: bold;")
        main_layout.addWidget(self.status_label)

        # Connection Frame
        conn_group = QGroupBox("Connection")
        conn_layout = QHBoxLayout(conn_group)
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.clicked.connect(self.connect)
        self.refresh_btn = QPushButton("Refresh Positions")
        self.refresh_btn.clicked.connect(self.refresh_positions)
        self.refresh_btn.setEnabled(False)
        conn_layout.addWidget(self.connect_btn)
        conn_layout.addStretch()
        conn_layout.addWidget(self.refresh_btn)
        main_layout.addWidget(conn_group)

        # Trading Frame
        trade_group = QGroupBox("Trade Futures")
        trade_layout = QFormLayout(trade_group)

        # Symbol
        self.symbol_combo = QComboBox()
        self.symbol_combo.addItems(["ES", "MES", "NQ", "MNQ"])
        self.symbol_combo.currentTextChanged.connect(self.on_input_changed)
        trade_layout.addRow("Symbol:", self.symbol_combo)

        # Direction Toggle
        self.direction_toggle = BuySellToggle(initial_sell=False)
        self.direction_toggle.modeChanged.connect(self.on_direction_changed)
        trade_layout.addRow("Direction:", self.direction_toggle)

        # Quantity
        self.quantity_entry = QLineEdit("1")
        self.quantity_entry.setFixedWidth(100)
        self.quantity_entry.textChanged.connect(self.on_input_changed)
        trade_layout.addRow("Quantity:", self.quantity_entry)

        # Entry Price
        entry_widget = QWidget()
        entry_layout = QHBoxLayout(entry_widget)
        entry_layout.setContentsMargins(0, 0, 0, 0)
        self.entry_price_entry = QLineEdit()
        self.entry_price_entry.setFixedWidth(100)
        self.entry_price_entry.setPlaceholderText("Market")
        entry_layout.addWidget(self.entry_price_entry)
        entry_layout.addWidget(QLabel("(leave empty for market)"))
        entry_layout.addStretch()
        trade_layout.addRow("Entry Price:", entry_widget)

        # Stop Loss Points
        stop_widget = QWidget()
        stop_layout = QHBoxLayout(stop_widget)
        stop_layout.setContentsMargins(0, 0, 0, 0)
        self.stop_entry = QLineEdit("10")
        self.stop_entry.setFixedWidth(100)
        self.stop_entry.textChanged.connect(self.on_input_changed)
        self.min_stop_label = QLabel("")
        self.min_stop_label.setStyleSheet("color: orange;")
        self.max_loss_label = QLabel("Max loss: N/A")
        self.max_loss_label.setStyleSheet("color: red;")
        stop_layout.addWidget(self.stop_entry)
        stop_layout.addWidget(self.min_stop_label)
        stop_layout.addWidget(self.max_loss_label)
        stop_layout.addStretch()
        trade_layout.addRow("Stop Loss (pts):", stop_widget)

        # Ladder Interval
        ladder_widget = QWidget()
        ladder_layout = QHBoxLayout(ladder_widget)
        ladder_layout.setContentsMargins(0, 0, 0, 0)
        self.ladder_interval_entry = QLineEdit("5")
        self.ladder_interval_entry.setFixedWidth(100)
        self.ladder_interval_entry.textChanged.connect(self.on_input_changed)
        self.full_ladder_label = QLabel("Full ladder: N/A")
        self.full_ladder_label.setStyleSheet("color: #aaa;")
        ladder_layout.addWidget(self.ladder_interval_entry)
        ladder_layout.addWidget(self.full_ladder_label)
        ladder_layout.addStretch()
        trade_layout.addRow("Ladder Interval (pts):", ladder_widget)

        # Max Contracts
        max_widget = QWidget()
        max_layout = QHBoxLayout(max_widget)
        max_layout.setContentsMargins(0, 0, 0, 0)
        self.max_contracts_entry = QLineEdit("3")
        self.max_contracts_entry.setFixedWidth(100)
        self.max_contracts_entry.textChanged.connect(self.on_input_changed)
        self.room_label = QLabel("Room after last: N/A")
        self.room_label.setStyleSheet("color: #aaa;")
        max_layout.addWidget(self.max_contracts_entry)
        max_layout.addWidget(self.room_label)
        max_layout.addStretch()
        trade_layout.addRow("Max Contracts:", max_widget)

        # Execute Button
        self.execute_btn = QPushButton("EXECUTE TRADE")
        self.execute_btn.setEnabled(False)
        self.execute_btn.clicked.connect(self.execute_trade)
        self.execute_btn.setStyleSheet(
            "QPushButton { padding: 10px; font-weight: bold; background: #4a4a4a; color: white; }"
            "QPushButton:enabled { background: #4a4a4a; color: white; }"
            "QPushButton:disabled { background: #555555; color: #888888; }"
        )
        trade_layout.addRow("", self.execute_btn)

        main_layout.addWidget(trade_group)

        # Info Frame
        info_group = QGroupBox("Trade Info")
        info_layout = QVBoxLayout(info_group)
        self.info_text = QTextEdit()
        self.info_text.setReadOnly(True)
        self.info_text.setFixedHeight(150)
        self.info_text.setFont(QFont("Courier", 11))
        info_layout.addWidget(self.info_text)
        main_layout.addWidget(info_group)

        # Manage Position Frame
        manage_group = QGroupBox("Manage Position")
        manage_layout = QVBoxLayout(manage_group)

        # Breakeven button (faint blue)
        self.breakeven_btn = QPushButton("Move Stop to Breakeven")
        self.breakeven_btn.setEnabled(False)
        self.breakeven_btn.clicked.connect(self.move_stop_to_breakeven)
        self.breakeven_btn.setStyleSheet(
            "QPushButton { padding: 8px; background: #555; color: #888; }"
            "QPushButton:enabled { background: #4a6fa5; color: white; }"
            "QPushButton:disabled { background: #555; color: #888; }"
        )
        manage_layout.addWidget(self.breakeven_btn)

        # Flatten button (faint green)
        self.flatten_btn = QPushButton("Flatten Position")
        self.flatten_btn.setEnabled(False)
        self.flatten_btn.clicked.connect(self.flatten_position)
        self.flatten_btn.setStyleSheet(
            "QPushButton { padding: 8px; background: #555; color: #888; }"
            "QPushButton:enabled { background: #5a8f5a; color: white; }"
            "QPushButton:disabled { background: #555; color: #888; }"
        )
        manage_layout.addWidget(self.flatten_btn)

        main_layout.addWidget(manage_group)
        main_layout.addStretch()

    def on_direction_changed(self, mode: str):
        self.direction = mode

    def on_input_changed(self):
        self.update_max_loss()
        self.update_execute_button()

    def connect(self):
        host = "127.0.0.1"

        print("Attempting to connect to Live Account (port 7496)...")
        success = self.loop.run_until_complete(self.ib_conn.connect(host, 7496))

        if success:
            account_type = "Live Account Connected"
        else:
            print("Live account failed. Attempting Demo Account (port 7497)...")
            success = self.loop.run_until_complete(self.ib_conn.connect(host, 7497))

            if success:
                account_type = "Demo Account Connected"
            else:
                QMessageBox.critical(self, "Connection Error", "Failed to connect to IB on both ports 7496 and 7497")
                return

        self.status_label.setText(account_type)
        self.status_label.setStyleSheet("color: green; font-weight: bold;")
        self.connect_btn.setEnabled(False)
        self.refresh_btn.setEnabled(True)

        self.refresh_positions()

    def refresh_positions(self):
        if not self.ib_conn.connected:
            QMessageBox.critical(self, "Error", "Not connected to IB")
            return

        print("\n*** Manual Refresh Triggered ***\n")

        sync_result = self.loop.run_until_complete(self.ib_conn.sync_positions())
        if sync_result:
            positions_info = []
            for sym, pos in sync_result["positions"].items():
                if pos != 0:
                    avg = self.loop.run_until_complete(self.ib_conn.get_avg_entry_price(sym, force_refresh=True))
                    positions_info.append(f"{sym}: {pos} @ {avg:.2f}" if avg > 0 else f"{sym}: {pos}")

            pos_text = "\n".join(positions_info) if positions_info else "No open positions"
            self.update_info(f"Positions:\n{pos_text}")

        self.update_flatten_button()
        self.update_execute_button()
        self.update_breakeven_button()

    def execute_trade(self):
        if not self.ib_conn.connected:
            QMessageBox.critical(self, "Error", "Not connected to IB")
            return

        try:
            direction = self.direction
            quantity = int(self.quantity_entry.text())
            entry_price_str = self.entry_price_entry.text().strip()
            entry_price = float(entry_price_str) if entry_price_str else None
            stop_points = float(self.stop_entry.text())
            ladder_interval = float(self.ladder_interval_entry.text())
            max_contracts = int(self.max_contracts_entry.text())

            if quantity <= 0:
                QMessageBox.critical(self, "Error", "Quantity must be greater than 0")
                return
            if stop_points <= 0:
                QMessageBox.critical(self, "Error", "Stop loss must be greater than 0")
                return
            if ladder_interval <= 0:
                QMessageBox.critical(self, "Error", "Ladder interval must be greater than 0")
                return
            if max_contracts <= 0:
                QMessageBox.critical(self, "Error", "Max contracts must be greater than 0")
                return

            self.execute_btn.setEnabled(False)
            self.update_info("Executing trade...\n")

            symbol = self.symbol_combo.currentText()

            result = self.loop.run_until_complete(
                self.ib_conn.execute_trade_with_ladder(
                    symbol, direction, entry_price, stop_points, quantity, ladder_interval, max_contracts
                )
            )

            if result["success"]:
                sym = result["symbol"]
                ladder_info = ""
                if result.get("ladder_orders"):
                    ladder_info = "\n\nLadder Orders Placed:\n" + "\n".join(
                        [f"  - {o['action']} {o['quantity']} {sym} @ {o['price']}" for o in result["ladder_orders"]]
                    )

                info = f"""Trade Executed Successfully!

Symbol: {sym}
Direction: {result['direction']}
Initial Quantity: {result['quantity']} contracts
Initial Fill: {result['fill_price']:.2f}
Expected Avg (if all fill): {result['expected_avg']:.2f}

Stop Loss Placed:
{'SELL' if direction == 'LONG' else 'BUY'} {result['stop_quantity']} {sym} @ {result['stop_price']} (STOP)
Stop Loss: {result['stop_points']} points
{ladder_info}"""
                self.update_info(info)

                self.update_flatten_button()
                self.update_execute_button()
                print(f"Active long: {self.ib_conn.active_long}, Active short: {self.ib_conn.active_short}")
            else:
                self.update_info(f"ERROR: {result['message']}\n")
                QMessageBox.critical(self, "Error", result["message"])
                self.execute_btn.setEnabled(True)

        except ValueError:
            QMessageBox.critical(self, "Error", "Invalid input values")
            self.execute_btn.setEnabled(True)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Unexpected error: {str(e)}")
            self.execute_btn.setEnabled(True)

    def update_info(self, text: str):
        self.info_text.setText(text)

    def update_execute_button(self):
        has_any_position = self.ib_conn.active_long or self.ib_conn.active_short
        self.execute_btn.setEnabled(self.ib_conn.connected and not has_any_position)

    def update_flatten_button(self):
        enabled = self.ib_conn.active_long or self.ib_conn.active_short
        self.flatten_btn.setEnabled(enabled)

    def update_breakeven_button(self):
        if not (self.ib_conn.active_long or self.ib_conn.active_short):
            self.breakeven_btn.setEnabled(False)
            return

        symbol = self.ib_conn.active_symbol
        if not symbol:
            self.breakeven_btn.setEnabled(False)
            return

        current_price = self.loop.run_until_complete(self.ib_conn.get_current_price(symbol))
        avg_price = self.ib_conn.avg_entry_price

        if not current_price or avg_price <= 0:
            self.breakeven_btn.setEnabled(False)
            return

        if self.ib_conn.active_long and current_price > avg_price:
            self.breakeven_btn.setEnabled(True)
        elif self.ib_conn.active_short and current_price < avg_price:
            self.breakeven_btn.setEnabled(True)
        else:
            self.breakeven_btn.setEnabled(False)

    def update_max_loss(self):
        multipliers = {"ES": 50.0, "MES": 5.0, "NQ": 20.0, "MNQ": 2.0}
        try:
            symbol = self.symbol_combo.currentText()
            stop_points = float(self.stop_entry.text())
            max_contracts = int(self.max_contracts_entry.text())
            quantity = int(self.quantity_entry.text())
            ladder_interval = float(self.ladder_interval_entry.text())
            multiplier = multipliers.get(symbol, 50.0)

            num_ladders = (max_contracts - quantity) // quantity
            min_stop = (ladder_interval * num_ladders) / 2 + 0.25

            max_loss = stop_points * max_contracts * multiplier

            if stop_points < min_stop:
                self.min_stop_label.setText(f"Min stop: {min_stop:.2f} pts!")
                self.max_loss_label.setText("")
            else:
                self.min_stop_label.setText("")
                self.max_loss_label.setText(f"Max loss: ${max_loss:,.0f}")

            ladder_span = ladder_interval * num_ladders
            room_after_last = stop_points - (ladder_span / 2)
            full_ladder = (ladder_span / 2) + stop_points

            self.room_label.setText(f"Room after last: {room_after_last:.1f} pts")
            self.full_ladder_label.setText(f"Full ladder: {full_ladder:.1f} pts")
        except (ValueError, AttributeError):
            self.min_stop_label.setText("")
            self.max_loss_label.setText("")
            self.room_label.setText("Room after last: N/A")
            self.full_ladder_label.setText("Full ladder: N/A")

    def flatten_position(self):
        self.flatten_btn.setEnabled(False)
        self.update_info("Flattening position...\n")

        symbol = self.ib_conn.active_symbol or self.symbol_combo.currentText()
        result = self.loop.run_until_complete(self.ib_conn.flatten_position(symbol))

        if result["success"]:
            closed_list = "\n".join(result.get("closed_contracts", []))
            info = f"""Position Flattened!

Closed Contracts:
{closed_list}

Average Fill: {result['close_price']:.2f}
Orders Cancelled: {result['cancelled_orders']}

All positions closed and orders cancelled."""
            self.update_info(info)
        else:
            self.update_info(f"ERROR: {result['message']}\n")
            QMessageBox.critical(self, "Error", result["message"])

    def move_stop_to_breakeven(self):
        self.breakeven_btn.setEnabled(False)
        self.update_info("Moving stop to breakeven...\n")

        symbol = self.ib_conn.active_symbol
        if not symbol:
            QMessageBox.critical(self, "Error", "No active position")
            return

        result = self.loop.run_until_complete(self.ib_conn.move_stop_to_breakeven(symbol))

        if result["success"]:
            info = f"""Stop Moved to Breakeven!

Symbol: {result['symbol']}
New Stop Price: {result['stop_price']:.2f}
Stop Quantity: {result['stop_quantity']}
Orders Cancelled: {result['cancelled_orders']}"""
            self.update_info(info)
        else:
            self.update_info(f"ERROR: {result['message']}\n")
            QMessageBox.critical(self, "Error", result["message"])

    def closeEvent(self, event):
        if self.ib_conn.connected:
            self.ib_conn.disconnect()
        event.accept()


def main():
    app = QApplication(sys.argv)

    # Dark theme
    app.setStyleSheet("""
        QMainWindow, QWidget {
            background-color: #2b2b2b;
            color: #ffffff;
        }
        QGroupBox {
            border: 1px solid #555;
            border-radius: 5px;
            margin-top: 10px;
            padding-top: 10px;
            font-weight: bold;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 5px;
        }
        QLineEdit, QComboBox, QTextEdit {
            background-color: #3b3b3b;
            border: 1px solid #555;
            border-radius: 3px;
            padding: 5px;
            color: #ffffff;
        }
        QComboBox::drop-down {
            border: none;
        }
        QComboBox::down-arrow {
            image: none;
            border-left: 5px solid transparent;
            border-right: 5px solid transparent;
            border-top: 5px solid #888;
            margin-right: 5px;
        }
        QPushButton {
            background-color: #4a4a4a;
            border: 1px solid #555;
            border-radius: 3px;
            padding: 8px 15px;
            color: #ffffff;
        }
        QPushButton:hover {
            background-color: #5a5a5a;
        }
        QPushButton:pressed {
            background-color: #3a3a3a;
        }
        QPushButton:disabled {
            background-color: #3a3a3a;
            color: #666;
        }
        QLabel {
            color: #ffffff;
        }
    """)

    window = TradingUI()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
