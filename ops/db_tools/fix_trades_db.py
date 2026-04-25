#!/usr/bin/env python3
"""
Limpia la base de datos de trades contaminada:
- Elimina órdenes huérfanas (pares distintos al trade real)
- Recalcula close_profit y close_profit_abs usando solo las órdenes correctas
- Fee Binance: 0.001 (0.1%) por lado
"""
import sqlite3
import shutil

BACKUP = "/home/ubuntu/freqtrade/trades.sqlite.bak_20260425_135827"
OUTPUT = "/home/ubuntu/freqtrade/trades.sqlite.fixed"
FEE = 0.001  # 0.1% Binance maker fee

shutil.copy2(BACKUP, OUTPUT)
conn = sqlite3.connect(OUTPUT)
conn.execute("PRAGMA foreign_keys = OFF")
cur = conn.cursor()

# Trades cerrados con múltiples pares en orders
# Incluir is_open=1 con close_rate válido (trade cerrado pero WAL no checkpoineado al hacer backup)
cur.execute("""
    SELECT id, pair, open_rate, close_rate, stake_amount FROM trades
    WHERE is_open=0 OR (is_open=1 AND close_rate IS NOT NULL AND close_rate > 0)
""")
trades = cur.fetchall()

fixed = 0
for trade_id, pair, open_rate, close_rate, stake_amount in trades:
    # Contar cuántos pares distintos hay en orders para este trade
    cur.execute("SELECT DISTINCT ft_pair FROM orders WHERE ft_trade_id=?", (trade_id,))
    pairs_in_orders = [r[0] for r in cur.fetchall()]

    if len(pairs_in_orders) <= 1:
        continue  # trade limpio, no tocar

    print(f"\nTrade {trade_id} ({pair}): contaminado con {pairs_in_orders}")

    # Borrar órdenes que no son del par real
    cur.execute("DELETE FROM orders WHERE ft_trade_id=? AND ft_pair!=?", (trade_id, pair))
    deleted = cur.rowcount
    print(f"  → Eliminadas {deleted} órdenes de otros pares")

    # Recalcular profit solo con las órdenes del par real
    cur.execute("""
        SELECT ft_order_side, price, filled FROM orders
        WHERE ft_trade_id=? AND ft_pair=? AND status='closed' AND filled>0
    """, (trade_id, pair))
    orders = cur.fetchall()

    buy_cost = sum(price * filled for side, price, filled in orders if side == 'buy')
    sell_revenue = sum(price * filled for side, price, filled in orders if side == 'sell')

    if buy_cost <= 0:
        print(f"  ⚠️  Sin órdenes buy, usando stake_amount + open/close rate")
        buy_cost = stake_amount
        sell_revenue = stake_amount * (close_rate / open_rate)
    elif sell_revenue <= 0:
        print(f"  ⚠️  Sin órdenes sell (bot matado antes de escribir), usando buy_cost + close_rate")
        sell_revenue = buy_cost * (close_rate / open_rate)

    buy_fees = buy_cost * FEE
    sell_fees = sell_revenue * FEE
    profit_abs = sell_revenue - buy_cost - buy_fees - sell_fees

    # Denominator = stake real del trade (no suma de todas las posiciones abiertas)
    profit_pct = profit_abs / stake_amount

    print(f"  buy_cost={buy_cost:.4f}, sell_revenue={sell_revenue:.4f}")
    print(f"  profit_abs={profit_abs:.4f} USDC ({profit_pct*100:.4f}%)")

    # Actualizar trades table (también cerrar trades que quedaron is_open=1 por WAL no checkpointed)
    cur.execute("""
        UPDATE trades SET close_profit=?, close_profit_abs=?, is_open=0,
        exit_reason=COALESCE(NULLIF(exit_reason,''), 'trailing_stop_loss')
        WHERE id=?
    """, (profit_pct, profit_abs, trade_id))
    fixed += 1

conn.commit()

# Verificación final
print(f"\n{'='*60}")
print(f"Trades corregidos: {fixed}")
print(f"\nResultado final (trades cerrados):")
cur.execute("""
    SELECT id, pair, open_rate, close_rate, stake_amount,
           close_profit*100 as pct, close_profit_abs as abs_usd,
           exit_reason
    FROM trades WHERE is_open=0 ORDER BY id DESC LIMIT 15
""")
for row in cur.fetchall():
    tid, pair, op, cl, stake, pct, abs_usd, reason = row
    sign = "✅" if pct > 0 else "❌"
    print(f"  {sign} #{tid} {pair}: {pct:.2f}% (${abs_usd:.2f}) [{reason}]")

conn.close()
print(f"\nDB limpia guardada en: {OUTPUT}")
