import httpx
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from flask import Flask, request, jsonify
from datetime import datetime
import asyncio
import data_pb2
import encode_id_clan_pb2

# ===================== CONFIG =====================
app = Flask(__name__)
freefire_version = "OB53"

key = bytes([89,103,38,116,99,37,68,69,117,104,54,37,90,99,94,56])
iv  = bytes([54,111,121,90,68,114,50,50,69,51,121,99,104,106,77,37])

jwt_tokens = {}

# ===================== JWT =====================
async def get_access_token(account):
    try:
        parts = dict(x.split("=") for x in account.split("&"))
        uid = parts.get("uid")
        password = parts.get("password")

        url = f"https://vk-boy-acc.vercel.app/guest_to_jwt?uid={uid}&password={password}"

        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(url)

        if r.status_code != 200:
            print("[JWT FAIL]", r.text[:100])
            return None

        data = r.json()
        return data.get("jwt_token")

    except Exception as e:
        print("[JWT ERROR]", e)
        return None


async def create_jwt(region):
    accounts = {
        "IND": "uid=4471767672&password=SEXTY_MODS_IND_REOPRZXEW",
        "BD":  "uid=4558447129&password=SEXTY_MODS_IND_QCZBNBQKO",
        "BR":  "uid=4627778236&password=SEXTY_MODS_IND_O8ALMMBEF",
        "US":  "uid=3333333333&password=xxx"
    }

    acc = accounts.get(region, accounts["IND"])
    token = await get_access_token(acc)

    if token:
        jwt_tokens[region] = f"Bearer {token}"
        print("[JWT READY]", region)


async def ensure_token(region):
    if region in jwt_tokens:
        return jwt_tokens[region]

    await create_jwt(region)
    return jwt_tokens.get(region)

# ===================== TIME =====================
def ts(x):
    try:
        return datetime.fromtimestamp(int(x)).strftime("%Y-%m-%d %H:%M:%S")
    except:
        return None

# ===================== ROUTE =====================
@app.route('/info', methods=['GET'])
def get_clan_info():

    clan_id = request.args.get("clan_id")
    region  = request.args.get("region", "IND").upper()

    if not clan_id:
        return jsonify({"error": "clan_id required"}), 400

    # ===== GET TOKEN =====
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        token = loop.run_until_complete(ensure_token(region))
        loop.close()
    except Exception as e:
        return jsonify({"error": "token fail", "details": str(e)}), 500

    if not token:
        return jsonify({"error": "JWT not available"}), 500

    try:
        # ===== PROTO REQUEST =====
        msg = encode_id_clan_pb2.MyData()
        msg.field1 = int(clan_id)
        msg.field2 = 1

        raw = msg.SerializeToString()

        cipher = AES.new(key, AES.MODE_CBC, iv)
        payload = cipher.encrypt(pad(raw, 16))

        region_map = {
            "IND": ("https://client.ind.freefiremobile.com/GetClanInfoByClanID","client.ind.freefiremobile.com"),
            "BD":  ("https://clientbp.ggblueshark.com/GetClanInfoByClanID","clientbp.ggblueshark.com"),
            "BR":  ("https://client.us.freefiremobile.com/GetClanInfoByClanID","client.us.freefiremobile.com"),
            "US":  ("https://client.us.freefiremobile.com/GetClanInfoByClanID","client.us.freefiremobile.com"),
            "SAC": ("https://client.us.freefiremobile.com/GetClanInfoByClanID","client.us.freefiremobile.com"),
            "NA":  ("https://client.us.freefiremobile.com/GetClanInfoByClanID","client.us.freefiremobile.com"),
        }

        url, host = region_map.get(region, region_map["IND"])

        headers = {
            "Authorization": token,
            "Content-Type": "application/octet-stream",
            "User-Agent": "Dalvik/2.1.0",
            "ReleaseVersion": freefire_version,
            "Host": host
        }

        with httpx.Client(timeout=15.0) as client:
            r = client.post(url, headers=headers, content=payload)

        if r.status_code != 200:
            return jsonify({"error": f"HTTP {r.status_code}"}), 500

        # ===== DECODE =====
        resp = data_pb2.response()
        resp.ParseFromString(r.content)

        # ===== FIND CLAN =====
        def find_clan(obj):
            if hasattr(obj, "clanInfo"):
                return obj.clanInfo

            for f in dir(obj):
                try:
                    v = getattr(obj, f)
                    if hasattr(v, "memberNum"):
                        return v
                except:
                    pass
            return None

        clan = find_clan(resp)

        # ===== DEFAULT =====
        member = 0
        capacity = 50
        leader = 0
        glory = 0

        if clan:
            def pick(keys):
                for k in keys:
                    if hasattr(clan, k):
                        return getattr(clan, k)
                return 0

            member   = int(pick(["memberNum","memberCount"]) or 0)
            capacity = int(pick(["capacity","maxMembers"]) or 50)

            cap = getattr(clan, "captainBasicInfo", None)
            if cap:
                leader = int(getattr(cap, "accountId", 0))

            # ===== GLORY FIX =====
            glory = int(pick([
                "glory",
                "clanGlory",
                "guildGlory",
                "creditScore",
                "clanScore"
            ]) or 0)

        # fallback (important)
        if glory == 0:
            glory = getattr(resp, "clan_glory", 0) or getattr(resp, "glory", 0)

        # ===== RESPONSE =====
        return jsonify({
            "clan_id": getattr(resp, "id", clan_id),
            "clan_name": getattr(resp, "special_code", None),

            "level": getattr(resp, "rank", None),
            "region": getattr(resp, "region", region),

            "member_count": member,
            "capacity": capacity,
            "leader_uid": leader,

            "guild_glory": glory,

            "score": getattr(resp, "score", 0),
            "xp": getattr(resp, "xp", 0),

            "created_at": ts(getattr(resp, "timestamp1", 0)),
            "last_active": ts(getattr(resp, "last_active", 0)),

            "status": "success"
        }), 200

    except Exception as e:
        return jsonify({"error": "server crash", "details": str(e)}), 500


# ===================== HEALTH =====================
@app.route('/health')
def health():
    return jsonify({
        "status": "running
