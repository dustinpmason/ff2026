"""Score the replay against the books' closing prices."""
import sys, json, warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd
import ff_sim as fs, ff_sim_live as fl
from ff_props import norm_player
OUT=sys.argv[1]
G=pd.read_csv(f"{OUT}/graded.csv")
G=G[G.result.isin(["over","under"])].copy(); G["y"]=(G.result=="over").astype(float)
def dec(a): a=np.asarray(a,float); return np.where(a>0, 1+a/100.0, 1+100.0/np.abs(a))
P=[]
for w in sorted(G.week.unique()):
    p=pd.read_csv(f"{OUT}/replay_prices_2026_wk{w:02d}.csv"); rj=json.load(open(f"{OUT}/replay_inputs_2026_wk{w:02d}.json"))
    p["stat"]=p.market.map(lambda m: fl.MARKETS.get(m,(None,))[0]); p=p[p.stat.notna()].copy()
    p["ln"]=p.line.where(p.line.notna(), p.rung_threshold-0.5)
    for m,v in (("player_anytime_td",0.5),("player_2plus_td",1.5),("player_3plus_td",2.5)): p.loc[p.ln.isna()&(p.market==m),"ln"]=v
    g=G[G.week==w]
    ids={}                                   # (team, normalised name) -> player id, from the graded file
    for tm,pid,nm in zip(g.team,g.player_id,g.name): ids[(tm,norm_player(nm))]=pid
    ali={(a["team"],norm_player(a["name"])):a["player"] for a in rj.get("aliases",[])}
    def pid_of(r):
        n=norm_player(r.player)
        for tm in (r.away,r.home):
            if (tm,n) in ali: return ali[(tm,n)]
            if (tm,n) in ids: return ids[(tm,n)]
        return None
    p["player_id"]=[pid_of(r) for r in p.itertuples()]; p["week"]=w
    P.append(p[p.player_id.notna()])
P=pd.concat(P); P["d_over"]=dec(P.over); P["d_under"]=np.where(P.under.notna(), dec(P.under.fillna(100)), np.nan)
P=P.rename(columns={"ln":"line_"}).drop(columns=["line"]).rename(columns={"line_":"line"})
two=P[P.d_under.notna()].copy(); two["pm"]=(1/two.d_over)/((1/two.d_over)+(1/two.d_under)); two["hold"]=(1/two.d_over)+(1/two.d_under)-1
K=["week","player_id","stat","line"]
cons=two.groupby(K).agg(pm=("pm","mean"), books2=("book","nunique"), best_over=("d_over","max"), best_under=("d_under","max"), hold=("hold","mean")).reset_index()
one=P.groupby(K).agg(best_over_any=("d_over","max"), n_books=("book","nunique")).reset_index()
G=G.merge(cons,on=K,how="left").merge(one,on=K,how="left")
print(f"graded lines {len(G):,}; with a two-sided price {int(G.pm.notna().sum()):,}; with any over price {int(G.best_over_any.notna().sum()):,}; average hold on two-sided lines {two.hold.mean():.1%}")
cm=lambda x,g: fs.cluster_mean(x,g)
def show(label, x, g):
    m,se,n,k=cm(x,g); print(f"  {label:<58} n {n:>5}, {k:>2} games: {m:+.4f} (se {se:.4f}, {abs(m)/se if se else 0:.1f})")
H=G[G.headline&(G.stat!="anytime_tds")&G.pm.notna()].copy()
print(f"\nA. BOOK MAIN LINES, one per player and stat, with a two-sided closing price: {len(H):,} lines in {H.game_id.nunique()} games; over hit {H.y.mean():.1%}; market said over {H.pm.mean():.1%}; simulator said over {H.p.mean():.1%}")
bs=(H.p-H.y)**2; bm=(H.pm-H.y)**2
print(f"  Brier: simulator {bs.mean():.4f}, market {bm.mean():.4f}, coin flip 0.2500")
show("simulator minus market (plus = simulator worse)", bs-bm, H.game_id); show("simulator minus coin flip", bs-0.25, H.game_id); show("market minus coin flip", bm-0.25, H.game_id)
for wk in sorted(H.week.unique()):
    h=H[H.week==wk]; print(f"   week {wk}: n {len(h)}, simulator {((h.p-h.y)**2).mean():.4f}, market {((h.pm-h.y)**2).mean():.4f}")
# does the simulator add anything once the market's number is known?
def logit(p): p=np.clip(p,1e-4,1-1e-4); return np.log(p/(1-p))
def fit(X,y):
    b=np.zeros(X.shape[1])
    for _ in range(60):
        q=1/(1+np.exp(-X@b)); Wt=q*(1-q); b=b+np.linalg.solve((X*Wt[:,None]).T@X+1e-9*np.eye(X.shape[1]), X.T@(y-q))
    return b
def reg(D, pm_col, label):
    X=np.c_[np.ones(len(D)), logit(D[pm_col].to_numpy()), logit(D.p.to_numpy())]; y=D.y.to_numpy(); b=fit(X,y)
    g=pd.factorize(D.game_id)[0]; idx=[np.flatnonzero(g==k) for k in range(g.max()+1)]; rng=np.random.default_rng(0); bb=[]
    for _ in range(300):
        pick=np.concatenate([idx[k] for k in rng.integers(0,len(idx),len(idx))]); bb.append(fit(X[pick],y[pick]))
    se=np.std(bb,axis=0)
    print(f"  {label}: weight on the market {b[1]:+.2f} (se {se[1]:.2f}); weight on the simulator {b[2]:+.2f} (se {se[2]:.2f})   [1 and 0 = the simulator adds nothing]")
reg(H,"pm","main lines")
print("\nB. WHAT THE SIMULATOR'S LEAN WAS WORTH on those main lines (side it favoured; bet at the best of the three books)")
H["fav_over"]=H.p>=0.5; H["ps"]=np.where(H.fav_over,H.p,1-H.p); H["hit"]=np.where(H.fav_over,H.y,1-H.y); H["pms"]=np.where(H.fav_over,H.pm,1-H.pm)
H["d"]=np.where(H.fav_over,H.best_over,H.best_under); H["profit"]=H.hit*(H.d-1)-(1-H.hit)
print(f"  {'simulator said':<22}{'lines':>6}{'games':>6}{'it said':>9}{'market said':>12}{'happened':>10}{'return per $1':>15}{'(se)':>8}")
for lo,hi in ((0.5,0.55),(0.55,0.60),(0.60,0.65),(0.65,0.70),(0.70,1.01),(0.60,1.01),(0.65,1.01)):
    d=H[(H.ps>=lo)&(H.ps<hi)]
    if len(d)<5: continue
    m,se,n,k=cm(d.profit,d.game_id); print(f"  {f'{lo:.0%} to {min(hi,1):.0%}':<22}{n:>6}{k:>6}{d.ps.mean():>9.1%}{d.pms.mean():>12.1%}{d.hit.mean():>10.1%}{m:>+15.3f}{se:>8.3f}")
for side,mask in (("OVERS it favoured",H.fav_over),("UNDERS it favoured",~H.fav_over)):
    d=H[mask&(H.ps>=0.60)]; m,se,n,k=cm(d.profit,d.game_id); print(f"  {side+', 60%+':<22}{n:>6}{k:>6}{d.ps.mean():>9.1%}{d.pms.mean():>12.1%}{d.hit.mean():>10.1%}{m:>+15.3f}{se:>8.3f}")
d=H[(H.ps*H.d>=1.05)]; m,se,n,k=cm(d.profit,d.game_id); print(f"  {'its own edge 5%+':<22}{n:>6}{k:>6}{d.ps.mean():>9.1%}{d.pms.mean():>12.1%}{d.hit.mean():>10.1%}{m:>+15.3f}{se:>8.3f}")
d=H; m,se,n,k=cm(np.where(H.y==1,H.best_over-1,-1.0),H.game_id); print(f"  for reference, every OVER: return {m:+.3f} (se {se:.3f});", end=" "); m,se,n,k=cm(np.where(H.y==0,H.best_under-1,-1.0),H.game_id); print(f"every UNDER: {m:+.3f} (se {se:.3f})")
print("\nC. LADDER OVERS (alternate lines and N+ rungs with a closing price), one rung per player and stat")
L=G[(G.stat!="anytime_tds")&~G.headline&G.best_over_any.notna()].copy(); L["q"]=1/L.best_over_any; L["edge"]=L.p*L.best_over_any-1; L["profit"]=L.y*(L.best_over_any-1)-(1-L.y)
print(f"  {len(L):,} priced rungs; simulator said {L.p.mean():.1%}, price implied {L.q.mean():.1%} (with the book's margin), happened {L.y.mean():.1%}")
reg(L.assign(pm=L.q.clip(0.01,0.99)),"pm","all priced rungs (market = the price's implied chance, margin included)")
print(f"  {'rule':<46}{'bets':>6}{'games':>6}{'it said':>9}{'price said':>11}{'happened':>10}{'return per $1':>15}{'(se)':>8}")
for label,mask in (("simulator 70%+, any price",L.p>=0.70),("simulator 70%+ and its own edge 5%+",(L.p>=0.70)&(L.edge>=0.05)),("simulator 80%+ and its own edge 5%+",(L.p>=0.80)&(L.edge>=0.05)),("simulator 60-80% and its own edge 5%+",(L.p>=0.60)&(L.p<0.80)&(L.edge>=0.05)),("its own edge 10%+ (any chance)",L.edge>=0.10)):
    d=L[mask].sort_values("edge",ascending=False).drop_duplicates(["week","player_id","stat"])
    if len(d)<5: print(f"  {label:<46} too few"); continue
    m,se,n,k=cm(d.profit,d.game_id); print(f"  {label:<46}{n:>6}{k:>6}{d.p.mean():>9.1%}{d.q.mean():>11.1%}{d.y.mean():>10.1%}{m:>+15.3f}{se:>8.3f}")
d=L.sort_values("p",ascending=False).drop_duplicates(["week","player_id","stat"]); m,se,n,k=cm(d.profit,d.game_id); print(f"  for reference, the safest rung of every ladder: {n} bets, happened {d.y.mean():.1%}, return {m:+.3f} (se {se:.3f})")
print("\nD. ANYTIME TOUCHDOWN (yes price only)")
T=G[(G.stat=="anytime_tds")&(G.line==0.5)&G.best_over_any.notna()].copy(); T["q"]=1/T.best_over_any; T["edge"]=T.p*T.best_over_any-1; T["profit"]=T.y*(T.best_over_any-1)-(1-T.y)
print(f"  {len(T):,} players; simulator said {T.p.mean():.1%}, price implied {T.q.mean():.1%}, scored {T.y.mean():.1%}")
reg(T.assign(pm=T.q.clip(0.01,0.99)),"pm","anytime touchdown")
for label,mask in (("every posted player",T.p>=0),("simulator 30%+",T.p>=0.30),("its own edge 5%+",T.edge>=0.05),("its own edge 5%+ and simulator 25%+",(T.edge>=0.05)&(T.p>=0.25)),("its own edge 20%+",T.edge>=0.20)):
    d=T[mask]
    if len(d)<5: print(f"  {label:<40} too few"); continue
    m,se,n,k=cm(d.profit,d.game_id); print(f"  {label:<40}{n:>5} bets {k:>3} games: it said {d.p.mean():.1%}, price said {d.q.mean():.1%}, scored {d.y.mean():.1%}, return {m:+.3f} (se {se:.3f})")
G.to_csv(f"{OUT}/graded_priced.csv",index=False)
