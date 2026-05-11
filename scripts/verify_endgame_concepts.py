import sys
import yaml
import chess

data = yaml.safe_load(open("config/knowledge/endgame_concepts.yaml", encoding="utf-8"))
failures = 0
for concept in data:
    cid = concept["id"]
    for i, pos in enumerate(concept["positions"], 1):
        fen = pos["fen"]
        try:
            board = chess.Board(fen)
            if not board.is_valid():
                raise ValueError(f"board.is_valid()=False: {board.status()!r}")
        except Exception as e:
            print(f"FAIL  {cid:30s} pos {i}: {fen!r} ({e})")
            failures += 1
            continue
        print(f"OK    {cid:30s} pos {i} ({len(board.piece_map())} pieces)")
print(f"\n{sum(len(c['positions']) for c in data) - failures}/"
      f"{sum(len(c['positions']) for c in data)} positions verified")
sys.exit(0 if failures == 0 else 1)
