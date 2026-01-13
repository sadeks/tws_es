from ib_async import IB, Future, MarketOrder, StopOrder, LimitOrder
import asyncio


class IBConnection:
    def __init__(self):
        self.ib = IB()
        self.connected = False
        self.active_long = False
        self.active_short = False
        self.es_contract = None
        self.mes_contract = None
        self.current_quantity = 0
        self.avg_entry_price = 0.0
        self.max_contracts = 0
        self.ladder_interval = 0
        self.stop_points = 0
        self.direction = None
        self.ladder_orders = []
        self.monitor_task = None
        self.mes_hedge_placed = False
        self.mes_position = 0  # Track MES position (negative = short, positive = long)

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

        # Give a moment for fill data to populate
        await asyncio.sleep(0.5)

        # Get actual fill price from fills
        fill_price = 0.0
        if trade.fills:
            # Calculate average fill price from all fills
            total_qty = sum(f.execution.shares for f in trade.fills)
            weighted_price = sum(f.execution.avgPrice * f.execution.shares for f in trade.fills)
            fill_price = weighted_price / total_qty if total_qty > 0 else 0.0

        if fill_price == 0.0 and trade.orderStatus.avgFillPrice:
            fill_price = trade.orderStatus.avgFillPrice

        return trade, fill_price

    async def place_limit_order(self, contract, action, quantity, limit_price):
        """Place limit order (BUY/SELL)"""
        # Qualify contract to ensure it's properly set up for trading
        qualified = await self.ib.qualifyContractsAsync(contract)
        if qualified:
            contract = qualified[0]

        order = LimitOrder(action, quantity, lmtPrice=limit_price)
        trade = self.ib.placeOrder(contract, order)

        # Wait for fill
        while not trade.isDone():
            await self.ib.updateEvent

        # Give a moment for fill data to populate
        await asyncio.sleep(0.5)

        # Get actual fill price from fills
        fill_price = 0.0
        if trade.fills:
            # Calculate average fill price from all fills
            total_qty = sum(f.execution.shares for f in trade.fills)
            weighted_price = sum(f.execution.avgPrice * f.execution.shares for f in trade.fills)
            fill_price = weighted_price / total_qty if total_qty > 0 else 0.0

        if fill_price == 0.0 and trade.orderStatus.avgFillPrice:
            fill_price = trade.orderStatus.avgFillPrice

        return trade, fill_price

    async def place_stop_order(self, contract, action, quantity, stop_price, parent_order_id=None):
        """Place stop order for MES hedge"""
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

    async def monitor_ladder_fills(self):
        """Background task to monitor ladder order fills and place MES hedge when max reached"""
        print("Starting ladder fill monitor...")

        try:
            while self.ladder_orders and not self.mes_hedge_placed:
                await asyncio.sleep(1)  # Check every second

                # Check each ladder order for fills
                for ladder_info in self.ladder_orders[:]:  # Copy list to allow removal during iteration
                    trade = ladder_info["trade"]

                    # Check if order is filled
                    if trade.isDone() and trade.orderStatus.status == "Filled":
                        print(f"Ladder order filled at {ladder_info['price']}")

                        # Get fill details
                        fill_price = ladder_info["price"]
                        fill_qty = 1  # Ladder orders are always 1 contract

                        # Update position tracking
                        total_cost = (self.avg_entry_price * self.current_quantity) + (fill_price * fill_qty)
                        self.current_quantity += fill_qty
                        self.avg_entry_price = total_cost / self.current_quantity

                        print(f"Updated position: {self.current_quantity} contracts @ avg {self.avg_entry_price:.2f}")

                        # Remove filled order from list
                        self.ladder_orders.remove(ladder_info)

                        # Check if we reached max contracts
                        if self.current_quantity >= self.max_contracts:
                            print(f"Max contracts ({self.max_contracts}) reached! Placing MES hedge...")

                            # Cancel any remaining ladder orders
                            for remaining in self.ladder_orders:
                                try:
                                    self.ib.cancelOrder(remaining["trade"].order)
                                    print(f"Cancelled remaining ladder order at {remaining['price']}")
                                except Exception as e:
                                    print(f"Error cancelling order: {e}")

                            self.ladder_orders.clear()

                            # Place MES hedge - get fresh average from IBKR
                            mes_action = "SELL" if self.direction == "LONG" else "BUY"

                            # CRITICAL: Get fresh average from IBKR, don't use cached value
                            fresh_avg = await self.get_avg_entry_price(force_refresh=True)
                            print(f"Using fresh average from IBKR: {fresh_avg:.2f}")

                            if self.direction == "LONG":
                                stop_price = fresh_avg - self.stop_points
                            else:
                                stop_price = fresh_avg + self.stop_points

                            stop_price = round(stop_price * 4) / 4
                            mes_quantity = self.current_quantity * 10

                            print(f"Placing MES {mes_action} stop @ {stop_price} for {mes_quantity} contracts (based on avg {fresh_avg:.2f})")
                            await self.place_stop_order(self.mes_contract, mes_action, mes_quantity, stop_price)

                            self.mes_hedge_placed = True
                            print("MES hedge placed successfully!")
                            break

        except Exception as e:
            print(f"Error in ladder monitor: {e}")

    async def execute_trade_with_ladder(
        self, direction, entry_price, stop_points, quantity, ladder_interval, max_contracts
    ):
        """
        Execute ES trade with ladder system

        Args:
            direction: 'LONG' or 'SHORT'
            entry_price: Entry price for ES (can be None for market order)
            stop_points: Stop loss in points (only applied when max contracts reached)
            quantity: Number of ES contracts for initial trade
            ladder_interval: Points between each ladder level
            max_contracts: Maximum number of contracts to accumulate
        """
        # Get front month contracts
        print("Finding front month contracts...")
        es = await self.get_front_month_contract("ES")
        mes = await self.get_front_month_contract("MES")

        if not es or not mes:
            return {"success": False, "message": "Failed to get front month contracts"}

        print(f"ES Contract: {es.localSymbol} (Exp: {es.lastTradeDateOrContractMonth})")
        print(f"MES Contract: {mes.localSymbol} (Exp: {mes.lastTradeDateOrContractMonth})")

        # Store ladder configuration
        self.max_contracts = max_contracts
        self.ladder_interval = ladder_interval
        self.stop_points = stop_points
        self.direction = direction
        self.es_contract = es
        self.mes_contract = mes

        # Determine actions
        if direction == "LONG":
            es_action = "BUY"
            mes_action = "SELL"
        else:  # SHORT
            es_action = "SELL"
            mes_action = "BUY"

        try:
            # Place initial ES order (limit or market based on entry_price)
            if entry_price:
                # Limit order
                print(f"Placing {es_action} limit order for {quantity} ES @ {entry_price}...")
                es_trade, fill_price = await self.place_limit_order(es, es_action, quantity, entry_price)
            else:
                # Market order
                print(f"Placing {es_action} market order for {quantity} ES...")
                es_trade, fill_price = await self.place_market_order(es, es_action, quantity)

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

            # Place ladder orders if we haven't reached max contracts
            self.ladder_orders = []
            if self.current_quantity < max_contracts:
                remaining_contracts = max_contracts - self.current_quantity

                for i in range(1, remaining_contracts + 1):
                    if direction == "LONG":
                        # For LONG, buy lower (favorable prices)
                        ladder_price = fill_price - (i * ladder_interval)
                    else:
                        # For SHORT, sell higher (favorable prices)
                        ladder_price = fill_price + (i * ladder_interval)

                    # Round to tick size
                    ladder_price = round(ladder_price * 4) / 4

                    print(f"Placing ladder order {i}: {es_action} 1 ES @ {ladder_price}")

                    # Place limit order for ladder
                    ladder_trade = await self.place_limit_order(es, es_action, 1, ladder_price)

                    self.ladder_orders.append({"trade": ladder_trade, "price": ladder_price, "action": es_action})

            # Only place MES hedge if we're already at max contracts
            if self.current_quantity >= max_contracts:
                # Place MES hedge
                if direction == "LONG":
                    stop_price = self.avg_entry_price - stop_points
                else:
                    stop_price = self.avg_entry_price + stop_points

                stop_price = round(stop_price * 4) / 4
                mes_quantity = self.current_quantity * 10

                print(f"Max contracts reached! Placing MES stop order at {stop_price}...")
                mes_trade = await self.place_stop_order(mes, mes_action, mes_quantity, stop_price)
                self.mes_hedge_placed = True

                return {
                    "success": True,
                    "es_fill": fill_price,
                    "direction": direction,
                    "stop_points": stop_points,
                    "quantity": self.current_quantity,
                    "ladder_orders": [{"price": o["price"], "action": o["action"]} for o in self.ladder_orders],
                    "mes_stop": stop_price,
                    "mes_quantity": mes_quantity,
                }
            else:
                # Start background monitoring task for ladder fills
                self.mes_hedge_placed = False
                if self.monitor_task:
                    self.monitor_task.cancel()
                self.monitor_task = asyncio.create_task(self.monitor_ladder_fills())

                return {
                    "success": True,
                    "es_fill": fill_price,
                    "direction": direction,
                    "stop_points": stop_points,
                    "quantity": self.current_quantity,
                    "ladder_orders": [{"price": o["price"], "action": o["action"]} for o in self.ladder_orders],
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
                    # For ES futures, avgCost is total cost basis
                    # Need to divide by multiplier (50 for ES) to get price per point
                    avg_price = pos.avgCost / 50.0
                    self.avg_entry_price = avg_price
                    print(f"Average entry price from IBKR: {avg_price:.2f} (avgCost={pos.avgCost}, multiplier=50)")
                    return avg_price

            return 0.0

        except Exception as e:
            print(f"Error getting avg entry price: {e}")
            return 0.0

    def get_positions(self):
        """Get current positions"""
        return self.ib.positions()

    def get_open_orders(self):
        """Get open orders"""
        return self.ib.openOrders()

    async def close_position(self, direction):
        """
        Close positions for the specified direction

        Args:
            direction: 'LONG' or 'SHORT' - the side to close
            - LONG: closes ES LONG and/or MES LONG positions
            - SHORT: closes ES SHORT and/or MES SHORT positions
        """
        try:
            closed_contracts = []
            fill_prices = []

            print(f"\n=== Closing {direction} positions ===")
            print(f"active_long: {self.active_long}, active_short: {self.active_short}")
            print(f"current_quantity: {self.current_quantity}, mes_position: {self.mes_position}")

            # Close ES LONG position
            if direction == "LONG" and self.active_long and self.current_quantity > 0:
                print(f"Closing LONG ES position - SELL {self.current_quantity} ES...")
                es_trade, fill_price = await self.place_market_order(self.es_contract, "SELL", self.current_quantity)
                if fill_price > 0:
                    closed_contracts.append(f"{self.current_quantity} ES LONG @ {fill_price:.2f}")
                    fill_prices.append(fill_price)
                    print(f"ES closed at {fill_price}")
                self.active_long = False
                self.current_quantity = 0
                self.avg_entry_price = 0.0

            # Close ES SHORT position
            if direction == "SHORT" and self.active_short and self.current_quantity > 0:
                print(f"Closing SHORT ES position - BUY {self.current_quantity} ES...")
                es_trade, fill_price = await self.place_market_order(self.es_contract, "BUY", self.current_quantity)
                if fill_price > 0:
                    closed_contracts.append(f"{self.current_quantity} ES SHORT @ {fill_price:.2f}")
                    fill_prices.append(fill_price)
                    print(f"ES closed at {fill_price}")
                self.active_short = False
                self.current_quantity = 0
                self.avg_entry_price = 0.0

            # Close MES LONG position
            if direction == "LONG" and self.mes_position > 0:
                mes_qty = abs(self.mes_position)
                print(f"Closing LONG MES position - SELL {mes_qty} MES...")
                mes_trade, fill_price = await self.place_market_order(self.mes_contract, "SELL", mes_qty)
                if fill_price > 0:
                    closed_contracts.append(f"{mes_qty} MES LONG @ {fill_price:.2f}")
                    fill_prices.append(fill_price)
                    print(f"MES closed at {fill_price}")
                self.mes_position = 0

            # Close MES SHORT position
            if direction == "SHORT" and self.mes_position < 0:
                mes_qty = abs(self.mes_position)
                print(f"Closing SHORT MES position - BUY {mes_qty} MES...")
                mes_trade, fill_price = await self.place_market_order(self.mes_contract, "BUY", mes_qty)
                if fill_price > 0:
                    closed_contracts.append(f"{mes_qty} MES SHORT @ {fill_price:.2f}")
                    fill_prices.append(fill_price)
                    print(f"MES closed at {fill_price}")
                self.mes_position = 0

            print(f"Closed contracts: {closed_contracts}")

            # Cancel all open orders (ladder orders + MES stops)
            open_orders = self.ib.openTrades()
            cancelled_count = 0
            for trade in open_orders:
                if (trade.contract.symbol in ["ES", "MES"]) and not trade.isDone():
                    self.ib.cancelOrder(trade.order)
                    cancelled_count += 1
                    print(f"Cancelled {trade.contract.symbol} order")

            # Cancel monitoring task if running
            if self.monitor_task:
                self.monitor_task.cancel()
                self.monitor_task = None

            # Reset position tracking
            self.ladder_orders = []
            self.direction = None
            self.mes_hedge_placed = False

            if not closed_contracts:
                return {"success": False, "message": f"No {direction} positions found to close"}

            avg_fill = sum(fill_prices) / len(fill_prices) if fill_prices else 0

            return {
                "success": True,
                "close_price": avg_fill,
                "direction": direction,
                "cancelled_orders": cancelled_count,
                "closed_contracts": closed_contracts,
            }

        except Exception as e:
            return {"success": False, "message": f"Error closing position: {str(e)}"}

    async def sync_positions(self):
        """Sync position state from IB account"""
        try:
            # Wait a moment for position data to load
            await asyncio.sleep(1)

            positions = self.ib.positions()
            open_orders = self.ib.openTrades()

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

            # Determine active positions first (needed for hedge check)
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

            # Check MES hedge - FIRST check filled positions, THEN check resting orders
            mes_orders = 0
            has_hedge = False
            expected_hedge_position = 0  # Expected MES position (negative for LONG ES, positive for SHORT ES)
            expected_hedge_action = None
            expected_hedge_qty = self.current_quantity * 10

            if self.active_long:
                expected_hedge_position = -expected_hedge_qty  # SHORT MES to hedge LONG ES
                expected_hedge_action = "SELL"
            elif self.active_short:
                expected_hedge_position = expected_hedge_qty  # LONG MES to hedge SHORT ES
                expected_hedge_action = "BUY"

            print(f"\n*** HEDGE DETECTION ***")
            print(f"ES Position: {self.current_quantity} {'LONG' if self.active_long else 'SHORT' if self.active_short else 'NONE'}")
            print(f"Expected MES hedge position: {expected_hedge_position} (filled)")
            print(f"OR Expected MES resting order: {expected_hedge_action} {expected_hedge_qty} (stop order)")

            # STEP 1: Check for filled MES position (hedge already triggered)
            print("\nStep 1: Checking filled MES positions...")
            mes_position = 0
            self.mes_position = 0  # Reset to 0 first
            for pos in positions:
                if pos.contract.symbol == "MES":
                    mes_position = pos.position
                    self.mes_position = mes_position  # Store MES position for UI
                    print(f"  Found MES position: {mes_position}")
                    if not self.mes_contract:
                        self.mes_contract = pos.contract
                    break

            if mes_position != 0 and mes_position == expected_hedge_position:
                has_hedge = True
                self.mes_hedge_placed = True
                print(f"  🎯 ✓✓✓ FILLED HEDGE POSITION DETECTED: {mes_position} MES ✓✓✓ 🎯")

            # STEP 2: If no filled position, check for resting stop orders
            if not has_hedge:
                print("\nStep 2: No filled hedge position. Checking resting stop orders...")
                print(f"Total open orders to check: {len(open_orders)}")

                for trade in open_orders:
                    if trade.contract.symbol == "MES" and not trade.isDone():
                        mes_orders += 1
                        order_action = trade.order.action
                        order_qty = trade.order.totalQuantity
                        order_type = trade.order.orderType

                        # Stop orders have auxPrice attribute
                        is_stop_order = hasattr(trade.order, 'auxPrice') and trade.order.auxPrice is not None

                        print(
                            f"\n  MES Order #{mes_orders}: {order_type} {order_action} {order_qty} @ {trade.order.auxPrice if hasattr(trade.order, 'auxPrice') else trade.order.lmtPrice if hasattr(trade.order, 'lmtPrice') else 'Market'}"
                        )

                        # Detailed comparison for debugging
                        action_match = order_action == expected_hedge_action
                        qty_match = int(order_qty) == int(expected_hedge_qty)

                        print(f"    Order Type: '{order_type}'")
                        print(f"    Is Stop Order: {is_stop_order}")
                        print(f"    Action Match: {order_action} == {expected_hedge_action} ? {action_match}")
                        print(f"    Qty Match: {int(order_qty)} == {int(expected_hedge_qty)} ? {qty_match}")

                        # Check if this is our hedge (STOP order, opposite direction, matching quantity)
                        if (expected_hedge_action and
                            is_stop_order and
                            action_match and
                            qty_match):
                            has_hedge = True
                            self.mes_hedge_placed = True
                            print(f"    🎯 ✓✓✓ RESTING HEDGE ORDER DETECTED FOR {self.current_quantity} ES CONTRACTS ✓✓✓ 🎯")

                        if not self.mes_contract:
                            self.mes_contract = trade.contract

            print(f"\n*** HEDGE DETECTION RESULT: {has_hedge} ***\n")

            print(f"MES Resting Orders: {mes_orders}")
            print(f"Has matching hedge: {has_hedge}")
            print("=========================\n")

            return {
                "es_position": es_position,
                "mes_orders": mes_orders,
                "has_hedge": has_hedge,
                "active_long": self.active_long,
                "active_short": self.active_short,
            }

        except Exception as e:
            print(f"Error syncing positions: {e}")
            return None
