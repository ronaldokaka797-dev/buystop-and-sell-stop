#include <iostream>
#include <cmath>

extern "C" {
    // دالة سريعة جداً لحساب تحريك الستوب لوز (Trailing Stop)
    // تعيد السعر الجديد للستوب لوز فوراً
    double calculate_fast_trailing(double current_bid, double open_price, double current_sl, double trail_points, double point_size) {
        double profit_points = (current_bid - open_price) / point_size;
        
        if (profit_points > trail_points) {
            double target_sl = current_bid - (trail_points * 0.5 * point_size);
            if (target_sl > current_sl) {
                return target_sl;
            }
        }
        return current_sl;
    }

    // دالة لحساب حجم اللوت بناءً على المخاطرة بسرعة
    double calculate_risk_lot(double balance, double risk_percent, double stop_loss_points, double tick_value) {
        if (stop_loss_points <= 0) return 0.01;
        double risk_amount = balance * (risk_percent / 100.0);
        double lot = risk_amount / (stop_loss_points * tick_value);
        return round(lot * 100) / 100.0;
    }
}
