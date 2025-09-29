import json, re, sys, io, os
if len(sys.argv) != 3:
    print("Uso: json_sanitize.py origen.json destino.json", file=sys.stderr); sys.exit(2)
src, dst = sys.argv[1], sys.argv[2]

with io.open(src, "r", encoding="utf-8", errors="replace") as f:
    raw = f.read()

# 1) Normaliza
raw = raw.lstrip("\ufeff").replace("\r", "")
# Quita caracteres de control (excepto \n \t)
raw = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F]', '', raw)

# 2) Quita comentarios // solo fuera de strings
out, i, in_str, esc = [], 0, False, False
while i < len(raw):
    c = raw[i]
    if in_str:
        out.append(c)
        if esc: esc = False
        elif c == '\\': esc = True
        elif c == '"': in_str = False
        i += 1
    else:
        if c == '"':
            in_str = True; out.append(c); i += 1
        elif c == '/' and i+1 < len(raw) and raw[i+1] == '/':
            j = raw.find('\n', i)
            i = len(raw) if j == -1 else j
        else:
            out.append(c); i += 1

clean = ''.join(out)

# 3) Quita comas colgantes antes de } o ] (fuera de strings)
tmp, in_str, esc = [], False, False
for ch in clean:
    if in_str:
        tmp.append(ch)
        if esc: esc = False
        elif ch == '\\': esc = True
        elif ch == '"': in_str = False
    else:
        if ch == '"':
            in_str = True; tmp.append(ch)
        elif ch in '}]':
            k = len(tmp)-1
            while k >= 0 and tmp[k].isspace(): k -= 1
            if k >= 0 and tmp[k] == ',': del tmp[k]
            tmp.append(ch)
        else:
            tmp.append(ch)

clean2 = ''.join(tmp)

# 4) Valida JSON y escribe formateado
cfg = json.loads(clean2)
os.makedirs(os.path.dirname(dst), exist_ok=True)
with io.open(dst, "w", encoding="utf-8") as f:
    json.dump(cfg, f, ensure_ascii=False, indent=2)
print("OK", "exchange" in cfg, "strategy" in cfg)
