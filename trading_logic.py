import MetaTrader5 as MetaTrader5Module
from typing import Any, cast

import utils

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
        """يكتشف السبريد وأقل مسافة يقبلها البروكر."""
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

    def _round_price(self, value: float, digits: int) -> float:
        return round(float(value), int(digits))

    def _success_retcodes(self) -> set[int]:
        retcodes = set()
        for name in ('TRADE_RETCODE_DONE', 'TRADE_RETCODE_PLACED'):
            value = getattr(mt5, name, None)
            if isinstance(value, int):
                retcodes.add(value)
        return retcodes

    def _retry_retcodes(self) -> set[int]:
        retcodes = set()
        for name in (
            'TRADE_RETCODE_INVALID_STOPS',
            'TRADE_RETCODE_PRICE_OFF',
            'TRADE_RETCODE_INVALID_PRICE',
            'TRADE_RETCODE_REQUOTE',
        ):
            value = getattr(mt5, name, None)
            if isinstance(value, int):
                retcodes.add(value)
        return retcodes

    def _is_success_result(self, result: Any) -> bool:
        return result is not None and getattr(result, 'retcode', None) in self._success_retcodes()

    def _is_retryable_result(self, result: Any) -> bool:
        return result is not None and getattr(result, 'retcode', None) in self._retry_retcodes()

    def _get_pending_filling_type(self) -> Any:
        """أوامر الـ Stop المعلقة تعمل غالباً مع RETURN أكثر من IOC."""
        for name in ('ORDER_FILLING_RETURN', 'ORDER_FILLING_IOC', 'ORDER_FILLING_FOK'):
            value = getattr(mt5, name, None)
            if value is not None:
                return value
        return None

    def _build_pending_request(self, symbol, lot, order_type, price, sl, filling_type):
        request = {
            'action': mt5.TRADE_ACTION_PENDING,
            'symbol': symbol,
            'volume': lot,
            'type': order_type,
            'price': price,
            'sl': sl,
            'type_time': mt5.ORDER_TIME_GTC,
            'comment': 'Arena Straddle',
        }
        if filling_type is not None:
            request['type_filling'] = filling_type
        return request

    def _remove_pending_order(self, order_ticket):
        if not order_ticket:
            return None
        request = {
            'action': mt5.TRADE_ACTION_REMOVE,
            'order': int(order_ticket),
        }
        return mt5_order_send(request)

    def place_order_with_retry(self, symbol, lot, distance):
        """يضع Buy Stop و Sell Stop مع إعادة المحاولة إذا كانت المسافة غير مقبولة."""
        if not mt5_call('initialize'):
            return None, distance, 'MT5 غير مهيأ. حاول إعادة تشغيل التطبيق أو إعادة الاتصال.'

        symbol = self.normalize_symbol(symbol)
        if not symbol:
            return None, distance, 'الرمز غير موجود في MT5.'
        if not mt5_call('symbol_select', symbol, True):
            return None, distance, 'تعذر اختيار الرمز في MT5.'

        info = mt5_call('symbol_info', symbol)
        tick = mt5_call('symbol_info_tick', symbol)
        if not info or not tick:
            return None, distance, 'تعذر الحصول على بيانات الرمز أو السوق.'

        point = info.point
        digits = info.digits
        filling_type = self._get_pending_filling_type()

        optimized_dist = self.logger.get_best_distance(symbol)
        if optimized_dist:
            distance = max(float(distance), float(optimized_dist))

        for _ in range(5):
            tick = mt5_call('symbol_info_tick', symbol)
            if not tick:
                return None, distance, 'تعذر تحديث بيانات الأسعار أثناء المحاولة.'

            spread, stop_lvl = self.get_broker_constraints(symbol)
            min_allowed = float(spread) + float(stop_lvl) + 5.0
            safe_dist = max(float(distance), min_allowed)

            buy_price = self._round_price(tick.ask + (safe_dist * point), digits)
            sell_price = self._round_price(tick.bid - (safe_dist * point), digits)

            buy_req = self._build_pending_request(
                symbol=symbol,
                lot=lot,
                order_type=mt5.ORDER_TYPE_BUY_STOP,
                price=buy_price,
                sl=sell_price,
                filling_type=filling_type,
            )
            sell_req = self._build_pending_request(
                symbol=symbol,
                lot=lot,
                order_type=mt5.ORDER_TYPE_SELL_STOP,
                price=sell_price,
                sl=buy_price,
                filling_type=filling_type,
            )

            buy_res = mt5_order_send(buy_req)
            if buy_res is None:
                return None, safe_dist, f'لم يعد MT5 استجابة لأمر Buy Stop. {mt5_last_error()}'
            if self._is_retryable_result(buy_res):
                distance = safe_dist + 5
                continue
            if not self._is_success_result(buy_res):
                comment = getattr(buy_res, 'comment', 'Unknown error')
                return None, safe_dist, f'فشل Buy Stop: {comment} ({getattr(buy_res, "retcode", "NO_CODE")})'

            sell_res = mt5_order_send(sell_req)
            if sell_res is None:
                self._remove_pending_order(getattr(buy_res, 'order', 0))
                return None, safe_dist, f'لم يعد MT5 استجابة لأمر Sell Stop. {mt5_last_error()}'
            if self._is_retryable_result(sell_res):
                self._remove_pending_order(getattr(buy_res, 'order', 0))
                distance = safe_dist + 5
                continue
            if not self._is_success_result(sell_res):
                self._remove_pending_order(getattr(buy_res, 'order', 0))
                comment = getattr(sell_res, 'comment', 'Unknown error')
                return None, safe_dist, f'فشل Sell Stop: {comment} ({getattr(sell_res, "retcode", "NO_CODE")})'

            return {
                'symbol': symbol,
                'buy': buy_res,
                'sell': sell_res,
            }, safe_dist, ''

        return None, distance, f'فشل بعد 5 محاولات. آخر مسافة مجرّبة: {distance}'

    def fast_trailing_loop(self, symbol):
        """حلقة التتبع السريع."""
        symbol = self.normalize_symbol(symbol)
        if not symbol:
            return

        positions = mt5_call('positions_get', symbol=symbol)
        if not positions:
            return

        info = mt5_call('symbol_info', symbol)
        if not info:
            return
        point = info.point

        for pos in positions:
            tick = mt5_call('symbol_info_tick', symbol)
            if not tick:
                continue

            current_sl = pos.sl or 0.0
            if pos.type == mt5.POSITION_TYPE_BUY:
                if (tick.bid - pos.price_open) > 20 * point:
                    new_sl = tick.bid - 10 * point
                    if new_sl > current_sl:
                        self.modify_sl(pos.ticket, new_sl)
            elif pos.type == mt5.POSITION_TYPE_SELL:
                if (pos.price_open - tick.ask) > 20 * point:
                    new_sl = tick.ask + 10 * point
                    if new_sl < current_sl or current_sl == 0:
                        self.modify_sl(pos.ticket, new_sl)

    def modify_sl(self, ticket, sl):
        req = {'action': mt5.TRADE_ACTION_SLTP, 'position': ticket, 'sl': sl}
        try:
            return mt5.order_send(req)
        except Exception:
            return None
