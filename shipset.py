#!/usr/bin/env python3
"""Which files must be committed TOGETHER with the ones you changed?

B100. The repo is updated by uploading files one at a time, so a partial
commit is the normal failure. On 2026-11-06 `ff_boost.py` was shipped with
a caption saying "ff_props.py and ff_boost.py must be committed together"
and `ff_props.py` was not attached — three sessions in a row then ran
against a torn clone, one of them misdiagnosing three functions as missing
and building a shim around an absence that was not there.

Detection was never the problem after B99; the problem was a hand-written
list of files. This computes it.

    python3 shipset.py ff_boost.py            # what must ship with it
    python3 shipset.py --changed <iso-date>   # everything newer than a time
"""
import ast
import pathlib
import sys


def deps(root: pathlib.Path) -> dict[str, set[str]]:
    """module -> the ff_* modules it imports FROM."""
    out: dict[str, set[str]] = {}
    for p in sorted(root.glob("ff_*.py")):
        try:
            tree = ast.parse(p.read_text())
        except SyntaxError:
            continue
        out[p.stem] = {
            n.module for n in ast.walk(tree)
            if isinstance(n, ast.ImportFrom)
            and n.module and n.module.startswith("ff_")}
    return out


def closure(mods: set[str], graph: dict[str, set[str]],
            deep: bool = False) -> set[str]:
    """Modules directly coupled to `mods`, in BOTH directions.

    Both directions matter. Ship a module without what it imports and it
    fails to import; ship it without its importers and they run against a
    stale copy of it — which is how a moved symbol produced the cryptic
    half-updated state this exists to prevent.

    ONE HOP by default. The full transitive closure over a seven-module
    repo is just "all of them", which is not advice. Pass deep=True if you
    want it anyway.
    """
    seen, frontier = set(mods), set(mods)
    while frontier:
        nxt: set[str] = set()
        for m in frontier:
            nxt |= graph.get(m, set())                       # it imports
            nxt |= {k for k, v in graph.items() if m in v}   # imports it
        nxt -= seen
        seen |= nxt
        frontier = nxt if deep else set()
    return seen


def main() -> None:
    root = pathlib.Path(__file__).resolve().parent
    g = deps(root)
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        print("modules found:", ", ".join(sorted(g)))
        return
    if args[0] == "--changed":
        import datetime
        cut = datetime.datetime.fromisoformat(args[1]).timestamp()
        seeds = {p.stem for p in root.glob("ff_*.py")
                 if p.stat().st_mtime > cut}
        print(f"changed since {args[1]}: {', '.join(sorted(seeds)) or 'none'}")
    else:
        seeds = {pathlib.Path(a).stem for a in args}
    full = closure(seeds, g, deep="--deep" in args)
    extra = sorted(full - seeds)
    print(f"\nSEEDS   : {', '.join(sorted(seeds))}")
    print(f"MUST ALSO SHIP: {', '.join(extra) if extra else '(nothing)'}")
    print(f"\nfull set: {' '.join(sorted(m + '.py' for m in full))}")
    if extra:
        print("\nWhy, per module:")
        for m in extra:
            why = []
            for s in sorted(seeds):
                if s in g.get(m, set()):
                    why.append(f"imports from {s}")
                if m in g.get(s, set()):
                    why.append(f"{s} imports from it")
            print(f"  {m}: {'; '.join(dict.fromkeys(why))}")


if __name__ == "__main__":
    main()
