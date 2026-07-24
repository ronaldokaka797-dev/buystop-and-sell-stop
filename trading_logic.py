import MetaTrader5 as MetaTrader5Module
import time
import ctypes
import os
from typing import Any, cast
import utils # تم إضافة الاستيراد هنا

mt5: Any = cast(Any, MetaTrader5Module)

def mt5_call(name: str, *args: Any, **kwargs: Any) -> Any:
    func = getattr(mt5, name, None)
    if callable(func):
        try:
            return func(*args, **kwargs)
        except Exception:
            return None
    return None


def mt5_order_send(request: dict) -> Any:
    try:
        return mt5.order_send(request)
    except Exception:
        return None


def mt5_last_error() -> str:
    err = mt5_call('last_error')
    if err is None:
        return 'لا توجد رسالة خطأ من MT5.'
    if hasattr(err, 'comment'):
        comment = getattr(err, 'comment', '')
        retcode = getattr(err, 'retcode', '')
        return f'{comment} ({retcode})'.strip()
    return str(err)


class TradingLogic:
    def __init__(self):
        self.loss_streak = 0
        self.is_running = False
        self.logger = utils.TradeLogger()
        
    def normalize_symbol(self, symbol):
        symbol = symbol.strip().upper()
        if not symbol:
            return None
        info = mt5_call('symbol_info', symbol)
        if info:
            return symbol
        candidates = [
            symbol,
            symbol + 'm',
            symbol + '.',
            symbol + '#',
        ]
        if 'XAU' in symbol and symbol != 'GOLD':
            candidates.append('GOLD')
        for s in candidates:
            info = mt5_call('symbol_info', s)
            if info:
                return s
        for s in mt5_call('symbols_get') or []:
            if symbol in s.name.upper():
                return s.name
        return None

    def get_broker_constraints(self, symbol):
        """ يكتشف السبريد وأقل مسافة يقبلها البروكر """
        symbol = self.normalize_symbol(symbol)
        if not symbol:
            return 0, 0
        mt5_call('symbol_select', symbol, True)
        info = mt5_call('symbol_info', symbol)
        tick = mt5_call('symbol_info_tick', symbol)
        if not info or not tick:
            return 0, 0
        
        spread = (tick.ask - tick.bid) / info.point
        stop_level = info.trade_stops_level or 0
        
        return spread, stop_level

    def place_order_with_retry(self, symbol, lot, distance):
        """ يحاول وضع الأوامر وإذا فشل بسبب القرب يبتعد قليلاً """
        if not mt5_call('initialize'):
            return None, distance, "MT5 غير مهيأ. حاول إعادة تشغيل التطبيق أو إعادة الاتصال."
        symbol = self.normalize_symbol(symbol)
        if not symbol:
            return None, distance, "الرمز غير موجود في MT5."
        if not mt5_call('symbol_select', symbol, True):
            return None, distance, "تعذر اختيار الرمز في MT5."
        info = mt5_call('symbol_info', symbol)
        tick = mt5_call('symbol_info_tick', symbol)
        if not info or not tick:
            return None, distance, "تعذر الحصول على بيانات الرمز أو السوق."
        point = info.point
        
        # التعلم من الماضي: هل هناك مسافة أفضل؟
        optimized_dist = self.logger.get_best_distance(symbol)
        if optimized_dist:
            distance = max(distance, optimized_dist)

        for attempt in range(5): # 5 محاولات لتحسين المكان
            tick = mt5_call('symbol_info_tick', symbol)
            if not tick:
                return None, distance, "تعذر تحديث بيانات الأسعار أثناء المحاولة."
            spread, stop_lvl = self.get_broker_constraints(symbol)
            
            # التأكد من أن المسافة أكبر من السبريد و الـ Stop Level بزيادة أمان
            min_allowed = spread + stop_lvl + 5 
            safe_dist = max(distance, min_allowed)
            
            buy_price = tick.ask + (safe_dist * point)
            sell_price = tick.bid - (safe_dist * point)
            
            # محاولة الإرسال
            buy_req = {
                "action": mt5.TRADE_ACTION_PENDING,
                "symbol": symbol,
                "volume": lot,
                "type": mt5.ORDER_TYPE_BUY_STOP,
                "price": buy_price,
                "sl": sell_price,
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            
            try:
                res = mt5.order_send(buy_req)
            except Exception:
                res = None
            if res is None:
                return None, distance, f"لم يعد MT5 استجابة لأمر الإرسال. {mt5_last_error()}"
            if getattr(res, 'retcode', None) == mt5.TRADE_RETCODE_DONE:
                return res, safe_dist, ""
            
            comment = getattr(res, 'comment', 'Unknown error')
            if getattr(res, 'retcode', None) in [
                mt5.TRADE_RETCODE_INVALID_STOPS,
                mt5.TRADE_RETCODE_PRICE_OFF,
                mt5.TRADE_RETCODE_INVALID_PRICE,
                mt5.TRADE_RETCODE_REQUOTE,
            ]:
                distance += 5 # زيادة المسافة والمحاولة مرة أخرى
                continue
            return None, distance, f"خطأ MT5: {comment} ({getattr(res,'retcode', 'NO_CODE')})"
        return None, distance, f"فشل بعد 5 محاولات. آخر مسافة: {distance}"

    def fast_trailing_loop(self, symbol):
        """ حلقة التتبع السريع """
        positions = mt5_call('positions_get', symbol=symbol)
        if not positions: return
        
        for pos in positions:
            tick = mt5_call('symbol_info_tick', symbol)
            point = mt5_call('symbol_info', symbol).point
            
            # منطق التتبع السريع (محاكاة لسرعة C++)
            if pos.type == mt5.POSITION_TYPE_BUY:
                if (tick.bid - pos.price_open) > 20 * point:
                    new_sl = tick.bid - 10 * point
                    if new_sl > pos.sl:
                        self.modify_sl(pos.ticket, new_sl)
            elif pos.type == mt5.POSITION_TYPE_SELL:
                if (pos.price_open - tick.ask) > 20 * point:
                    new_sl = tick.ask + 10 * point
                    if new_sl < pos.sl or pos.sl == 0:
                        self.modify_sl(pos.ticket, new_sl)

    def modify_sl(self, ticket, sl):
        req = {"action": mt5.TRADE_ACTION_SLTP, "position": ticket, "sl": sl}
        try:
            return mt5.order_send(req)
        except Exception:
            return None
