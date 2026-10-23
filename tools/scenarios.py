"""Targeted differential scenarios: setups that exercise the timing races
(destroyed / eaten / sliced cards, packs filling up, boss effects).

    python tools/scenarios.py [name ...]

Each scenario sets a run up with test helpers (no RNG involved), then plays
it with a simple policy; the engine and the original game are compared after
every command.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from balatro.game import Game  # noqa: E402
from balatro.oracle import Oracle, diff, normalize  # noqa: E402
from balatro.oracle.fuzz import best_play  # noqa: E402


def J(*keys: str) -> list[dict]:
    return [{"cmd": "add_joker", "key": k} for k in keys]


def C(*keys: str) -> list[dict]:
    return [{"cmd": "add_joker", "key": k} for k in keys]


SCENARIOS: dict[str, dict[str, Any]] = {
    "dagger_juggler": dict(setup=J("j_ceremonial", "j_juggler"), policy="play"),
    "dagger_troubadour": dict(setup=J("j_ceremonial", "j_troubadour"), policy="play"),
    "dagger_turtle": dict(setup=J("j_ceremonial", "j_turtle_bean", "j_ceremonial", "j_juggler"), policy="play"),
    "madness_juggler": dict(setup=J("j_madness", "j_juggler", "j_juggler", "j_stuntman"), policy="play"),
    "trading_card": dict(setup=J("j_trading", "j_trading"), policy="discard1"),
    "hallucination_packs": dict(setup=J("j_hallucination", "j_hallucination", "j_hallucination"), policy="packs",
                                dollars=200),
    "gros_michel": dict(setup=J("j_gros_michel", "j_gros_michel", "j_gros_michel", "j_gros_michel"), policy="play",
                        dollars=100),
    "eaten_food": dict(setup=J("j_ice_cream", "j_popcorn", "j_selzer", "j_ramen", "j_turtle_bean"), policy="mixed"),
    "glass": dict(setup=J("j_glass", "j_oops", "j_oops") + C("c_justice", "c_justice"), policy="glass"),
    "hanged_man": dict(setup=C("c_hanged_man", "c_hanged_man") + J("j_caino", "j_glass"), policy="use_first"),
    "spectral_destroy": dict(setup=C("c_immolate", "c_grim") + J("j_caino"), policy="use_first"),
    "ankh_hex": dict(setup=J("j_juggler", "j_turtle_bean", "j_joker") + C("c_ankh", "c_hex"), policy="use_first"),
    "first_hand": dict(setup=J("j_dna", "j_certificate", "j_marble", "j_riff_raff"), policy="single"),
    "setting_blind": dict(setup=J("j_burglar", "j_cartomancer", "j_marble", "j_madness"), policy="play"),
    "sixth_sense": dict(setup=J("j_sixth_sense", "j_vagabond", "j_superposition"), policy="single"),
    "vampire_midas": dict(setup=J("j_midas_mask", "j_vampire") + C("c_magician", "c_empress"), policy="use_first"),
    "perkeo": dict(setup=J("j_perkeo", "j_invisible") + C("c_fool", "c_jupiter"), policy="shop_sell", dollars=60),
    "boss_hook": dict(setup=[{"cmd": "cheat", "boss": "bl_hook"}], policy="play"),
    "boss_bell": dict(setup=[{"cmd": "cheat", "boss": "bl_final_bell", "ante": 8}], policy="play"),
    "boss_heart": dict(setup=J("j_joker", "j_juggler", "j_blueprint") + [{"cmd": "cheat", "boss": "bl_final_heart", "ante": 8}],
                       policy="play"),
    "boss_acorn": dict(setup=J("j_joker", "j_juggler", "j_madness") + [{"cmd": "cheat", "boss": "bl_final_acorn", "ante": 8}],
                       policy="play"),
    "boss_ox_arm": dict(setup=[{"cmd": "cheat", "boss": "bl_ox", "ante": 6}], policy="play"),
    "luchador_chicot": dict(setup=J("j_luchador", "j_chicot") + [{"cmd": "cheat", "boss": "bl_manacle"}], policy="sell_play"),
    "diet_cola": dict(setup=J("j_diet_cola", "j_invisible"), policy="sell_play"),
}


def choose(G: Game, policy: str, step: int) -> dict:
    S = G.STATES
    st = G.STATE
    legal = G.legal_actions()
    cmds = {a["cmd"] for a in legal}
    if st == S.BLIND_SELECT:
        if policy == "sell_play" and step < 30:
            for a in legal:
                if a["cmd"] == "sell" and a["area"] == "jokers":
                    return a
        return {"cmd": "select_blind"}
    if st == S.SELECTING_HAND:
        n = len(G.hand.cards)
        for a in legal:
            if a["cmd"] == "use" and policy in ("use_first", "glass", "mixed") and G.consumeables.cards:
                cons = G.consumeables.cards[a["index"]].ability.consumeable
                k = min(cons.mod_num or 1, n) if cons.max_highlighted else None
                t = list(range(k)) if k else None
                if t is None or G.can_use(a["index"], t):
                    return {"cmd": "use", "index": a["index"], "targets": t}
        if policy == "discard1" and "discard" in cmds:
            return {"cmd": "discard", "cards": [step % n]}
        if policy == "mixed" and "discard" in cmds and step % 3 == 0:
            return {"cmd": "discard", "cards": list(range(min(3, n)))}
        if policy == "single" and step % 2 == 0:
            return {"cmd": "play", "cards": [n - 1]}
        if policy == "glass" and step % 2 == 0:
            return {"cmd": "play", "cards": [0, 1]}
        return {"cmd": "play", "cards": best_play(G)}
    if st == S.ROUND_EVAL:
        return {"cmd": "cash_out"}
    if G.in_shop():
        if policy in ("packs", "hallucination") or policy == "packs":
            for a in legal:
                if a["cmd"] == "buy" and a["area"] == "shop_booster":
                    return a
        if policy == "shop_sell":
            for a in legal:
                if a["cmd"] == "buy" and a["area"] == "shop_jokers" and not a.get("use"):
                    return a
        return {"cmd": "end_shop"}
    if G.in_pack():
        for a in legal:
            if a["cmd"] == "pick" and "max" not in a:
                return dict(a, targets=[])
        return {"cmd": "skip_pack"}
    return legal[0]


def run(name: str, seed: str = "SCEN1234", deck: str = "b_red", steps: int = 40) -> bool:
    sc = SCENARIOS[name]
    start = {"cmd": "start", "seed": seed, "deck": "Red Deck", "stake": 1}
    with Oracle() as o:
        r = o.send(start)
        G = Game(seed, deck=deck, hands_order=r["state"]["hands_order"]).start_run()
        log = [start]
        cmds: list[dict] = list(sc["setup"])
        if sc.get("dollars"):
            cmds.append({"cmd": "cheat", "dollars": sc["dollars"]})
        for i in range(steps + len(cmds)):
            if G.is_game_over():
                break
            cmd = cmds.pop(0) if cmds else choose(G, sc["policy"], i)
            if G.STATE == G.STATES.SELECTING_HAND and G.GAME.current_round.hands_left <= 1 and not cmds:
                cmd = {"cmd": "cheat", "win": True}
            log.append(cmd)
            r = o.send(cmd)
            G.do(cmd)
            d = diff(normalize(G.snapshot()), normalize(r["state"]))
            if d:
                print(f"{name}: DIVERGED at {len(log) - 1} {json.dumps(cmd)}")
                for line in d[:25]:
                    print("   ", line)
                with open(f"scenario_{name}.json", "w") as f:
                    json.dump({"log": log}, f)
                return False
    print(f"{name}: identical ({len(log) - 1} commands, ante {G.GAME.round_resets.ante})")
    return True


def check_keys() -> None:
    centers = Game("X").P_CENTERS
    for name, sc in SCENARIOS.items():
        for c in sc["setup"]:
            if c["cmd"] == "add_joker" and c["key"] not in centers:
                raise SystemExit(f"{name}: unknown key {c['key']}")


if __name__ == "__main__":
    check_keys()
    names = sys.argv[1:] or list(SCENARIOS)
    ok = sum(run(n) for n in names)
    print(f"{ok}/{len(names)} scenarios identical")
    sys.exit(0 if ok == len(names) else 1)
