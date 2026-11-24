"""Replay a finished week through the live simulator on the books' real closing lines.
The model sees only games before the week. Everything handed in comes from what the books
posted before kickoff: who has a passing line (the starter), who is posted but not on the
slate (added), and who is posted in another team's game (moved; chance 0 for the old team).
No status or chance from any other source. Usage: replay.py <week> <odds folder> <out folder>"""
import sys, glob, json, warnings; warnings.filterwarnings("ignore")
import pandas as pd
import ff_data, ff_sim as fs, ff_sim_live as fl
from ff_props import flatten_odds, norm_player
from ff_sim_play import load_reports
from sim_record import RECORD
YEARS=(2023,2024,2025,2026); SEASON=2026; WEEK=int(sys.argv[1]); T=SEASON*100+WEEK
ODDS, OUT = sys.argv[2], sys.argv[3]
frame=fs.load_frame(YEARS); roster=ff_data.load_roster(SEASON); reports=load_reports(YEARS)
past=frame[frame.t<T]; hist=fs.History(past,T); names=fl.Names(roster,hist,SEASON)
PULLED=[]; OUT_OF={}
def live_only(e):
    """Keep only what was on the board at the close: an outcome with a closing price. A line a
    book pulled before kickoff (a player ruled out) has none. An over/under left with one side
    is dropped too."""
    kept=dropped=0
    kick=pd.Timestamp(e["commence_time"]); last={}
    for bk in e["bookmakers"]:          # when each player's prices last moved, any book
        for m in bk["markets"]:
            for o in m["outcomes"]:
                if o.get("price") is not None and o.get("closing_at"):
                    n=norm_player(o.get("description") or o["name"])
                    last[n]=min(last.get(n,1e9),(kick-pd.Timestamp(o["closing_at"])).total_seconds()/3600)
    pulled={n for n,h in last.items() if h>1.0}      # no price moved in the last hour: off the board (measured: 3% of these played)
    PULLED.extend(sorted(pulled))
    real=set()
    for bk in e["bookmakers"]:
        for m in bk["markets"]:
            if not m["key"].endswith("_td"):
                real.update(norm_player(o.get("description") or o["name"]) for o in m["outcomes"] if o.get("price") is not None)
    for tm in (fl.TEAM_CODE[e["away_team"]],fl.TEAM_CODE[e["home_team"]]):
        OUT_OF[tm]=pulled & real      # had yardage lines, and they were pulled: ruled out (0 of 21 such players played)
    for bk in e["bookmakers"]:
        mk=[]
        for m in bk["markets"]:
            oc=[o for o in m["outcomes"] if o.get("price") is not None
                and norm_player(o.get("description") or o["name"]) not in pulled]
            dropped+=len(m["outcomes"])-len(oc)
            sides={o["name"] for o in oc}
            if oc and not (sides=={"Over"} or sides=={"Under"}):
                mk.append({**m,"outcomes":oc}); kept+=len(oc)
            else: dropped+=len(oc)
        bk["markets"]=mk
    return e,kept,dropped
files=sorted(glob.glob(f"{ODDS}/wk{WEEK:02d}_*.json")); events=[]; K=D=0
for f in files:
    e,k,d=live_only(fl.read_odds(f)); events.append(e); K+=k; D+=d
quotes={}; log=[]
for e in events:
    a,h=fl.TEAM_CODE[e["away_team"]],fl.TEAM_CODE[e["home_team"]]
    quotes[(a,h)]=[q for q in flatten_odds(e,line_type="") if not fl.NOT_A_PLAYER.search(str(q["player"]).strip())]
# 1. starters: the quarterback with a posted passing-yards line
starters={}
for (a,h),qs in quotes.items():
    posted={}
    for q in qs:      # a passing-yards MAIN line with a closing price
        if q["market"]=="player_pass_yds" and q["line_type"]=="main" and q.get("over") is not None and q["over"]==q["over"]:
            posted[norm_player(q["player"])]=posted.get(norm_player(q["player"]),0)+1
    for tm in (a,h):
        cands={g for n in posted for g in names.by_name.get((tm,n),()) if (names.position.get(g) or hist.last_position(g))=="QB"}
        last=hist.last_starting_qb(tm)
        if len(cands)==1:
            starters[tm]=next(iter(cands))
            if starters[tm]!=last: log.append(f"starter {tm}: {names.full.get(starters[tm])} has the passing line (last game's starter was {hist.last_name(last) if last else None})")
        else:
            starters[tm]=last; log.append(f"starter {tm}: {len(cands)} posted quarterbacks found, kept last game's starter {hist.last_name(last)}")
# aliases: a posted name nobody on either team has, read as the one player on those teams
# with the same last name and a first name starting the same way (Cameron/Cam, Chigoziem/Chig)
KNOWN={"zonovan knight":"bam knight","hollywood brown":"marquise brown","drew ogletree":"andrew ogletree"}
SUFFIX={"jr","sr","ii","iii","iv","v"}
def parts(n):
    t=[x for x in n.replace(".","").replace("'","").split() if x not in SUFFIX]
    return (t[0], t[-1]) if len(t)>=2 else (n,"")
aliases=[]
for (a,h),qs in quotes.items():
    have={}
    for tm in (a,h):
        for (t_,n_),ids in names.by_name.items():
            if t_==tm: have.setdefault(n_,set()).update((tm,g) for g in ids)
    for book_name in sorted({q["player"] for q in qs}):
        n=norm_player(book_name)
        if n in have: continue
        f,l=parts(n)
        hits={(tm,g) for n_,v in have.items() for tm,g in v
              if n_==KNOWN.get(n) or (parts(n_)[1]==l and l and (parts(n_)[0][:3]==f[:3]))}
        if len(hits)==1:
            tm,g=next(iter(hits)); aliases.append({"team":tm,"name":book_name,"player":g}); log.append(f"alias: the books' {book_name!r} read as {names.full.get(g,g)} ({tm})")
        else: log.append(f"no alias found for {book_name!r} in {a} at {h} ({len(hits)} candidates)")
def run(add, chances):
    inp=fl.read_inputs({"season":SEASON,"week":WEEK,"starters":starters,"add":add,"chances":chances,"aliases":aliases})
    return fl.run_live(past,reports,roster,events,inp,week=WEEK)
b=run([],[])
# 2. moved: a slate player whose name is posted in a game his slate team is not in
where={}
for (a,h),qs in quotes.items():
    for n in {norm_player(q["player"]) for q in qs}: where.setdefault(n,set()).add((a,h))
chances=[]
for tm,pid,nm in zip(b.slate.team,b.slate.player_id,b.slate.name):
    n=norm_player(nm); games=where.get(n,set())
    if games and len(names.any_name.get(n,()))==1 and not any(tm in g for g in games):
        chances.append({"team":tm,"player":pid,"chance":0.0}); log.append(f"moved: {nm} is on {tm}'s slate and posted in {sorted(games)}: chance 0 for {tm}")
# 2b. ruled out: on the slate, and his yardage lines were pulled before kickoff
for tm,pid,nm in zip(b.slate.team,b.slate.player_id,b.slate.name):
    if norm_player(nm) in OUT_OF.get(tm,()) and not any(c["team"]==tm and c["player"]==pid for c in chances):
        chances.append({"team":tm,"player":pid,"chance":0.0}); log.append(f"ruled out: {nm} ({tm}), his lines were pulled before kickoff: chance 0")
# 3. added: posted with a yardage, catches or carries line, and not on his team's slate
add=[]
for rnd in range(3):
    new=[]
    for tm,who in b.off_slate.items():
        game=next(g for g in quotes if tm in g)
        for full in who:
            n=norm_player(full)
            if (tm,n) in {(x["team"],norm_player(x["player"])) for x in add}: continue
            real=[q for q in quotes[game] if norm_player(q["player"])==n and not q["market"].endswith("_td")]
            if not real: log.append(f"left off: {full} ({tm}) is posted for touchdowns only"); continue
            try: pid=names.find(tm,full,anywhere=True)
            except fl.Missing as e: log.append(f"could not add {full} ({tm}): {e}"); continue
            pos=names.position.get(pid) or hist.last_position(pid)
            if pos not in fl.ADD_AT: log.append(f"could not add {full} ({tm}): position {pos}"); continue
            new.append({"team":tm,"player":pid,"position":pos}); log.append(f"added: {full} ({tm}, {pos}), {len(real)} posted lines")
    if not new and rnd>0: break
    add+=new
    b=run(add,chances)
    if not new: break
out=fl.to_csv(b,RECORD,SEASON,WEEK); out.to_csv(f"{OUT}/shadow_{SEASON}_wk{WEEK:02d}.csv",index=False)
rows=[]
for (a,h),qs in quotes.items():
    for q in qs: rows.append({"away":a,"home":h,**{k:q.get(k) for k in ("book","market","player","line","rung_threshold","line_type","over","under")}})
pd.DataFrame(rows).to_csv(f"{OUT}/prices_{SEASON}_wk{WEEK:02d}.csv",index=False)
json.dump({"pulled":PULLED,"starters":starters,"add":add,"chances":chances,"aliases":aliases,"log":log,"unmatched":[list(u) for u in b.unmatched],"notes":b.notes},open(f"{OUT}/replay_wk{WEEK:02d}.json","w"),indent=1)
print(f"outcomes on the board at the close: {K:,}; pulled before kickoff and left out: {D:,} ({len(PULLED)} players whose prices stopped moving over an hour before kickoff)")
print(f"week {WEEK}: {len(events)} games, {len(out):,} lines priced, {len(rows):,} prices; starters changed {sum('has the passing line' in l for l in log)}, moved {sum(l.startswith('moved') for l in log)}, ruled out {sum(l.startswith('ruled out') for l in log)}, added {len(add)}, not priced {len(b.unmatched)} names")
print("matched:", out.matched.value_counts().to_dict(), "| too-high lines:", int(out.cautions.fillna('').str.contains('too high if').sum()))
for l in log:
    if not l.startswith("left off"): print("  ", l)
print("NOT PRICED with 10+ lines:"); [print("  ",u[0],"|",u[1],"|",u[2],"lines |",u[3][:110]) for u in b.unmatched if u[2]>=10]
