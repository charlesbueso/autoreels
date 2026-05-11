import sys
import yaml
import chess

data = yaml.safe_load(open("config/knowledge/opening_traps.yaml", encoding="utf-8"))
failures = 0
for t in data:
    b = chess.Board()
    ok = True
    for i, san in enumerate(t["pgn"], 1):
        try:
            b.push_san(san)
        except Exception as e:
            print(f"FAIL  {t['id']:25s} ply {i} '{san}': {e}")
            ok = False
            failures += 1
            break
    if ok:
        plies = len(t["pgn"])
        print(f"OK    {t['id']:25s} {plies} plies")
print(f"\n{len(data) - failures}/{len(data)} verified")
sys.exit(0 if failures == 0 else 1)
