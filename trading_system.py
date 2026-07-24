import MetaTrader5 as mt5
import pandas as pd
import time
from PyQt6 import QtWidgets, QtCore, QtGui
import sys

# --- Trading Engine Logic ---
class TradingEngine:
    def __init__(self):
        self.symbol_map = {}
        self.loss_count = 0
        self.base_distance = 0.0010  # المسافة الافتراضية
        self.current_distance = self.base_distance

    def initialize_mt5(self):
        if not mt5.initialize():
            print("MT5 Initialization failed")
            return False
        return True

    def get_account_info(self):
        acc = mt5.account_info()
        if acc:
            return acc._asdict()
        return None

    def detect_liquidity(self, symbol):
        # تحليل السيولة بناءً على فجوة السبريد وحركة السعر
        tick = mt5.symbol_info_tick(symbol)
        symbol_info = mt5.symbol_info(symbol)
        if not tick or not symbol_info:
            return "Unknown"
        
        spread = tick.ask - tick.bid
        avg_spread = symbol_info.spread * symbol_info.point
        
        if spread <= avg_spread * 1.2:
            return "High"
        elif spread <= avg_spread * 2.0:
            return "Medium"
        else:
            return "Low"

    def adjust_parameters(self, liquidity):
        # تعديل المسافة بناءً على السيولة وعدد الخسارات
        multiplier = 1.0
        if self.loss_count >= 2:
            multiplier = 1.5 # تكبير المسافة لتجنب التذبذب
        
        if liquidity == "High":
            self.current_distance = self.base_distance * 0.8 * multiplier
        elif liquidity == "Low":
            self.current_distance = self.base_distance * 1.5 * multiplier
        else:
            self.current_distance = self.base_distance * multiplier

    def _round_price(self, value, digits):
        return round(float(value), int(digits))

    def _is_success_result(self, result):
        retcode = getattr(result, "retcode", None)
        return retcode in {
            getattr(mt5, "TRADE_RETCODE_DONE", None),
            getattr(mt5, "TRADE_RETCODE_PLACED", None),
        }

    def _get_pending_filling_type(self):
        for name in ("ORDER_FILLING_RETURN", "ORDER_FILLING_IOC", "ORDER_FILLING_FOK"):
            value = getattr(mt5, name, None)
            if value is not None:
                return value
        return None

    def _remove_pending_order(self, order_ticket):
        if not order_ticket:
            return None
        request = {
            "action": mt5.TRADE_ACTION_REMOVE,
            "order": int(order_ticket),
        }
        return mt5.order_send(request)

    def place_straddle_orders(self, symbol, price, distance, volume):
        info = mt5.symbol_info(symbol)
        if info is None:
            return None, None

        digits = info.digits
        filling_type = self._get_pending_filling_type()

        # حساب مستويات الأوامر
        buy_stop_price = self._round_price(price + distance, digits)
        sell_stop_price = self._round_price(price - distance, digits)

        # وضع Buy Stop مع SL عند سعر الـ Sell Stop
        buy_request = {
            "action": mt5.TRADE_ACTION_PENDING,
            "symbol": symbol,
            "volume": volume,
            "type": mt5.ORDER_TYPE_BUY_STOP,
            "price": buy_stop_price,
            "sl": sell_stop_price,
            "type_time": mt5.ORDER_TIME_GTC,
            "comment": "Arena Straddle",
        }
        if filling_type is not None:
            buy_request["type_filling"] = filling_type

        # وضع Sell Stop مع SL عند سعر الـ Buy Stop
        sell_request = {
            "action": mt5.TRADE_ACTION_PENDING,
            "symbol": symbol,
            "volume": volume,
            "type": mt5.ORDER_TYPE_SELL_STOP,
            "price": sell_stop_price,
            "sl": buy_stop_price,
            "type_time": mt5.ORDER_TIME_GTC,
            "comment": "Arena Straddle",
        }
        if filling_type is not None:
            sell_request["type_filling"] = filling_type

        res1 = mt5.order_send(buy_request)
        if not self._is_success_result(res1):
            return res1, None

        res2 = mt5.order_send(sell_request)
        if not self._is_success_result(res2):
            self._remove_pending_order(getattr(res1, "order", 0))
        return res1, res2

    def trailing_stop(self, symbol, points):
        positions = mt5.positions_get(symbol=symbol)
        if positions:
            for pos in positions:
                # منطق تحريك الستوب لوز بسرعة
                new_sl = 0
                if pos.type == mt5.POSITION_TYPE_BUY:
                    if mt5.symbol_info_tick(symbol).bid - pos.price_open > points * mt5.symbol_info(symbol).point:
                        new_sl = mt5.symbol_info_tick(symbol).bid - (points * 0.5) * mt5.symbol_info(symbol).point
                elif pos.type == mt5.POSITION_TYPE_SELL:
                    if pos.price_open - mt5.symbol_info_tick(symbol).ask > points * mt5.symbol_info(symbol).point:
                        new_sl = mt5.symbol_info_tick(symbol).ask + (points * 0.5) * mt5.symbol_info(symbol).point
                
                if new_sl > 0:
                    request = {
                        "action": mt5.TRADE_ACTION_SLTP,
                        "position": pos.ticket,
                        "sl": new_sl,
                    }
                    mt5.order_send(request)

# --- GUI Components ---
class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.engine = TradingEngine()
        self.engine.initialize_mt5()
        self.setWindowTitle("Arena Pro Trader - MT5")
        self.resize(800, 600)
        
        self.setup_ui()
        
        # Timer للتحديث المستمر
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.update_dashboard)
        self.timer.start(1000)

    def setup_ui(self):
        layout = QtWidgets.QVBoxLayout()
        tabs = QtWidgets.QTabWidget()
        
        # Tab 1: Control Panel
        self.control_tab = QtWidgets.QWidget()
        control_layout = QtWidgets.QGridLayout()
        
        self.symbol_input = QtWidgets.QLineEdit("XAUUSD")
        self.vol_input = QtWidgets.QDoubleSpinBox()
        self.vol_input.setValue(0.1)
        
        self.btn_start = QtWidgets.QPushButton("تشغيل نظام الستوب المزدوج")
        self.btn_start.clicked.connect(self.run_strategy)
        
        control_layout.addWidget(QtWidgets.QLabel("الرمز:"), 0, 0)
        control_layout.addWidget(self.symbol_input, 0, 1)
        control_layout.addWidget(QtWidgets.QLabel("الحجم:"), 1, 0)
        control_layout.addWidget(self.vol_input, 1, 1)
        control_layout.addWidget(self.btn_start, 2, 0, 1, 2)
        
        self.control_tab.setLayout(control_layout)
        
        # Tab 2: Account Details & Trades
        self.info_tab = QtWidgets.QWidget()
        info_layout = QtWidgets.QVBoxLayout()
        self.acc_label = QtWidgets.QLabel("معلومات الحساب...")
        self.trades_table = QtWidgets.QTableWidget()
        self.trades_table.setColumnCount(4)
        self.trades_table.setHorizontalHeaderLabels(["Symbol", "Type", "Open Price", "Profit"])
        info_layout.addWidget(self.acc_label)
        info_layout.addWidget(QtWidgets.QLabel("الصفقات المفتوحة:"))
        info_layout.addWidget(self.trades_table)
        self.info_tab.setLayout(info_layout)
        
        tabs.addTab(self.control_tab, "لوحة التحكم")
        tabs.addTab(self.info_tab, "تفاصيل الحساب والصفقات")
        
        self.setCentralWidget(tabs)

    def update_dashboard(self):
        # تحديث معلومات الحساب
        acc = self.engine.get_account_info()
        if acc:
            self.acc_label.setText(f"Balance: {acc['balance']} | Equity: {acc['equity']} | Spread: {self.get_current_spread()}")
        
        # تحديث الصفقات (تبسيط)
        positions = mt5.positions_get()
        if positions:
            self.trades_table.setRowCount(len(positions))
            self.trades_table.setColumnCount(4)
            for i, p in enumerate(positions):
                self.trades_table.setItem(i, 0, QtWidgets.QTableWidgetItem(str(p.symbol)))
                self.trades_table.setItem(i, 1, QtWidgets.QTableWidgetItem(str(p.type)))
                self.trades_table.setItem(i, 2, QtWidgets.QTableWidgetItem(str(p.price_open)))
                self.trades_table.setItem(i, 3, QtWidgets.QTableWidgetItem(str(p.profit)))
        else:
            self.trades_table.setRowCount(0)
        
        # تشغيل التريلنغ ستوب تلقائياً
        symbol = self.symbol_input.text()
        self.engine.trailing_stop(symbol, 20) # 20 نقطة مثلاً

    def get_current_spread(self):
        symbol = self.symbol_input.text()
        tick = mt5.symbol_info_tick(symbol)
        info = mt5.symbol_info(symbol)
        if tick and info:
            return round((tick.ask - tick.bid) / info.point, 1)
        return 0

    def auto_map_symbol(self, user_symbol):
        """ يكتشف الرمز الصحيح في البروكر تلقائياً """
        all_symbols = [s.name for s in mt5.symbols_get()]
        # تجربة الرمز كما هو، ثم تجربة إضافات شائعة
        suggestions = [user_symbol, user_symbol+"m", user_symbol+".", user_symbol+"#", "GOLD" if "XAU" in user_symbol else user_symbol]
        for s in suggestions:
            if s in all_symbols:
                mt5.symbol_select(s, True)
                return s
        return user_symbol

    def run_strategy(self):
        raw_symbol = self.symbol_input.text()
        symbol = self.auto_map_symbol(raw_symbol)
        volume = self.vol_input.value()
        
        # التأكد من السيولة والسبريد
        symbol_info = mt5.symbol_info(symbol)
        if symbol_info is None:
            QtWidgets.QMessageBox.critical(self, "خطأ", f"الرمز {symbol} غير موجود")
            return

        liq = self.engine.detect_liquidity(symbol)
        self.engine.adjust_parameters(liq)
        
        # التنفيذ
        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            QtWidgets.QMessageBox.critical(self, "خطأ", f"تعذر الحصول على بيانات السوق للرمز {symbol}")
            return
        price = tick.bid
        
        # حساب المسافة بالنقاط بناء على حالة السوق
        dist = self.engine.current_distance
        
        res1, res2 = self.engine.place_straddle_orders(symbol, price, dist, volume)

        if self.engine._is_success_result(res1) and self.engine._is_success_result(res2):
            print(
                f"Buy Stop #{getattr(res1, 'order', '?')} | "
                f"Sell Stop #{getattr(res2, 'order', '?')}"
            )
        elif res1 is None:
            print("Error: تعذر إنشاء أوامر الستوب بسبب عدم توفر بيانات الرمز")
        elif not self.engine._is_success_result(res1):
            print(f"Error Buy Stop: {getattr(res1, 'comment', 'Unknown error')}")
        else:
            print(f"Error Sell Stop: {getattr(res2, 'comment', 'Unknown error')}")

if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
