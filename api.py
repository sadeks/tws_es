from ib_async import IB, Future, MarketOrder, StopOrder, LimitOrder
import asyncio


class IBConnection:
    # Multipliers for each futures contract
    MULTIPLIERS = {
        "ES": 50.0,
        "MES": 5.0,
        "NQ": 20.0,
        "MNQ": 2.0,
    }

    def __init__(self):
        self.ib = IB()
        self.connected = False
        self.active_long = False
        self.active_short = False
        self.active_symbol = None  # Track which symbol has active position
        self.contract = None  # Current contract
        self.current_quantity = 0
        self.avg_entry_price = 0.0
        self.max_contracts = 0
        self.ladder_interval = 0
        self.stop_points = 0
        self.direction = None
        self.ladder_orders = []

        # For background monitoring
        self.loop = None
        self.monitor_running = False
        self.stop_monitor = False
        self.current_price = None  # Live price updated by monitor
        self.market_data_ticker = None
        self.monitored_symbol = None

    async def connect(self, host="127.0.0.1", port=7497, client_id=1):
        """Connect to IB Gateway or TWS"""
        try:
            await self.ib.connectAsync(host, port, clientId=client_id)
            self.connected = True
            print(f"Connected to IB on {host}:{port}")

            # Check for existing positions on connect
            await self.sync_positions()

            return True
        except Exception as e:
            print(f"Connection failed: {e}")
            self.connected = False
            return False

    def disconnect(self):
        """Disconnect from IB"""
        self.stop_monitor = True
        if self.connected:
            self.ib.disconnect()
            self.connected = False
            print("Disconnected from IB")

    async def start_monitor(self, symbol):
        """Start background monitoring for a symbol"""
        if self.monitor_running and self.monitored_symbol == symbol:
            return  # Already monitoring this symbol

        # Stop existing monitor if running
        if self.monitor_running:
            await self.stop_monitoring()

        self.monitored_symbol = symbol
        self.stop_monitor = False

        # Get contract for the symbol
        contract = await self.get_front_month_contract(symbol)
        if not contract:
            print(f"Could not get contract for {symbol}")
            return

        # Subscribe to market data
        self.market_data_ticker = self.ib.reqMktData(contract)
        print(f"Subscribed to {symbol} market data")

        # Start monitor loop
        if self.loop:
            self.loop.create_task(self._monitor_loop(symbol, contract))

    async def stop_monitoring(self):
        """Stop the background monitor"""
        self.stop_monitor = True
        if self.market_data_ticker and self.monitored_symbol:
            try:
                contract = await self.get_front_month_contract(self.monitored_symbol)
                if contract:
                    self.ib.cancelMktData(contract)
            except Exception:
                pass
        self.market_data_ticker = None
        self.monitored_symbol = None
        self.monitor_running = False
        await asyncio.sleep(0.2)

    async def _monitor_loop(self, symbol, contract):
        """Background loop that updates price and position"""
        self.monitor_running = True
        print(f"Monitor started for {symbol}")
        last_position_update = 0

        while self.connected and not self.stop_monitor:
            await asyncio.sleep(0.1)  # 100ms polling

            # Update price from ticker
            if self.market_data_ticker:
                price = self.market_data_ticker.marketPrice()
                if price is not None and price == price:  # Check for NaN
                    self.current_price = price

            # Update position stats every ~1 second
            current_time = asyncio.get_event_loop().time()
            if current_time - last_position_update >= 1.0:
                await self._update_position_stats(symbol)
                last_position_update = current_time

        self.monitor_running = False
        print(f"Monitor stopped for {symbol}")

    async def _update_position_stats(self, symbol):
        """Update position and average cost from IB"""
        try:
            positions = self.ib.positions()
            multiplier = self.MULTIPLIERS.get(symbol, 50.0)

            found = False
            for pos in positions:
                if pos.contract.symbol == symbol and pos.position != 0:
                    self.current_quantity = abs(int(pos.position))
                    self.avg_entry_price = pos.avgCost / multiplier
                    self.active_long = pos.position > 0
                    self.active_short = pos.position < 0
                    self.active_symbol = symbol
                    found = True
                    break

            if not found:
                # No position for this symbol
                if self.active_symbol == symbol:
                    self.current_quantity = 0
                    self.avg_entry_price = 0.0
                    self.active_long = False
                    self.active_short = False
                    self.active_symbol = None

        except Exception as e:
            print(f"Error updating position stats: {e}")

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

    async def place_market_order(self, contract, action, quantity, wait_for_fill=True):
        """Place market order (BUY/SELL)

        Args:
            wait_for_fill: If True, wait and retry to get fill price. If False, return quickly.
        """
        # Qualify contract to ensure it's properly set up for trading
        qualified = await self.ib.qualifyContractsAsync(contract)
        if qualified:
            contract = qualified[0]

        order = MarketOrder(action, quantity)
        trade = self.ib.placeOrder(contract, order)

        # Wait for fill
        while not trade.isDone():
            await self.ib.updateEvent

        # Quick exit if we don't need fill price
        if not wait_for_fill:
            await asyncio.sleep(0.1)  # Brief pause to let fill notification come through
            fill_price = trade.orderStatus.avgFillPrice or 0.0
            return trade, fill_price

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
        self, symbol, direction, entry_price, stop_points, quantity, ladder_interval, max_contracts
    ):
        """
        Execute futures trade with ladder system

        Args:
            symbol: 'ES', 'MES', 'NQ', or 'MNQ'
            direction: 'LONG' or 'SHORT'
            entry_price: Entry price (can be None for market order)
            stop_points: Stop loss in points
            quantity: Number of contracts for initial trade
            ladder_interval: Points between each ladder level
            max_contracts: Maximum number of contracts to accumulate
        """
        # Get front month contract
        print(f"Finding front month {symbol} contract...")
        contract = await self.get_front_month_contract(symbol)

        if not contract:
            return {"success": False, "message": f"Failed to get front month {symbol} contract"}

        print(f"{symbol} Contract: {contract.localSymbol} (Exp: {contract.lastTradeDateOrContractMonth})")

        # Store ladder configuration
        self.max_contracts = max_contracts
        self.ladder_interval = ladder_interval
        self.stop_points = stop_points
        self.direction = direction
        self.contract = contract
        self.active_symbol = symbol

        # Determine actions
        action = "BUY" if direction == "LONG" else "SELL"

        try:
            # Place initial order (limit or market based on entry_price)
            if entry_price:
                print(f"Placing {action} limit order for {quantity} {symbol} @ {entry_price}...")
                _, fill_price = await self.place_limit_order(
                    contract, action, quantity, entry_price, wait_for_fill=True
                )
            else:
                print(f"Placing {action} market order for {quantity} {symbol}...")
                _, fill_price = await self.place_market_order(contract, action, quantity)

            if fill_price == 0.0:
                return {"success": False, "message": "Order filled but could not get fill price"}

            print(f"{symbol} filled at {fill_price}")

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
                num_ladder_steps = remaining_contracts // quantity

                for i in range(1, num_ladder_steps + 1):
                    if direction == "LONG":
                        ladder_price = fill_price - (i * ladder_interval)
                    else:
                        ladder_price = fill_price + (i * ladder_interval)
                    ladder_price = round(ladder_price * 4) / 4
                    ladder_prices.append(ladder_price)

                # Calculate expected average if all fill
                total_cost = fill_price * quantity
                total_qty = quantity
                for ladder_price in ladder_prices:
                    total_cost += ladder_price * quantity
                    total_qty += quantity

                expected_avg = total_cost / total_qty
                print(f"Expected average if all ladders fill: {expected_avg:.2f}")

                # Place ladder orders
                for i, ladder_price in enumerate(ladder_prices, 1):
                    print(f"Placing ladder order {i}: {action} {quantity} {symbol} @ {ladder_price}")
                    ladder_trade, _ = await self.place_limit_order(
                        contract, action, quantity, ladder_price, wait_for_fill=False
                    )
                    self.ladder_orders.append(
                        {"trade": ladder_trade, "price": ladder_price, "action": action, "quantity": quantity}
                    )
            else:
                expected_avg = self.avg_entry_price

            # Calculate stop price based on expected average
            if direction == "LONG":
                stop_price = expected_avg - stop_points
            else:
                stop_price = expected_avg + stop_points

            stop_price = round(stop_price * 4) / 4

            # Place stop loss to exit entire position
            stop_action = "SELL" if direction == "LONG" else "BUY"

            print(
                f"Placing {symbol} stop loss: {stop_action} {max_contracts} @ {stop_price} (based on expected avg {expected_avg:.2f})"
            )
            await self.place_stop_order(contract, stop_action, max_contracts, stop_price)

            return {
                "success": True,
                "symbol": symbol,
                "fill_price": fill_price,
                "direction": direction,
                "stop_points": stop_points,
                "quantity": self.current_quantity,
                "ladder_orders": [
                    {"price": o["price"], "action": o["action"], "quantity": o["quantity"]} for o in self.ladder_orders
                ],
                "stop_price": stop_price,
                "stop_quantity": max_contracts,
                "expected_avg": expected_avg,
            }

        except Exception as e:
            return {"success": False, "message": f"Error: {str(e)}"}

    async def get_avg_entry_price(self, symbol, force_refresh=False):
        """Get average entry price from position

        Args:
            symbol: 'ES', 'MES', 'NQ', or 'MNQ'
            force_refresh: If True, always get fresh data from IBKR (ignore cached value)
        """
        try:
            # If force_refresh is False and we have a stored value for active symbol, use it
            if not force_refresh and symbol == self.active_symbol and self.avg_entry_price > 0:
                return self.avg_entry_price

            multiplier = self.MULTIPLIERS.get(symbol, 50.0)

            # Get from IBKR position data
            positions = self.ib.positions()
            for pos in positions:
                if pos.contract.symbol == symbol and pos.position != 0:
                    avg_price = pos.avgCost / multiplier
                    if symbol == self.active_symbol:
                        self.avg_entry_price = avg_price

                    print(f"{symbol} Average entry price from IBKR: {avg_price:.2f} (avgCost={pos.avgCost})")
                    return avg_price

            return 0.0

        except Exception as e:
            print(f"Error getting {symbol} avg entry price: {e}")
            return 0.0

    async def get_current_price(self, symbol):
        """Get current market price for symbol"""
        try:
            contract = await self.get_front_month_contract(symbol)
            if not contract:
                return None
            price = await self.get_market_price(contract)
            return price
        except Exception as e:
            print(f"Error getting current price: {e}")
            return None

    async def move_stop_to_breakeven(self, symbol):
        """
        Cancel all resting orders and place new stop at average cost (breakeven)

        Args:
            symbol: 'ES', 'MES', 'NQ', or 'MNQ'
        """
        try:
            print(f"\n=== Moving Stop to Breakeven for {symbol} ===")

            # Use cached average entry price
            avg_price = self.avg_entry_price
            if avg_price <= 0:
                return {"success": False, "message": "Could not get average entry price"}

            # Get position quantity and direction
            positions = self.ib.positions()
            position_qty = 0
            position_contract = None

            for pos in positions:
                if pos.contract.symbol == symbol:
                    position_qty = int(pos.position)
                    position_contract = pos.contract
                    break

            if position_qty == 0:
                return {"success": False, "message": f"No {symbol} position found"}

            # Cancel all open orders for this symbol
            open_orders = self.ib.openTrades()
            cancelled_count = 0
            for trade in open_orders:
                if trade.contract.symbol == symbol and not trade.isDone():
                    self.ib.cancelOrder(trade.order)
                    cancelled_count += 1
                    print(f"Cancelled {symbol} order")

            # Wait for cancellations to process
            await asyncio.sleep(0.5)

            # Place new stop at breakeven (average price)
            stop_price = round(avg_price * 4) / 4  # Round to tick size

            if position_qty > 0:
                # Long position - stop is a SELL
                stop_action = "SELL"
                stop_qty = position_qty
            else:
                # Short position - stop is a BUY
                stop_action = "BUY"
                stop_qty = abs(position_qty)

            print(f"Placing breakeven stop: {stop_action} {stop_qty} {symbol} @ {stop_price}")
            await self.place_stop_order(position_contract, stop_action, stop_qty, stop_price)

            return {
                "success": True,
                "symbol": symbol,
                "stop_price": stop_price,
                "stop_quantity": stop_qty,
                "cancelled_orders": cancelled_count,
            }

        except Exception as e:
            return {"success": False, "message": f"Error moving stop to breakeven: {str(e)}"}

    async def flatten_position(self, symbol):
        """
        Flatten position for given symbol and cancel all resting orders

        Args:
            symbol: 'ES', 'MES', 'NQ', or 'MNQ'
        """
        try:
            closed_contracts = []
            fill_prices = []

            print(f"\n=== Flattening {symbol} Position ===")

            # Get positions from IBKR
            positions = self.ib.positions()
            position_qty = 0
            position_contract = None

            print(f"Checking {len(positions)} positions...")
            for pos in positions:
                print(f"  {pos.contract.symbol}: {pos.position} (type: {type(pos.position).__name__})")
                if pos.contract.symbol == symbol:
                    # Sum up all positions for this symbol (in case of multiple entries)
                    position_qty += int(pos.position)
                    if not position_contract:
                        position_contract = pos.contract

            print(f"Total {symbol} position to flatten: {position_qty}")

            # Get contract if we don't have one from positions
            if not position_contract:
                position_contract = await self.get_front_month_contract(symbol)

            # Close position if exists
            if position_qty != 0 and position_contract:
                if position_qty > 0:
                    # Long position - sell to close
                    print(f"Closing LONG {symbol} position - SELL {position_qty}...")
                    _, fill_price = await self.place_market_order(position_contract, "SELL", position_qty, wait_for_fill=False)
                    closed_contracts.append(f"{position_qty} {symbol} LONG @ {fill_price:.2f}" if fill_price > 0 else f"{position_qty} {symbol} LONG")
                    if fill_price > 0:
                        fill_prices.append(fill_price)
                    print(f"{symbol} closed")
                else:
                    # Short position - buy to close
                    qty = abs(position_qty)
                    print(f"Closing SHORT {symbol} position - BUY {qty}...")
                    _, fill_price = await self.place_market_order(position_contract, "BUY", qty, wait_for_fill=False)
                    closed_contracts.append(f"{qty} {symbol} SHORT @ {fill_price:.2f}" if fill_price > 0 else f"{qty} {symbol} SHORT")
                    if fill_price > 0:
                        fill_prices.append(fill_price)
                    print(f"{symbol} closed")

                # Reset tracking if this was the active symbol
                if self.active_symbol == symbol:
                    self.active_long = False
                    self.active_short = False
                    self.current_quantity = 0
                    self.avg_entry_price = 0.0
                    self.active_symbol = None

            print(f"Closed contracts: {closed_contracts}")

            # Cancel all open orders for this symbol
            open_orders = self.ib.openTrades()
            cancelled_count = 0
            for trade in open_orders:
                if trade.contract.symbol == symbol and not trade.isDone():
                    self.ib.cancelOrder(trade.order)
                    cancelled_count += 1
                    print(f"Cancelled {symbol} order")

            # Reset position tracking
            self.ladder_orders = []
            self.direction = None

            if not closed_contracts and cancelled_count == 0:
                return {"success": False, "message": f"No {symbol} positions or orders to flatten"}

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
        """Sync position state from IB account for all supported symbols"""
        try:
            # Wait a moment for position data to load
            await asyncio.sleep(1)

            positions = self.ib.positions()

            print("\n=== Syncing Positions ===")

            # Check all supported symbols
            symbols = ["ES", "MES", "NQ", "MNQ"]
            position_data = {}

            for symbol in symbols:
                position_data[symbol] = 0
                for pos in positions:
                    if pos.contract.symbol == symbol:
                        position_data[symbol] = int(pos.position)
                        print(f"{symbol} Position: {pos.position}")
                        # Store contract if it's the active symbol
                        if pos.position != 0 and not self.contract:
                            self.contract = pos.contract
                            self.active_symbol = symbol
                        break

            # Determine active position (first non-zero position found)
            self.active_long = False
            self.active_short = False
            self.current_quantity = 0

            for symbol in symbols:
                pos = position_data[symbol]
                if pos > 0:
                    self.active_long = True
                    self.current_quantity = abs(pos)
                    self.active_symbol = symbol
                    print(f"Status: LONG {symbol} position detected")
                    break
                elif pos < 0:
                    self.active_short = True
                    self.current_quantity = abs(pos)
                    self.active_symbol = symbol
                    print(f"Status: SHORT {symbol} position detected")
                    break

            if not self.active_long and not self.active_short:
                print("Status: No open positions")
                self.active_symbol = None

            print("=========================\n")

            return {
                "positions": position_data,
                "active_long": self.active_long,
                "active_short": self.active_short,
                "active_symbol": self.active_symbol,
            }

        except Exception as e:
            print(f"Error syncing positions: {e}")
            return None
