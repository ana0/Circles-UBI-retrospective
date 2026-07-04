#!/usr/bin/env python3
"""
Read the Circles v1 Hub monetary constants directly from chain (authoritative,
self-verifying). Includes a pure-python keccak-256 (no external deps) validated
against the known empty-string vector, so function selectors are computed, not
trusted.

Hub: 0x29b9a7fBb8995b2423a71cC17cf9810798F6C543 (Gnosis Chain)

Run: python3 hub_constants.py
"""
import json, urllib.request

RPC = "https://rpc.gnosischain.com"
HUB = "0x29b9a7fBb8995b2423a71cC17cf9810798F6C543"

def keccak256(msg: bytes) -> bytes:
    RC=[0x0000000000000001,0x0000000000008082,0x800000000000808A,0x8000000080008000,
        0x000000000000808B,0x0000000080000001,0x8000000080008081,0x8000000000008009,
        0x000000000000008A,0x0000000000000088,0x0000000080008009,0x000000008000000A,
        0x000000008000808B,0x800000000000008B,0x8000000000008089,0x8000000000008003,
        0x8000000000008002,0x8000000000000080,0x000000000000800A,0x800000008000000A,
        0x8000000080008081,0x8000000000008080,0x0000000080000001,0x8000000080008008]
    r=[[0,36,3,41,18],[1,44,10,45,2],[62,6,43,15,61],[28,55,25,21,56],[27,20,39,8,14]]
    def rol(x,n): return ((x<<n)|(x>>(64-n)))&0xFFFFFFFFFFFFFFFF
    S=[[0]*5 for _ in range(5)]; rate=136
    m=bytearray(msg); m.append(0x01)
    while len(m)%rate!=0: m.append(0)
    m[-1]^=0x80
    for off in range(0,len(m),rate):
        blk=m[off:off+rate]
        for i in range(rate//8):
            S[i%5][i//5]^=int.from_bytes(blk[i*8:i*8+8],'little')
        for rnd in range(24):
            C=[S[x][0]^S[x][1]^S[x][2]^S[x][3]^S[x][4] for x in range(5)]
            D=[C[(x-1)%5]^rol(C[(x+1)%5],1) for x in range(5)]
            for x in range(5):
                for y in range(5): S[x][y]^=D[x]
            B=[[0]*5 for _ in range(5)]
            for x in range(5):
                for y in range(5): B[y][(2*x+3*y)%5]=rol(S[x][y],r[x][y])
            for x in range(5):
                for y in range(5): S[x][y]=B[x][y]^((~B[(x+1)%5][y])&B[(x+2)%5][y])
            S[0][0]^=RC[rnd]
    out=bytearray(); i=0
    while len(out)<32:
        out+=S[i%5][i//5].to_bytes(8,'little'); i+=1
    return bytes(out[:32])

assert keccak256(b"").hex()=="c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470", "keccak self-test FAILED"

def selector(sig): return "0x"+keccak256(sig.encode())[:4].hex()

def call_uint(sig):
    req=urllib.request.Request(RPC, data=json.dumps({"jsonrpc":"2.0","method":"eth_call",
        "params":[{"to":HUB,"data":selector(sig)},"latest"],"id":1}).encode(),
        headers={"Content-Type":"application/json"})
    res=json.loads(urllib.request.urlopen(req,timeout=30).read())
    r=res.get("result")
    return int(r,16) if r and r!="0x" else None

if __name__ == "__main__":
    print("keccak self-test: OK\n")
    wad = 10**18
    sb = call_uint("signupBonus()")
    ii = call_uint("initialIssuance()")
    inf = call_uint("inflation()"); dv = call_uint("divisor()")
    pd = call_uint("period()")
    print(f"signupBonus     = {sb} wei = {sb/wad:g} CRC")
    print(f"initialIssuance = {ii} wei/s = {ii*86400/wad:g} CRC/day")
    print(f"inflation/divisor = {inf}/{dv} = +{(inf/dv-1)*100:g}%/yr")
    print(f"period          = {pd} s = {pd/86400:g} days")
