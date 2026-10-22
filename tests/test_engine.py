"""Known values recorded from the original game (via the headless oracle)."""

from balatro import Game


def test_testseed_start():
    G = Game("TESTSEED").start_run()
    rr = G.GAME.round_resets
    assert rr.blind_choices.Boss == "bl_head"
    assert G.GAME.current_round.voucher == "v_crystal_ball"
    assert (rr.blind_tags.Small, rr.blind_tags.Big) == ("tag_economy", "tag_investment")
    deck = " ".join(c.base.suit[0] + c.base.value for c in G.deck.cards)
    assert deck == ("D5 D9 D2 HJack H4 H6 HAce S3 S5 H9 S6 C5 SJack SKing H7 D10 CJack S4 CQueen H2 C7 D7 SAce "
                    "S10 SQueen HQueen C9 D8 CKing C2 H5 HKing C10 DQueen S9 DAce D6 DKing D4 C3 S2 H10 D3 H3 C6 "
                    "S7 C8 C4 H8 CAce DJack S8")


def test_testseed_first_round():
    G = Game("TESTSEED").start_run()
    G.act_select_blind()
    assert [c.config.card_key for c in G.hand.cards] == ["H_A", "H_K", "D_Q", "S_9", "C_9", "C_5", "D_5", "C_4"]
    G.act_play([0, 1, 2, 3, 4])
    assert G.GAME.chips == 56
    assert [c.config.card_key for c in G.hand.cards] == ["S_A", "C_Q", "C_T", "C_8", "H_7", "C_5", "D_5", "C_4"]


def test_erratic_nan_seed_runs():
    # 'erratic' .. '7LB2WVPK' hashes to NaN in the game; every erratic draw then
    # hits the same card - the engine must reproduce that instead of crashing
    G = Game("7LB2WVPK", deck="b_erratic").start_run()
    assert len({c.config.card_key for c in G.playing_cards}) == 1
