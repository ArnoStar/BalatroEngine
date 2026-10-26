"""The player's progress: what an unseeded run unlocks and discovers (progress.py).
The oracle fuzz (--profile fresh --unlocks) checks it against the game."""

from balatro import Game, Profile
from balatro.progress import CHALLENGE_WINS

from test_api import play_random


def test_a_seeded_run_or_a_challenge_unlocks_nothing():
    for kw in ({"seeded": True}, {"seeded": False, "challenge": "c_omelette_1"}):
        G = Game("PROGRESS", profile=Profile.fresh(), **kw).start_run()
        G.do({"cmd": "continue"})
        G.act_select_blind()
        G.act_play([0, 1, 2, 3, 4])
        assert G.PROFILE.progress.unlocked == [] and G.PROFILE.progress.discovered == []


def test_an_unseeded_run_unlocks_and_discovers():
    G = Game("PROGRESS", profile=Profile.fresh(), seeded=False).start_run()
    fb = G.start_feedback()
    G.do({"cmd": "continue"})  # Throwback: continue a run from the main menu
    G.stop_feedback()
    assert G.PROFILE.progress.unlocked == ["j_throwback"] and G.is_unlocked(G.P_CENTERS["j_throwback"])
    assert [(e["key"], e["set"]) for e in fb if e["type"] == "card_unlocked"] == [("j_throwback", "Joker")]
    G.act_select_blind()
    G.do({"cmd": "cheat", "win": True})
    G.do({"cmd": "cash_out"})
    assert "bl_small" in G.PROFILE.progress.discovered  # a beaten blind is discovered
    assert "bl_small" in G.profile.discovered and G.GAME.round_scores.new_collection.amt >= 1


def test_the_callers_profile_is_not_changed():
    p = Profile.fresh()
    before = p.to_json()
    G = Game("PROGRESS", profile=p, seeded=False).start_run()
    G.do({"cmd": "continue"})
    assert p.to_json() == before


def test_unlocks_change_the_pools_and_a_profile_replays_the_same():
    # what is unlocked decides the pools: a fresh profile's run differs from an all-unlocked one,
    # and the same profile always gives the same run
    def run(profile):
        G, trace = play_random("POOLS123", steps=60, rnd_seed=4, profile=profile, seeded=False)
        return G.snapshot(), trace
    fresh1, t1 = run(Profile.fresh())
    fresh2, _ = run(Profile.fresh())
    assert fresh1 == fresh2
    everything, t3 = run(Profile.everything())
    assert (fresh1, t1) != (everything, t3)


def test_profile_round_trip_and_helpers():
    p = Profile.fresh()
    p.unlocked.add("j_throwback")
    p.discovered |= {"bl_small", "tag_foil"}
    p.career_stats["c_cards_discarded"] = 300
    p.deck_usage["b_red"] = {"wins": {1: 1, 2: 1}, "losses": {}}
    p.voucher_usage["v_blank"] = 2
    p.challenges_completed.add("c_omelette_1")
    q = Profile.from_json(p.to_json())
    assert q.to_json() == p.to_json()
    assert q.deck_win_stake("b_red") == 2 and q.max_stake("b_red") == 3 and q.max_stake("b_blue") == 1
    assert Profile.everything().max_stake("b_red") == 8 and Profile.from_json({"all": True}).all
    assert q.challenges_unlocked(20) == 0
    for d in ("b_blue", "b_yellow", "b_green", "b_black")[: CHALLENGE_WINS - 1]:
        q.deck_usage[d] = {"wins": {1: 1}, "losses": {}}
    assert q.challenges_unlocked(20) == 1 + 5  # 5 decks won with, 1 challenge completed


def test_the_main_menu_unlocks_career_stats():
    p = Profile.fresh()
    p.career_stats["c_cards_discarded"] = 2500  # Recyclomancy: discard 2500 cards
    p.career_stats["c_hands_played"] = 10  # (Acrobat needs 200)
    q = p.with_main_menu_unlocks()
    assert q.is_unlocked("v_recyclomancy") and not q.is_unlocked("j_acrobat")
    assert not p.is_unlocked("v_recyclomancy")


def test_a_clone_has_its_own_progress():
    G = Game("PROGRESS", profile=Profile.fresh(), seeded=False).start_run()
    C = G.clone()
    C.do({"cmd": "continue"})
    assert C.PROFILE.progress.unlocked == ["j_throwback"]
    assert G.PROFILE.progress.unlocked == [] and not G.is_unlocked(G.P_CENTERS["j_throwback"])
    G.do({"cmd": "continue"})
    assert G.PROFILE.progress.unlocked == ["j_throwback"]
