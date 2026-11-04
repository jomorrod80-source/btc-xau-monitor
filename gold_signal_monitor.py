import json, os, time, urllib.request
from pathlib import Path

BASE="https://contract.mexc.com"
STATE=Path("gold_state.json")
OWNER="jomorrod80-source"
REPO="btc-xau-monitor"
H=3600

def get_json(url, method="GET", data=None, headers=None):
    body=None
    h={"User-Agent":"gold-monitor/1.0"}
    if headers: h.update(headers)
    if data is not None:
        body=json.dumps(data).encode()
        h["Content-Type"]="application/json"
    req=urllib.request.Request(url,data=body,headers=h,method=method)
    with urllib.request.urlopen(req,timeout=20) as r:
        return json.loads(r.read().decode())

def mexc(path):
    j=get_json(BASE+path)
    return j["data"]

def gh(path,method="GET",data=None):
    token=os.environ["GITHUB_TOKEN"]
    return get_json(
        f"https://api.github.com/repos/{OWNER}/{REPO}{path}",
        method,data,
        {"Authorization":f"Bearer {token}","Accept":"application/vnd.github+json"}
    )

def load():
    return json.loads(STATE.read_text()) if STATE.exists() else {"status":"IDLE"}

def save(s):
    STATE.write_text(json.dumps(s,indent=2,sort_keys=True)+"\n")

def sma(a,p,i):
    return sum(a[i-p+1:i+1])/p

def gann(h,l,c,p=5):
    g=None
    for i in range(p,len(c)):
        if c[i]>sma(h,p,i-1): g=sma(l,p,i)
        elif c[i]<sma(l,p,i-1): g=sma(h,p,i)
    return g

def atr(h,l,c,p,i):
    return sum(max(h[k]-l[k],abs(h[k]-c[k-1]),abs(l[k]-c[k-1])) for k in range(i-p+1,i+1))/p

def fmt(x): return f"{x:.2f}"

def create_issue(entry,stop,tp1,tp2):
    title=f"[ORO] ENTRADA {fmt(entry)} | SL {fmt(stop)} | TP1 {fmt(tp1)} | TP2 {fmt(tp2)}"
    body=f"ENTRADA: {fmt(entry)}\nSTOP LOSS: {fmt(stop)}\nTAKE PROFIT 1: {fmt(tp1)}\nTAKE PROFIT 2: {fmt(tp2)}"
    return gh("/issues","POST",{"title":title,"body":body,"assignees":[OWNER]})["number"]

def close_issue(n,reason,price,entry):
    if not n: return
    gh(f"/issues/{n}/comments","POST",{"body":f"@{OWNER}\n\nSALIDA\nMotivo: {reason}\nEntrada: {fmt(entry)}\nSalida: {fmt(price)}"})
    gh(f"/issues/{n}","PATCH",{"state":"closed"})

def clear(s,hour):
    s.update({"status":"IDLE","setup_time":None,"pending_level":None,"pending_expires_at":None,
              "entry_time":None,"entry_price":None,"stop_loss":None,"tp1":None,"tp2":None,
              "exit_due_at":None,"issue_number":None,"last_hour_key":hour})

def main():
    now=int(time.time())
    hour=(now//H)*H
    start=now-180*H
    d=mexc(f"/api/v1/contract/kline/XAU_USDT?interval=Min60&start={start}&end={now}")
    t=[int(float(x)) for x in d["time"]]
    h=[float(x) for x in d["high"]]
    l=[float(x) for x in d["low"]]
    c=[float(x) for x in d["close"]]
    closed=[i for i,x in enumerate(t) if x+H<=now]
    i=closed[-1]
    price=float(mexc("/api/v1/contract/ticker?symbol=XAU_USDT")["lastPrice"])
    s=load()

    if s.get("status")=="OPEN":
        if price<=float(s["stop_loss"]):
            close_issue(s.get("issue_number"),"STOP LOSS",float(s["stop_loss"]),float(s["entry_price"]))
            clear(s,hour); save(s); print("EXIT_STOP"); return
        if now>=int(s["exit_due_at"]):
            close_issue(s.get("issue_number"),"FIN 5 HORAS",price,float(s["entry_price"]))
            clear(s,hour); save(s); print("EXIT_TIME"); return
        save(s); print("OPEN"); return

    if s.get("status")=="PENDING":
        if now>=int(s["pending_expires_at"]):
            clear(s,hour); save(s); print("EXPIRED"); return
        level=float(s["pending_level"])
        if price>=level:
            a=atr(h,l,c,95,i); stop=level-a; r=level-stop; tp1=level+r; tp2=level+2*r
            issue=create_issue(level,stop,tp1,tp2)
            s.update({"status":"OPEN","entry_time":now,"entry_price":level,"stop_loss":stop,
                      "tp1":tp1,"tp2":tp2,"exit_due_at":now+5*H,"issue_number":issue,"last_hour_key":hour})
            save(s); print("ENTRY",fmt(level)); return
        save(s); print("PENDING"); return

    if s.get("last_hour_key")==hour:
        save(s); print("IDLE"); return

    g=gann(h[:i+1],l[:i+1],c[:i+1],5)
    s["last_hour_key"]=hour
    if g is None or c[i]<=g:
        s["status"]="IDLE"; save(s); print("IDLE"); return

    high51=max(h[i-50:i+1])
    s.update({"status":"PENDING","setup_time":hour,"pending_level":high51,"pending_expires_at":hour+10*H})
    save(s); print("SETUP",fmt(high51))

try:
    main()
except Exception as e:
    s=load(); s["last_error"]=str(e); save(s); print("ERROR",e)
