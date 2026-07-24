import sys
import MetaTrader5 as mt5
from PyQt6 import QtWidgets, QtCore, QtGui
import threading
import time
from typing import Any
from trading_logic import TradingLogic
import utils


def mt5_call(name: str, *args: Any, **kwargs: Any) -> Any:
    func = getattr(mt5, name, None)
    if callable(func):
        return func(*args, **kwargs)
    return None


def mt5_has(name: str) -> bool:
    return hasattr(mt5, name)

class ProfessionalTraderApp(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.logic = TradingLogic()
        self.is_active = False
        
        self.setWindowTitle("Arena Auto-Trader (MT5 Integrated)")
        self.resize(1100, 850)
        
        # تهيئة الواجهة
        self.init_ui()
        
        # محاولة الاتصال التلقائي عند التشغيل
        QtCore.QTimer.singleShot(1000, self.auto_connect_mt5)
        
        # مؤقت لتحديث البيانات (الرصيد والصفقات ومعلومات السوق)
        self.ui_timer = QtCore.QTimer()
        self.ui_timer.timeout.connect(self.update_dashboard)
        self.ui_timer.start(1000)

    def init_ui(self):
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        main_layout = QtWidgets.QVBoxLayout(central)

        # 1. شريط الحالة العلوي
        self.top_status = QtWidgets.QFrame()
        self.top_status.setStyleSheet("background-color: #34495e; border-radius: 5px;")
        top_layout = QtWidgets.QHBoxLayout(self.top_status)
        
        self.conn_light = QtWidgets.QLabel("●")
        self.conn_light.setStyleSheet("color: gray; font-size: 20px;")
        self.conn_status = QtWidgets.QLabel("جاري البحث عن MetaTrader 5...")
        self.conn_status.setStyleSheet("color: white; font-weight: bold;")
        
        self.acc_info_label = QtWidgets.QLabel("الحساب: غير متصل")
        self.acc_info_label.setStyleSheet("color: #ecf0f1;")
        
        btn_reconnect = QtWidgets.QPushButton("إعادة اتصال")
        btn_reconnect.clicked.connect(self.auto_connect_mt5)
        
        top_layout.addWidget(self.conn_light)
        top_layout.addWidget(self.conn_status)
        top_layout.addStretch()
        top_layout.addWidget(self.acc_info_label)
        top_layout.addWidget(btn_reconnect)
        main_layout.addWidget(self.top_status)

        # 2. منطقة التحكم والبيانات
        content_layout = QtWidgets.QHBoxLayout()
        
        # الجانب الأيسر (التحكم)
        side_panel = QtWidgets.QVBoxLayout()
        
        self.btn_master_start = QtWidgets.QPushButton("بدء التداول التلقائي")
        self.btn_master_start.setFixedHeight(80)
        self.btn_master_start.setStyleSheet("background-color: #27ae60; color: white; font-size: 18px; font-weight: bold; border-radius: 10px;")
        self.btn_master_start.setEnabled(False)
        self.btn_master_start.clicked.connect(self.toggle_master_system)
        
        cfg_group = QtWidgets.QGroupBox("إعدادات الصفقة")
        cfg_layout = QtWidgets.QFormLayout()
        self.sym_input = QtWidgets.QLineEdit("XAUUSD")
        self.lot_input = QtWidgets.QDoubleSpinBox()
        self.lot_input.setRange(0.01, 100.0)
        self.lot_input.setValue(0.1)
        self.dist_input = QtWidgets.QSpinBox()
        self.dist_input.setRange(5, 1000)
        self.dist_input.setValue(30)
        
        cfg_layout.addRow("الرمز:", self.sym_input)
        cfg_layout.addRow("اللوت:", self.lot_input)
        cfg_layout.addRow("المسافة (نقاط):", self.dist_input)
        cfg_group.setLayout(cfg_layout)
        
        side_panel.addWidget(self.btn_master_start)
        side_panel.addWidget(cfg_group)
        side_panel.addStretch()
        
        # الجانب الأيمن (التبويبات)
        self.tabs = QtWidgets.QTabWidget()
        
        # تبويب السجل
        self.log_view = QtWidgets.QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setStyleSheet("background-color: #1e1e1e; color: #00ff00; font-family: 'Consolas';")
        
        # تبويب الصفقات
        self.trade_table = QtWidgets.QTableWidget(0, 5)
        self.trade_table.setHorizontalHeaderLabels(["ID", "Symbol", "Type", "Profit", "SL"])
        header = self.trade_table.horizontalHeader()
        if header is not None:
            header.setStretchLastSection(True)
        
        self.tabs.addTab(self.log_view, "سجل العمليات")
        self.tabs.addTab(self.trade_table, "الصفقات المفتوحة")
        
        content_layout.addLayout(side_panel, 1)
        content_layout.addWidget(self.tabs, 2)
        
        main_layout.addLayout(content_layout)

    def log(self, message):
        timestamp = time.strftime('%H:%M:%S')
        self.log_view.append(f"[{timestamp}] {message}")

    def auto_connect_mt5(self):
        self.log("محاولة الاتصال بـ MetaTrader 5...")
        if mt5_call('initialize'):
            acc = mt5_call('account_info')
            if acc:
                self.conn_light.setStyleSheet("color: #2ecc71; font-size: 20px;")
                self.conn_status.setText(f"متصل: {acc.company}")
                self.acc_info_label.setText(f"حساب: {acc.login} | {acc.currency}")
                self.btn_master_start.setEnabled(True)
                self.log(f"تم الربط بنجاح مع الحساب {acc.login}")
            else:
                self.conn_light.setStyleSheet("color: #e74c3c; font-size: 20px;")
                self.conn_status.setText("فشل جلب بيانات الحساب.")
                self.btn_master_start.setEnabled(False)
                self.log("فشل جلب بيانات الحساب.")
        else:
            self.conn_light.setStyleSheet("color: #e74c3c; font-size: 20px;")
            self.conn_status.setText("MT5 غير موجود أو مغلق.")
            self.log("MT5 غير موجود أو مغلق.")

    def toggle_master_system(self):
        if not self.is_active:
            # تنفيذ الدخول الأول (Straddle)
            symbol = self.sym_input.text()
            lot = self.lot_input.value()
            dist = self.dist_input.value()
            
            res, actual_dist, err_msg = self.logic.place_order_with_retry(symbol, lot, dist)
            if res:
                self.is_active = True
                self.btn_master_start.setText("إيقاف النظام")
                self.btn_master_start.setStyleSheet("background-color: #e74c3c; color: white; font-weight: bold; border-radius: 10px;")
                self.log(f"تم تفعيل النظام بمسافة معدلة: {actual_dist}")
                
                # تشغيل حلقة التتبع
                self.trade_thread = threading.Thread(target=self.background_loop, daemon=True)
                self.trade_thread.start()
            else:
                self.log(f"فشل في وضع الأوامر الأولية: {err_msg}")
        else:
            self.is_active = False
            self.btn_master_start.setText("بدء التداول التلقائي")
            self.btn_master_start.setStyleSheet("background-color: #27ae60; color: white; font-weight: bold; border-radius: 10px;")
            self.log("تم إيقاف النظام.")

    def background_loop(self):
        symbol = self.sym_input.text()
        while self.is_active:
            self.logic.fast_trailing_loop(symbol)
            time.sleep(0.1)

    def update_dashboard(self):
        if not mt5_call('initialize'):
            self.conn_status.setText("MT5 غير متصل.")
            self.btn_master_start.setEnabled(False)
            return
        
        symbol = self.sym_input.text()
        spread, stop_lvl = self.logic.get_broker_constraints(symbol)
        session = utils.get_market_session()
        
        self.conn_status.setText(f"الجلسة: {session} | السبريد: {round(spread,1)} | أدنى مسافة: {stop_lvl}")
        
        acc = mt5_call('account_info')
        if acc:
            self.acc_info_label.setText(f"حساب: {acc.login} | ربح: {round(acc.profit,2)} | Equity: {round(acc.equity,2)}")
        
        positions = mt5_call('positions_get')
        if positions:
            self.trade_table.setRowCount(len(positions))
            for i, p in enumerate(positions):
                self.trade_table.setItem(i, 0, QtWidgets.QTableWidgetItem(str(p.ticket)))
                self.trade_table.setItem(i, 1, QtWidgets.QTableWidgetItem(str(p.symbol)))
                self.trade_table.setItem(i, 2, QtWidgets.QTableWidgetItem("BUY" if p.type == 0 else "SELL"))
                self.trade_table.setItem(i, 3, QtWidgets.QTableWidgetItem(str(round(p.profit, 2))))
                self.trade_table.setItem(i, 4, QtWidgets.QTableWidgetItem(str(p.sl)))
        else:
            self.trade_table.setRowCount(0)
        
    def closeEvent(self, a0):
        try:
            if mt5_call('shutdown'):
                self.log("تم إغلاق اتصال MT5.")
        except Exception:
            pass
        super().closeEvent(a0)

if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    app.setStyle("Fusion")
    window = ProfessionalTraderApp()
    window.show()
    sys.exit(app.exec())
