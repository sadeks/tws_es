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
        order = MarketOrder(action, quantity)
        order.exchange = "CME"
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
        order = LimitOrder(action, quantity, limitPrice=limit_price)
        order.exchange = "CME"
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
        order = StopOrder(action, quantity, stopPrice=stop_price)
        order.exchange = "CME"

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

    def get_positions(self):
        """Get current positions"""
        return self.ib.positions()

    def get_open_orders(self):
        """Get open orders"""
        return self.ib.openOrders()

    async def close_position(self, direction):
        """
        Close ES position and cancel all orders (ladder + MES stop)

        Args:
            direction: 'LONG' or 'SHORT' - the position to close
        """
        if not self.es_contract:
            return {"success": False, "message": "No active ES contract"}

        try:
            # Determine closing action
            close_action = "SELL" if direction == "LONG" else "BUY"

            # Close ES position (use current_quantity)
            print(f"Closing {direction} position - {close_action} {self.current_quantity} ES...")
            es_trade, fill_price = await self.place_market_order(self.es_contract, close_action, self.current_quantity)

            if fill_price == 0.0:
                return {"success": False, "message": "Position closed but could not get fill price"}

            print(f"ES closed at {fill_price}")

            # Cancel all open orders (ladder orders + MES stops)
            open_orders = self.ib.openTrades()
            cancelled_count = 0
            for trade in open_orders:
                if (trade.contract.symbol in ["ES", "MES"]) and not trade.isDone():
                    self.ib.cancelOrder(trade.order)
                    cancelled_count += 1
                    print(f"Cancelled {trade.contract.symbol} order")

            # Update position state
            if direction == "LONG":
                self.active_long = False
            else:
                self.active_short = False

            # Reset position tracking
            self.current_quantity = 0
            self.avg_entry_price = 0.0
            self.ladder_orders = []
            self.direction = None

            return {
                "success": True,
                "close_price": fill_price,
                "direction": direction,
                "cancelled_orders": cancelled_count,
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

            # Check MES resting orders
            mes_orders = 0
            for trade in open_orders:
                if trade.contract.symbol == "MES" and not trade.isDone():
                    mes_orders += 1
                    print(
                        f"MES Open Order: {trade.order.action} {trade.order.totalQuantity} @ {trade.order.auxPrice if hasattr(trade.order, 'auxPrice') else 'Market'}"
                    )
                    if not self.mes_contract:
                        self.mes_contract = trade.contract

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

            print(f"MES Resting Orders: {mes_orders}")
            print("=========================\n")

            return {
                "es_position": es_position,
                "mes_orders": mes_orders,
                "active_long": self.active_long,
                "active_short": self.active_short,
            }

        except Exception as e:
            print(f"Error syncing positions: {e}")
            return None
