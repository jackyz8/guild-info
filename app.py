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

key = bytes([89, 103, 38, 116, 99, 37, 68, 69, 117, 104, 54, 37, 90, 99, 94, 56])
iv = bytes([54, 111, 121, 90, 68, 114, 50, 50, 69, 51, 121, 99, 104, 106, 77, 37])

jwt_tokens = {}

# ===================== JWT TOKEN =====================
async def get_access_token(account):
    try:
        parts = dict(x.split("=") for x in account.split("&"))
        uid = parts.get("uid")
        password = parts.get("password")

        url = f"https://vk-boy-acc.vercel.app/guest_to_jwt?uid={uid}&password={password}"

        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(url)

        if r.status_code != 200:
            print("[JWT FAIL]", r.text[:100])
            return None, None

        data = r.json()
        return data.get("jwt_token"), data.get("open_id")

    except Exception as e:
        print("[JWT ERROR]", e)
        return None, None


async def create_jwt(region):
    accounts = {
        "IND": "uid=4471767672&password=SEXTY_MODS_IND_REOPRZXEW",
        "BD": "uid=4558447129&password=SEXTY_MODS_IND_QCZBNBQKO",
        "BR": "uid=4627778236&password=SEXTY_MODS_IND_O8ALMMBEF",
        "US": "uid=3333333333&password=xxx"
    }

    account = accounts.get(region, accounts["IND"])

    token, open_id = await get_access_token(account)

    if token:
        jwt_tokens[region] = f"Bearer {token}"
        print(f"[JWT READY] {region}")
    else:
        print(f"[JWT FAIL] {region}")


async def ensure_token(region):
    if region in jwt_tokens:
        return jwt_tokens[region]

    await create_jwt(region)
    return jwt_tokens.get(region)

# ===================== MAIN ROUTE =====================
@app.route('/info', methods=['GET'])
def get_clan_info():
    clan_id = request.args.get('clan_id')
    region = request.args.get('region', 'IND').upper()

    if not clan_id:
        return jsonify({"error": "clan_id required"}), 400

    # ===== TOKEN =====
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    token = loop.run_until_complete(ensure_token(region))
    loop.close()

    if not token:
        return jsonify({"error": "JWT not available"}), 503

    try:
        # ===== PROTO =====
        my_data = encode_id_clan_pb2.MyData()
        my_data.field1 = int(clan_id)
        my_data.field2 = 1

        data_bytes = my_data.SerializeToString()

        cipher = AES.new(key, AES.MODE_CBC, iv)
        payload = cipher.encrypt(pad(data_bytes, 16))

        # ===== REGION =====
        region_map = {
            "IND": ("https://client.ind.freefiremobile.com/GetClanInfoByClanID", "client.ind.freefiremobile.com"),
            "BD": ("https://clientbp.ggblueshark.com/GetClanInfoByClanID", "clientbp.ggblueshark.com"),
            "BR": ("https://client.us.freefiremobile.com/GetClanInfoByClanID", "client.us.freefiremobile.com"),
            "US": ("https://client.us.freefiremobile.com/GetClanInfoByClanID", "client.us.freefiremobile.com"),
        }

        url, host = region_map.get(region, region_map["IND"])

        headers = {
            "Authorization": token,
            "Content-Type": "application/octet-stream",
            "User-Agent": "Dalvik/2.1.0",
            "Host": host
        }

        # ===== REQUEST =====
        with httpx.Client(timeout=20.0) as client:
            response = client.post(url, headers=headers, content=payload)

        if response.status_code != 200:
            return jsonify({"error": f"HTTP {response.status_code}"}), 500

        # ===== DECODE =====
        resp = data_pb2.response()
        resp.ParseFromString(response.content)

        # ===== FINAL CLEAN RESPONSE =====
        return jsonify({
            "guild_name": getattr(resp, "special_code", None),
            "clan_id": getattr(resp, "id", clan_id),
            "level": getattr(resp, "rank", None),
            "region": getattr(resp, "region", region),
            "status": "success"
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ===================== HEALTH =====================
@app.route('/health')
def health():
    return jsonify({
        "status": "running",
        "tokens": list(jwt_tokens.keys())
    })


# ===================== START =====================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
