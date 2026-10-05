"""
SOL HUNTER V6.3 - PYDROID3 LAB (WITH TELEGRAM NOTIFICATIONS)
PAPER ONLY / READ-ONLY WALLET (UPGRADED)
- Added Slippage & Fee simulation
- Added Real-time isolated position refreshing
- Added GoPlus API for Mint/Honeypot security checks
- Added Reason logging
- Added Telegram Notifications
"""
import os, time, sqlite3, json
from datetime import datetime, timezone
import requests

# ================= CONFIG =================
PAPER_ONLY = True
PAPER_BALANCE = 100.0
POSITION_SIZE = 5.0
MAX_POSITIONS = 1
SCAN_INTERVAL = 90
DB_FILE = "sol_hunter_v6_3_pydroid.db"

# Telegram Config (از Environment Variables خوانده می‌شود)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Simulated Realities
SLIPPAGE = 0.02 # 2% slippage on entry and exit
DEX_FEE = 0.01  # 1% standard Solana swap fee estimate

MIN_LIQUIDITY = 15000.0
MIN_VOLUME_1H = 8000.0
MIN_AGE_MIN = 3.0
MAX_AGE_MIN = 120.0
MIN_SECURITY = 70
MIN_SMART = 45
MIN_NARRATIVE = 45
MIN_TIMING = 60
MIN_FINAL = 65 # Lowered slightly as GoPlus acts as the hard filter
STOP_LOSS = 0.15
RECOVERY_GAIN = 0.50
TRAILING_STOP = 0.15

DISCOVERY = ["solana", "meme", "ai", "dog", "cat", "pepe", "elon", "musk", "tesla", "spacex", "robot", "agent", "animal", "moon", "mars", "gold", "forex", "dollar", "btc", "bitcoin"]
THEMES = {
    "AI": ["ai", "agent", "gpt", "bot", "robot"],
    "ANIMAL": ["dog", "cat", "pepe", "frog", "bear", "wolf", "panda", "animal"],
    "ELON": ["elon", "musk", "tesla", "spacex"],
    "EVENT": ["event", "war", "olympic", "election", "launch", "mars", "moon"],
    "FINANCE": ["gold", "forex", "dollar", "btc", "bitcoin", "bank", "fed"],
    "MEME": ["meme", "moon", "inu", "wojak", "pepe"],
}

S = requests.Session()
S.headers.update({"User-Agent": "SOL-HUNTER/6.3-PYDROID"})

# ================= TELEGRAM HELPER =================
def send_telegram(msg):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        S.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"}, timeout=5)
    except Exception as e:
        print("⚠️ خطا در ارسال پیام به تلگرام:", repr(e))

# ================= DATABASE =================
def db():
    c = sqlite3.connect(DB_FILE)
    c.execute("CREATE TABLE IF NOT EXISTS positions(id INTEGER PRIMARY KEY, address TEXT UNIQUE, symbol TEXT, entry REAL, qty REAL, peak REAL, recovered INTEGER DEFAULT 0, opened TEXT, closed TEXT, status TEXT DEFAULT 'OPEN', pnl REAL DEFAULT 0, reason TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS tokens(address TEXT PRIMARY KEY, symbol TEXT, name TEXT, last_price REAL, score REAL, updated TEXT)")
    c.commit(); return c

# ================= HELPERS & SECURITY =================
def num(x, d=0.0):
    try: return float(x)
    except: return d

def age_min(pair):
    ts = pair.get("pairCreatedAt")
    if not ts: return 999999
    return max(0.0, (time.time()*1000 - num(ts))/60000)

def goplus_security_check(address):
    """Hard check for mintable and honeypot status via GoPlus"""
    try:
        r = S.get(f"https://api.gopluslabs.io/api/v1/token_security/501?contract_addresses={address}", timeout=5)
        if r.status_code == 200:
            data = r.json().get("result", {}).get(address.lower(), {})
            if not data: return True
            if data.get("is_mintable") == "1" or data.get("is_honeypot") == "1":
                return False
        return True
    except:
        return True

def normalize(p):
    b = p.get("baseToken") or {}
    tx = p.get("txns") or {}
    h1 = tx.get("h1") or {}; m5 = tx.get("m5") or {}
    vol = p.get("volume") or {}; ch = p.get("priceChange") or {}
    buys1, sells1 = int(h1.get("buys",0) or 0), int(h1.get("sells",0) or 0)
    buys5, sells5 = int(m5.get("buys",0) or 0), int(m5.get("sells",0) or 0)
    return {
        "address": b.get("address",""), "symbol": b.get("symbol","?"), "name": b.get("name","?"),
        "price": num(p.get("priceUsd")), "liquidity": num((p.get("liquidity") or {}).get("usd")),
        "volume1h": num(vol.get("h1")), "pc1h": num(ch.get("h1")), "pc5m": num(ch.get("m5")),
        "buys1": buys1, "sells1": sells1, "buys5": buys5, "sells5": sells5,
        "age": age_min(p), "url": p.get("url","")
    }

def discover():
    out = {}
    for q in DISCOVERY:
        try:
            r = S.get("https://api.dexscreener.com/latest/dex/search", params={"q":q}, timeout=12)
            if r.status_code != 200: continue
            for p in (r.json().get("pairs") or []):
                if p.get("chainId") != "solana": continue
                x = normalize(p)
                if not x["address"]: continue
                old = out.get(x["address"])
                if old is None or x["liquidity"] > old["liquidity"]: out[x["address"]] = x
        except requests.RequestException:
            continue
    return list(out.values())

def score(x):
    sec = 100
    if x["liquidity"] < MIN_LIQUIDITY: sec -= 25
    if x["pc5m"] > 35: sec -= 20
    if x["pc1h"] > 80: sec -= 15
    total = x["buys1"] + x["sells1"]
    if total and x["sells1"]/total > .55: sec -= 25
    sec = max(0, min(100, sec))

    text = (x["name"] + " " + x["symbol"]).lower()
    themes = [k for k, words in THEMES.items() if any(w in text for w in words)]
    nar = 35 + min(25, len(themes)*10)
    if x["volume1h"] >= MIN_VOLUME_1H: nar += 8
    if x["buys5"] > x["sells5"]*1.5: nar += 7
    nar = min(100, nar)

    sm = 30 + (x["buys1"]/total if total else 0)*45
    if x["buys5"] > x["sells5"]: sm += 10
    if x["buys5"] >= 8: sm += 8
    sm = min(100, sm)

    tim = 100
    if x["age"] > 60: tim -= 12
    if x["age"] > 100: tim -= 20
    if x["pc5m"] > 12: tim -= 15
    if x["pc5m"] > 25: tim -= 25
    if x["pc1h"] > 80: tim -= 25
    if x["buys5"] > x["sells5"] and x["pc5m"] < 12: tim += 5
    tim = max(0, min(100, tim))

    final = sec*.32 + sm*.23 + nar*.20 + tim*.25
    return {"security":round(sec),"smart":round(sm),"narrative":round(nar),"timing":round(tim),"final":round(final),"themes":themes}

def eligible(x, sc):
    return (MIN_AGE_MIN <= x["age"] <= MAX_AGE_MIN and x["liquidity"] >= MIN_LIQUIDITY and 
            x["volume1h"] >= MIN_VOLUME_1H and sc["security"] >= MIN_SECURITY and 
            sc["smart"] >= MIN_SMART and sc["narrative"] >= MIN_NARRATIVE and 
            sc["timing"] >= MIN_TIMING and sc["final"] >= MIN_FINAL)

# ================= PAPER ENGINE =================
def open_positions(c): return c.execute("SELECT * FROM positions WHERE status='OPEN'").fetchall()

def refresh_open_positions(c):
    rows = open_positions(c)
    prices = {}
    for r in rows:
        address = r[1]
        try:
            res = S.get(f"https://api.dexscreener.com/latest/dex/tokens/{address}", timeout=5)
            if res.status_code == 200:
                pairs = res.json().get("pairs", [])
                if pairs:
                    prices[address] = num(pairs[0].get("priceUsd"))
        except: pass
    return prices

def paper_buy(c, x, sc):
    if not PAPER_ONLY or open_positions(c): return False
    if x["price"] <= 0: return False
    
    if not goplus_security_check(x["address"]):
        print(f"🚨 SECURITY REJECT: {x['symbol']} failed GoPlus checks (Mint/Honeypot).")
        send_telegram(f"🚨 <b>هشدار امنیتی</b>\nتوکن {x['symbol']} در بررسی GoPlus به عنوان Mintable یا Honeypot شناسایی شد و رد شد.")
        return False

    real_entry_price = x["price"] * (1 + SLIPPAGE)
    capital_after_fee = POSITION_SIZE * (1 - DEX_FEE)
    qty = capital_after_fee / real_entry_price
    reason = f"Final:{sc['final']} S:{sc['security']} M:{sc['smart']} T:{sc['themes']}"
    
    c.execute("INSERT OR IGNORE INTO positions(address,symbol,entry,qty,peak,opened,reason) VALUES(?,?,?,?,?,?,?)", 
              (x["address"],x["symbol"],real_entry_price,qty,real_entry_price,datetime.now(timezone.utc).isoformat(),reason))
    c.commit()
    
    buy_msg = (
        f"🟢 <b>سیگنال خرید جدید (Paper Buy)</b>\n\n"
        f"🪙 <b>نماد:</b> ${x['symbol']}\n"
        f"💵 <b>قیمت ورود:</b> ${real_entry_price:.10f}\n"
        f"💰 <b>حجم پوزیشن:</b> ${POSITION_SIZE:.2f}\n"
        f"📊 <b>امتیاز نهایی:</b> {sc['final']}/100\n"
        f"🛡️ <b>امنیت:</b> {sc['security']} | <b>هوشمند:</b> {sc['smart']}\n"
        f"⏱️ <b>سن توکن:</b> {x['age']:.1f} دقیقه\n"
        f"💧 <b>نقدینگی:</b> ${x['liquidity']:,.0f}\n\n"
        f"🔗 <a href='{x['url']}'>مشاهده در DexScreener</a>"
    )
    print(f"\n🟢 PAPER BUY ${POSITION_SIZE:.2f} {x['symbol']} @ ${real_entry_price:.10f}")
    send_telegram(buy_msg)
    return True

def manage(c):
    prices = refresh_open_positions(c)
    rows = open_positions(c)
    for r in rows:
        pid,address,symbol,entry,qty,peak,recovered,opened,closed,status,pnl,reason = r
        price = prices.get(address)
        if not price: continue
        
        peak = max(num(peak), price)
        real_exit_price = price * (1 - SLIPPAGE)
        gain = real_exit_price/entry - 1 if entry else 0
        
        if not recovered and gain >= RECOVERY_GAIN:
            recovered = 1
            print(f"💰 RECOVERY +50%: {symbol}")
            send_telegram(f"💰 <b>بازیابی اصل سرمایه (+50%)</b>\nتوکن: ${symbol}\nسود تا این لحظه: +{gain*100:.1f}%")
            
        stop = entry*(1-STOP_LOSS) if not recovered else peak*(1-TRAILING_STOP)
        
        if real_exit_price <= stop:
            exit_capital = (real_exit_price * qty) * (1 - DEX_FEE)
            pnl = exit_capital - POSITION_SIZE
            c.execute("UPDATE positions SET peak=?, recovered=?, closed=?, status='CLOSED', pnl=? WHERE id=?", 
                      (peak,recovered,datetime.now(timezone.utc).isoformat(),pnl,pid)); c.commit()
            
            pnl_emoji = "🟢" if pnl >= 0 else "🔴"
            exit_msg = (
                f"{pnl_emoji} <b>خروج از پوزیشن (Paper Exit)</b>\n\n"
                f"🪙 <b>نماد:</b> ${symbol}\n"
                f"💵 <b>قیمت خروج:</b> ${real_exit_price:.10f}\n"
                f"📊 <b>PnL (سود/زیان):</b> ${pnl:.2f}\n"
                f"📈 <b>بازدهی:</b> {gain*100:+.2f}%\n"
            )
            print(f"🔴 PAPER EXIT {symbol} @ ${real_exit_price:.10f} | Final PnL ${pnl:.2f}")
            send_telegram(exit_msg)
        else:
            c.execute("UPDATE positions SET peak=?, recovered=? WHERE id=?", (peak,recovered,pid)); c.commit()

# ================= MAIN LOOP =================
def run_once():
    c = db()
    manage(c)
    
    data = discover(); stats={"discovery":len(data),"basic":0,"security":0}
    scored=[]
    
    for x in data:
        if MIN_AGE_MIN <= x["age"] <= MAX_AGE_MIN and x["liquidity"] >= MIN_LIQUIDITY and x["volume1h"] >= MIN_VOLUME_1H:
            stats["basic"] += 1
            sc = score(x)
            if sc["security"] >= MIN_SECURITY: stats["security"] += 1
            x["sc"] = sc; scored.append(x)
            c.execute("INSERT OR REPLACE INTO tokens VALUES(?,?,?,?,?,?)",(x["address"],x["symbol"],x["name"],x["price"],sc["final"],datetime.now(timezone.utc).isoformat()))
    
    c.commit()
    scored.sort(key=lambda z:z["sc"]["final"], reverse=True)
    
    print("\n"+"="*100); print("🦈 SOL HUNTER V6.3 | PYDROID3 LAB | REALISTIC SIMULATION"); print("="*100)
    print(f"Discovery={stats['discovery']} | Basic={stats['basic']} | Security OK={stats['security']} | Open={len(open_positions(c))}")
    print("\n🏆 TOP 10")
    for i,x in enumerate(scored[:10],1):
        s = x["sc"]
        decision = "PAPER_BUY" if eligible(x,s) else "WATCH"
        print(f"#{i:<2} {x['symbol'][:14]:<14} age={x['age']:5.1f}m L=${x['liquidity']:,.0f} V=${x['volume1h']:,.0f} 5m={x['pc5m']:+.1f}% S={s['security']} M={s['smart']} N={s['narrative']} T={s['timing']} F={s['final']} {decision}")
        if decision == "PAPER_BUY" and not open_positions(c): 
            paper_buy(c,x,s); break
    c.close()

def main():
    print("🦈 SOL HUNTER V6.3 PYDROID3 STARTED — REALISTIC PAPER ENGINE")
    send_telegram("🚀 <b>ربات SOL HUNTER روشن شد و شروع به اسکن نمود.</b>")
    while True:
        try: run_once()
        except KeyboardInterrupt: 
            print("\nStopped.")
            break
        except Exception as e: 
            print("⚠️ LOOP ERROR:",repr(e))
        print(f"\n⏳ Next scan in {SCAN_INTERVAL}s")
        time.sleep(SCAN_INTERVAL)

if __name__ == "__main__": main()
