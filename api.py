from ib_async import IB, Future, MarketOrder, StopOrder, LimitOrder
import asyncio
import json
import os
from datetime import datetime


class IBConnection:
    def __init__(self):
        self.ib = IB()
        self.connected = False
        self.active_long = False
        self.active_short = False
        self.es_contract = None
        self.current_quantity = 0
        self.avg_entry_price = 0.0
        self.max_contracts = 0
        self.ladder_interval = 0
        self.stop_points = 0
        self.direction = None
        self.ladder_orders = []

        # Trade counter
        self.trade_counter_file = os.path.join(os.path.dirname(__file__), "trade_counter.json")
        self.max_trades_per_day = 2
        self.today_trade_count = 0

    def load_trade_counter(self):
        """Load trade counter from JSON file"""
        today = datetime.now().strftime("%Y-%m-%d")

        # Create file if doesn't exist
        if not os.path.exists(self.trade_counter_file):
            data = {today: 0}
            with open(self.trade_counter_file, "w") as f:
                json.dump(data, f, indent=2)
            self.today_trade_count = 0
            print(f"Created trade counter file. Today ({today}): 0 trades")
            return

        # Load existing file
        with open(self.trade_counter_file, "r") as f:
            data = json.load(f)

        # Check if today's date exists
        if today not in data:
            data[today] = 0
            with open(self.trade_counter_file, "w") as f:
                json.dump(data, f, indent=2)
            print(f"New day detected. Reset counter for {today}")

        self.today_trade_count = data[today]
        print(f"Trade counter loaded. Today ({today}): {self.today_trade_count}/{self.max_trades_per_day} trades")

    def increment_trade_counter(self):
        """Increment today's trade count"""
        today = datetime.now().strftime("%Y-%m-%d")

        with open(self.trade_counter_file, "r") as f:
            data = json.load(f)

        data[today] = data.get(today, 0) + 1
        self.today_trade_count = data[today]

        with open(self.trade_counter_file, "w") as f:
            json.dump(data, f, indent=2)

        print(f"Trade count incremented: {self.today_trade_count}/{self.max_trades_per_day}")

    def can_execute_trade(self):
        """Check if we can execute another trade today"""
        return self.today_trade_count < self.max_trades_per_day

    async def connect(self, host="127.0.0.1", port=7497, client_id=1):
        """Connect to IB Gateway or TWS"""
        try:
            await self.ib.connectAsync(host, port, clientId=client_id)
            self.connected = True
            print(f"Connected to IB on {host}:{port}")

            # Load trade counter for today
            self.load_trade_counter()

            # Check for existing positions on connect
            await self.sync_positions()

            return True
        except Exception as e:
            print(f"Connection failed: {e}")
            self.connected = False
            return False

    def disconnect(self):
        """Disconnect from IB"""
        if self.connected:
            self.ib.disconnect()
            self.connected = False
            print("Disconnected from IB")

    def create_contract(self, symbol, exchange="CME", currency="USD", last_trade_date=""):
        """Create futures contract"""
        contract = Future(
            symbol=symbol, exchange=exchange, currency=currency, lastTradeDateOrContractMonth=last_trade_date
        )
        return contract

    async def qualify_contract(self, contract):
        """Qualify contract to get full details"""
        qualified = await self.ib.qualifyContractsAsync(contract)
        if qualified:
            return qualified[0]
        return None

    async def get_front_month_contract(self, symbol):
        """Get the front month (nearest expiration) contract"""
        # Request contract details to get all available contracts
        contract = Future(symbol=symbol, exchange="CME", currency="USD")
        details = await self.ib.reqContractDetailsAsync(contract)

        if not details:
            return None

        # Extract contracts and sort by expiration date
        contracts = [cd.contract for cd in details]
        contracts.sort(key=lambda x: x.lastTradeDateOrContractMonth)

        # Return the nearest expiration (front month)
        return contracts[0]

    async def get_market_price(self, contract):
        """Get current market price"""
        ticker = self.ib.reqMktData(contract)
        await asyncio.sleep(2)  # Wait for data

        if ticker.last and ticker.last > 0:
            price = ticker.last
        elif ticker.close and ticker.close > 0:
            price = ticker.close
        else:
            price = None

        self.ib.cancelMktData(contract)
        return price

    async def place_market_order(self, contract, action, quantity):
        """Place market order (BUY/SELL)"""
        # Qualify contract to ensure it's properly set up for trading
        qualified = await self.ib.qualifyContractsAsync(contract)
        if qualified:
            contract = qualified[0]

        order = MarketOrder(action, quantity)
        trade = self.ib.placeOrder(contract, order)

        # Wait for fill
        while not trade.isDone():
            await self.ib.updateEvent

        # Retry loop to get fill price (data may take time to populate)
        fill_price = 0.0
        for attempt in range(5):
            await asyncio.sleep(0.5)

            # Try to get fill price from fills
            if trade.fills:
                total_qty = sum(f.execution.shares for f in trade.fills)
                weighted_price = sum(f.execution.avgPrice * f.execution.shares for f in trade.fills)
                fill_price = weighted_price / total_qty if total_qty > 0 else 0.0

            # Fallback to orderStatus
            if fill_price == 0.0 and trade.orderStatus.avgFillPrice:
                fill_price = trade.orderStatus.avgFillPrice

            if fill_price > 0.0:
                break

            print(f"Waiting for fill price (attempt {attempt + 1}/5)...")

        # Last resort: get current market price
        if fill_price == 0.0:
            print("Fill price not available from order, fetching market price...")
            market_price = await self.get_market_price(contract)
            if market_price:
                fill_price = market_price

        return trade, fill_price

    async def place_limit_order(self, contract, action, quantity, limit_price, wait_for_fill=True):
        """Place limit order (BUY/SELL)

        Args:
            wait_for_fill: If True, wait for order to fill. If False, just place and return limit price.
        """
        # Qualify contract to ensure it's properly set up for trading
        qualified = await self.ib.qualifyContractsAsync(contract)
        if qualified:
            contract = qualified[0]

        order = LimitOrder(action, quantity, lmtPrice=limit_price)
        trade = self.ib.placeOrder(contract, order)

        # If not waiting for fill, just return the limit price
        if not wait_for_fill:
            return trade, limit_price

        # Wait for fill
        while not trade.isDone():
            await self.ib.updateEvent

        # Retry loop to get fill price (data may take time to populate)
        fill_price = 0.0
        for attempt in range(3):
            await asyncio.sleep(0.5)

            # Try to get fill price from fills
            if trade.fills:
                total_qty = sum(f.execution.shares for f in trade.fills)
                weighted_price = sum(f.execution.avgPrice * f.execution.shares for f in trade.fills)
                fill_price = weighted_price / total_qty if total_qty > 0 else 0.0

            # Fallback to orderStatus
            if fill_price == 0.0 and trade.orderStatus.avgFillPrice:
                fill_price = trade.orderStatus.avgFillPrice

            if fill_price > 0.0:
                break

        # Fallback: if still 0, use limit price (order was filled at limit)
        if fill_price == 0.0:
            fill_price = limit_price

        return trade, fill_price

    async def place_stop_order(self, contract, action, quantity, stop_price, parent_order_id=None):
        """Place stop order"""
        # Qualify contract to ensure it's properly set up for trading
        qualified = await self.ib.qualifyContractsAsync(contract)
        if qualified:
            contract = qualified[0]

        order = StopOrder(action, quantity, stopPrice=stop_price)

        if parent_order_id:
            order.parentId = parent_order_id
            order.transmit = True

        trade = self.ib.placeOrder(contract, order)
        return trade

    async def execute_trade_with_ladder(
        self, direction, entry_price, stop_points, quantity, ladder_interval, max_contracts
    ):
        """
        Execute ES trade with ladder system

        Args:
            direction: 'LONG' or 'SHORT'
            entry_price: Entry price for ES (can be None for market order)
            stop_points: Stop loss in points
            quantity: Number of ES contracts for initial trade
            ladder_interval: Points between each ladder level
            max_contracts: Maximum number of contracts to accumulate
        """
        # Check trade limit
        if not self.can_execute_trade():
            return {
                "success": False,
                "message": f"Daily trade limit reached ({self.max_trades_per_day} trades). Cannot execute new trade."
            }

        # Get front month ES contract
        print("Finding front month ES contract...")
        es = await self.get_front_month_contract("ES")

        if not es:
            return {"success": False, "message": "Failed to get front month ES contract"}

        print(f"ES Contract: {es.localSymbol} (Exp: {es.lastTradeDateOrContractMonth})")

        # Store ladder configuration
        self.max_contracts = max_contracts
        self.ladder_interval = ladder_interval
        self.stop_points = stop_points
        self.direction = direction
        self.es_contract = es

        # Determine actions
        es_action = "BUY" if direction == "LONG" else "SELL"

        try:
            # Place initial ES order (limit or market based on entry_price)
            if entry_price:
                # Limit order - wait for fill to get actual entry price
                print(f"Placing {es_action} limit order for {quantity} ES @ {entry_price}...")
                _, fill_price = await self.place_limit_order(
                    es, es_action, quantity, entry_price, wait_for_fill=True
                )
            else:
                # Market order
                print(f"Placing {es_action} market order for {quantity} ES...")
                _, fill_price = await self.place_market_order(es, es_action, quantity)

            if fill_price == 0.0:
                return {"success": False, "message": "Order filled but could not get fill price"}

            print(f"ES filled at {fill_price}")

            # Initialize position tracking
            self.current_quantity = quantity
            self.avg_entry_price = fill_price

            # Set active position
            if direction == "LONG":
                self.active_long = True
            else:
                self.active_short = True

            # Calculate expected average if all ladder orders fill
            self.ladder_orders = []
            ladder_prices = []

            if self.current_quantity < max_contracts:
                remaining_contracts = max_contracts - self.current_quantity
                # Number of ladder steps (each step adds 'quantity' contracts)
                num_ladder_steps = remaining_contracts // quantity

                # Calculate all ladder prices first
                for i in range(1, num_ladder_steps + 1):
                    if direction == "LONG":
                        ladder_price = fill_price - (i * ladder_interval)
                    else:
                        ladder_price = fill_price + (i * ladder_interval)
                    ladder_price = round(ladder_price * 4) / 4
                    ladder_prices.append(ladder_price)

                # Calculate expected average if all fill
                total_cost = fill_price * quantity  # Initial fill
                total_qty = quantity
                for ladder_price in ladder_prices:
                    total_cost += ladder_price * quantity  # Each ladder adds 'quantity' contracts
                    total_qty += quantity

                expected_avg = total_cost / total_qty
                print(f"Expected average if all ladders fill: {expected_avg:.2f}")

                # Place ladder orders (don't wait for fills - these are resting orders)
                for i, ladder_price in enumerate(ladder_prices, 1):
                    print(f"Placing ladder order {i}: {es_action} {quantity} ES @ {ladder_price}")
                    ladder_trade, _ = await self.place_limit_order(
                        es, es_action, quantity, ladder_price, wait_for_fill=False
                    )
                    self.ladder_orders.append(
                        {"trade": ladder_trade, "price": ladder_price, "action": es_action, "quantity": quantity}
                    )
            else:
                # Already at max, use current average
                expected_avg = self.avg_entry_price

            # Calculate stop price based on expected average
            if direction == "LONG":
                stop_price = expected_avg - stop_points
            else:
                stop_price = expected_avg + stop_points

            stop_price = round(stop_price * 4) / 4

            # Place ES stop loss to exit entire position
            es_stop_action = "SELL" if direction == "LONG" else "BUY"
            es_stop_quantity = max_contracts

            print(
                f"Placing ES stop loss: {es_stop_action} {es_stop_quantity} @ {stop_price} (based on expected avg {expected_avg:.2f})"
            )
            await self.place_stop_order(es, es_stop_action, es_stop_quantity, stop_price)

            # Increment trade counter after successful execution
            self.increment_trade_counter()

            return {
                "success": True,
                "es_fill": fill_price,
                "direction": direction,
                "stop_points": stop_points,
                "quantity": self.current_quantity,
                "ladder_orders": [
                    {"price": o["price"], "action": o["action"], "quantity": o["quantity"]} for o in self.ladder_orders
                ],
                "es_stop": stop_price,
                "es_stop_quantity": es_stop_quantity,
                "expected_avg": expected_avg,
            }

        except Exception as e:
            return {"success": False, "message": f"Error: {str(e)}"}

    async def get_avg_entry_price(self, force_refresh=False):
        """Get average entry price from ES position

        Args:
            force_refresh: If True, always get fresh data from IBKR (ignore cached value)
        """
        try:
            # If force_refresh is False and we have a stored value, use it
            if not force_refresh and self.avg_entry_price > 0:
                return self.avg_entry_price

            # Get from IBKR position data (most accurate for existing positions)
            positions = self.ib.positions()
            for pos in positions:
                if pos.contract.symbol == "ES" and pos.position != 0:
                    # For futures, avgCost is total cost basis
                    # Need to divide by multiplier to get price per point
                    avg_price = pos.avgCost / 50.0
                    self.avg_entry_price = avg_price

                    print(
                        f"ES Average entry price from IBKR: {avg_price:.2f} (avgCost={pos.avgCost})"
                    )
                    return avg_price

            return 0.0

        except Exception as e:
            print(f"Error getting ES avg entry price: {e}")
            return 0.0

    def get_positions(self):
        """Get current positions"""
        return self.ib.positions()

    def get_open_orders(self):
        """Get open orders"""
        return self.ib.openOrders()

    async def flatten_position(self):
        """
        Flatten all ES positions and cancel all resting orders
        """
        try:
            closed_contracts = []
            fill_prices = []

            print("\n=== Flattening Position ===")
            print(f"active_long: {self.active_long}, active_short: {self.active_short}")
            print(f"current_quantity: {self.current_quantity}")

            # Close ES LONG position
            if self.active_long and self.current_quantity > 0:
                print(f"Closing LONG ES position - SELL {self.current_quantity} ES...")
                _, fill_price = await self.place_market_order(self.es_contract, "SELL", self.current_quantity)
                if fill_price > 0:
                    closed_contracts.append(f"{self.current_quantity} ES LONG @ {fill_price:.2f}")
                    fill_prices.append(fill_price)
                    print(f"ES closed at {fill_price}")
                self.active_long = False
                self.current_quantity = 0
                self.avg_entry_price = 0.0

            # Close ES SHORT position
            elif self.active_short and self.current_quantity > 0:
                print(f"Closing SHORT ES position - BUY {self.current_quantity} ES...")
                _, fill_price = await self.place_market_order(self.es_contract, "BUY", self.current_quantity)
                if fill_price > 0:
                    closed_contracts.append(f"{self.current_quantity} ES SHORT @ {fill_price:.2f}")
                    fill_prices.append(fill_price)
                    print(f"ES closed at {fill_price}")
                self.active_short = False
                self.current_quantity = 0
                self.avg_entry_price = 0.0

            print(f"Closed contracts: {closed_contracts}")

            # Cancel all open ES orders (ladder orders + stops)
            open_orders = self.ib.openTrades()
            cancelled_count = 0
            for trade in open_orders:
                if trade.contract.symbol == "ES" and not trade.isDone():
                    self.ib.cancelOrder(trade.order)
                    cancelled_count += 1
                    print("Cancelled ES order")

            # Reset position tracking
            self.ladder_orders = []
            self.direction = None

            if not closed_contracts and cancelled_count == 0:
                return {"success": False, "message": "No positions or orders to flatten"}

            avg_fill = sum(fill_prices) / len(fill_prices) if fill_prices else 0

            return {
                "success": True,
                "close_price": avg_fill,
                "cancelled_orders": cancelled_count,
                "closed_contracts": closed_contracts,
            }

        except Exception as e:
            return {"success": False, "message": f"Error flattening position: {str(e)}"}

    async def sync_positions(self):
        """Sync position state from IB account"""
        try:
            # Wait a moment for position data to load
            await asyncio.sleep(1)

            positions = self.ib.positions()

            print("\n=== Syncing Positions ===")

            # Check ES positions
            es_position = 0
            for pos in positions:
                if pos.contract.symbol == "ES":
                    es_position = pos.position
                    print(f"ES Position: {es_position}")
                    if not self.es_contract:
                        self.es_contract = pos.contract
                    break

            # Determine active positions
            if es_position > 0:
                self.active_long = True
                self.active_short = False
                self.current_quantity = abs(es_position)
                print("Status: LONG position detected")
            elif es_position < 0:
                self.active_short = True
                self.active_long = False
                self.current_quantity = abs(es_position)
                print("Status: SHORT position detected")
            else:
                self.active_long = False
                self.active_short = False
                self.current_quantity = 0
                print("Status: No ES position")

            print("=========================\n")

            return {
                "es_position": es_position,
                "active_long": self.active_long,
                "active_short": self.active_short,
            }

        except Exception as e:
            print(f"Error syncing positions: {e}")
            return None
