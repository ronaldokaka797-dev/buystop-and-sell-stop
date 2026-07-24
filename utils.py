import datetime
import pandas as pd
import os

def get_market_session():
    """ يحدد جلسة السوق الحالية بناءً على توقيت غرينتش """
    now_utc = datetime.datetime.now(datetime.timezone.utc).hour
    if 8 <= now_utc < 16: return "London"
    if 13 <= now_utc < 21: return "New York"
    if 0 <= now_utc < 7: return "Tokyo"
    return "Sideways/Late"

class TradeLogger:
    """ نظام تخزين وتعلم من الصفقات """
    def __init__(self, filename="trade_history.csv"):
        self.filename = filename
        if not os.path.exists(self.filename):
            df = pd.DataFrame(columns=["time", "symbol", "session", "distance", "result", "profit"])
            df.to_csv(self.filename, index=False)

    def log_trade(self, symbol, session, distance, result, profit):
        df = pd.read_csv(self.filename)
        new_row = {"time": datetime.datetime.now(), "symbol": symbol, 
                   "session": session, "distance": distance, 
                   "result": result, "profit": profit}
        df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
        df.to_csv(self.filename, index=False)

    def get_best_distance(self, symbol):
        """ يحلل الصفقات السابقة ليعطي أفضل مسافة ربحية """
        try:
            df = pd.read_csv(self.filename)
            symbol_df = df[df['symbol'] == symbol]
            if len(symbol_df) < 5: return None # يحتاج 5 صفقات على الأقل ليتعلم
            
            # اختيار المسافة التي حققت أعلى معدل ربح
            best = symbol_df.groupby('distance')['profit'].mean().idxmax()
            return int(best)
        except:
            return None
