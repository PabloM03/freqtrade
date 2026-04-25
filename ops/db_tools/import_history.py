#!/usr/bin/env python3
"""
Importa los trades históricos limpios al nuevo trades.sqlite creado por freqtrade.
Solo inserta trades cerrados (is_open=0) del backup corregido.
"""
import sqlite3

SRC = "/home/ubuntu/freqtrade/trades.sqlite.clean"
DST = "/home/ubuntu/freqtrade/trades.sqlite"

src = sqlite3.connect(SRC)
dst = sqlite3.connect(DST)
dst.execute("PRAGMA foreign_keys = OFF")

src.row_factory = sqlite3.Row
src_cur = src.cursor()
dst.row_factory = sqlite3.Row
dst_cur = dst.cursor()

# Obtener columnas que existen en AMBAS tablas
src_cur.execute("PRAGMA table_info(trades)")
src_cols = {r["name"] for r in src_cur.fetchall()}
dst_cur.execute("PRAGMA table_info(trades)")
dst_cols = {r["name"] for r in dst_cur.fetchall()}
common_cols = sorted(src_cols & dst_cols)

# Leer trades cerrados del backup
src_cur.execute(f"SELECT {','.join(common_cols)} FROM trades WHERE is_open=0 ORDER BY id")
trades = src_cur.fetchall()

inserted = 0
skipped = 0
for row in trades:
    try:
        placeholders = ",".join("?" * len(common_cols))
        dst_cur.execute(
            f"INSERT OR IGNORE INTO trades ({','.join(common_cols)}) VALUES ({placeholders})",
            [row[c] for c in common_cols]
        )
        if dst_cur.rowcount:
            inserted += 1
        else:
            skipped += 1
    except Exception as e:
        print(f"  Error en trade {row['id']}: {e}")

# También importar las orders correspondientes
src_cur.execute("PRAGMA table_info(orders)")
src_order_cols = {r["name"] for r in src_cur.fetchall()}
dst_cur2 = dst.cursor()
dst_cur2.execute("PRAGMA table_info(orders)")
dst_order_cols = {r["name"] for r in dst_cur2.fetchall()}
common_order_cols = sorted(src_order_cols & dst_order_cols)

closed_ids = [row["id"] for row in trades]
if closed_ids:
    placeholders = ",".join("?" * len(closed_ids))
    src_cur.execute(
        f"SELECT {','.join(common_order_cols)} FROM orders WHERE ft_trade_id IN ({placeholders})",
        closed_ids
    )
    orders = src_cur.fetchall()
    orders_inserted = 0
    for order in orders:
        try:
            ph = ",".join("?" * len(common_order_cols))
            dst_cur.execute(
                f"INSERT OR IGNORE INTO orders ({','.join(common_order_cols)}) VALUES ({ph})",
                [order[c] for c in common_order_cols]
            )
            if dst_cur.rowcount:
                orders_inserted += 1
        except Exception as e:
            print(f"  Error en order: {e}")
    print(f"Orders importadas: {orders_inserted}")

dst.commit()
src.close()
dst.close()

print(f"Trades insertados: {inserted}, omitidos (ya existían): {skipped}")
print(f"\nVerificación:")
v = sqlite3.connect(DST)
rows = v.execute("SELECT id, pair, close_profit*100, close_profit_abs, exit_reason FROM trades WHERE is_open=0 ORDER BY id DESC LIMIT 10").fetchall()
for r in rows:
    sign = "✅" if (r[2] or 0) > 0 else "❌"
    print(f"  {sign} #{r[0]} {r[1]}: {r[2]:.2f}% (${r[3]:.2f}) [{r[4]}]")
v.close()
