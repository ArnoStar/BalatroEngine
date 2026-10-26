-- Ground-truth oracle: drives the ORIGINAL Balatro code headlessly.
--
-- Protocol: one JSON object per line on stdin, one JSON reply per line on
-- stdout.  Every reply contains the full comparable game state (see dump()).
--   {"cmd":"start","seed":"ABCD1234","deck":"Red Deck","stake":1}
--   {"cmd":"select_blind"} {"cmd":"skip_blind"} {"cmd":"reroll_boss"}
--   {"cmd":"play","cards":[0,1,2]}  {"cmd":"discard","cards":[3]}   (0-based)
--   {"cmd":"cash_out"} {"cmd":"reroll"} {"cmd":"end_shop"}
--   {"cmd":"buy","area":"shop_jokers","index":0,"use":false}
--   {"cmd":"use","index":0,"targets":[0,1]}   (consumable slot, hand targets)
--   {"cmd":"sell","area":"jokers","index":0}
--   {"cmd":"pick","index":0,"targets":[]}  {"cmd":"skip_pack"}
--   {"cmd":"move","area":"jokers","from":0,"to":2}
--   {"cmd":"state"} {"cmd":"quit"}
local here = debug.getinfo(1, 'S').source:match('^@(.*/)') or './'
local boot = dofile(here .. 'boot.lua')
local json = dofile(here .. 'json.lua')

local real_stdout = io.stdout
-- the game prints debug output; keep stdout clean for the protocol
print = function(...) io.stderr:write(table.concat({ ... }, '\t'), '\n') end

boot.init({ profile = os.getenv('ORACLE_PROFILE') or 'all' })
G.SETTINGS.GAMESPEED = tonumber(os.getenv('ORACLE_GAMESPEED') or '1')
local DT = tonumber(os.getenv('ORACLE_DT') or tostring(1 / 60))

local function fmt(x)
  if type(x) ~= 'number' then return x end
  return string.format('%.17g', x)
end

-- ------------------------------------------------------------ the profile
-- What the run adds to the player's profile, recorded as for an unseeded run
-- that isn't a challenge (the engine's G.PROFILE): the profile starts blank
-- at each run, and the game's "not seeded" checks around the stats are
-- skipped.  Nothing here changes the game.
local CAREER, HIGH = {}, { 'hand', 'furthest_round', 'furthest_ante', 'most_money', 'boss_streak' }

local function profile() return G.PROFILES[G.SETTINGS.profile] end

local function reset_profile()
  local p = profile()
  for k in pairs(p.career_stats) do p.career_stats[k] = 0 end
  for _, k in ipairs(HIGH) do p.high_scores[k].amt = 0 end
  p.joker_usage, p.voucher_usage = {}, {}
end

local function unseeded() return G.GAME.seeded or G.GAME.challenge end

-- ------------------------------------------------------------ unlocks (ORACLE_UNLOCKS=1)
-- The runs here are seeded (the oracle picks the seed), and a seeded run
-- unlocks nothing.  With ORACLE_UNLOCKS=1 the game's unlock and discovery
-- functions run as in an unseeded run (the engine's Game(seeded=False)), from
-- the boot profile again at every run, and the dump lists what each run
-- unlocked and discovered, in order.  The achievements are left out (the
-- engine has none) and the saves and notifications do nothing.
local UNLOCKS = os.getenv('ORACLE_UNLOCKS') == '1'
local progress = { unlocked = {}, discovered = {} }
local boot_flags = nil

local function as_unseeded(f, ...)
  local s = G.GAME.seeded
  G.GAME.seeded = nil
  local r = f(...)
  G.GAME.seeded = s
  return r
end

if UNLOCKS then
  local orig_unlock_card, orig_discover_card, orig_check = unlock_card, discover_card, check_for_unlock
  -- (listed before the call: what it unlocks or discovers in turn comes after)
  function unlock_card(card)
    if card.unlocked == false and not card.wip and not G.GAME.challenge then
      progress.unlocked[#progress.unlocked + 1] = card.key
    end
    as_unseeded(orig_unlock_card, card)
  end
  function discover_card(card)
    if card and card.key and not card.discovered and not card.wip and not G.GAME.challenge then
      progress.discovered[#progress.discovered + 1] = card.key
    end
    as_unseeded(orig_discover_card, card)
  end
  function check_for_unlock(args) return as_unseeded(orig_check, args) end
  function unlock_achievement() end
  function notify_alert() end
  function Game:save_notify() end
end

-- every run starts from the boot profile: the centers', tags' and blinds' flags, and G.P_LOCKED
local function reset_unlocks()
  if not UNLOCKS then return end
  local sets = { G.P_CENTERS, G.P_TAGS, G.P_BLINDS }
  if not boot_flags then
    boot_flags = {}
    for i, t in ipairs(sets) do
      boot_flags[i] = {}
      for k, v in pairs(t) do boot_flags[i][k] = { v.unlocked, v.discovered } end
    end
  end
  for i, t in ipairs(sets) do
    for k, v in pairs(t) do v.unlocked, v.discovered = boot_flags[i][k][1], boot_flags[i][k][2] end
  end
  G.P_LOCKED = {}
  for k, v in pairs(G.P_CENTERS) do
    if not v.unlocked and (string.find(k, '^j_') or string.find(k, '^b_') or string.find(k, '^v_')) then G.P_LOCKED[#G.P_LOCKED + 1] = v end
  end
  table.sort(G.P_LOCKED, function(a, b) return (a.order or 0) < (b.order or 0) end)
  local p = profile()
  p.deck_usage, p.challenge_progress = {}, { completed = {}, unlocked = {} }
  p.career_stats.c_round_interest_cap_streak, p.career_stats.c_single_hand_round_streak = 0, 0
  progress = { unlocked = {}, discovered = {} }
end

function inc_career_stat(stat, mod)
  local cs = profile().career_stats
  cs[stat] = (cs[stat] or 0) + (mod or 0)
end

function check_and_set_high_score(score, amt)
  if not amt or type(amt) ~= 'number' then return end
  if G.GAME.round_scores[score] and math.floor(amt) > G.GAME.round_scores[score].amt then
    G.GAME.round_scores[score].amt = math.floor(amt)
  end
  local hs = profile().high_scores[score]
  if hs and math.floor(amt) > hs.amt then hs.amt = math.floor(amt) end
end

local orig_win_game = win_game
function win_game()
  if unseeded() then
    set_joker_win()
    if UNLOCKS and not G.GAME.challenge then
      set_deck_win()
      for _, kind in ipairs({ 'win_no_hand', 'win_no', 'win_custom', 'win_deck', 'win_stake', 'win' }) do
        check_for_unlock({ type = kind })
      end
    end
    inc_career_stat('c_wins', 1)
  end
  return orig_win_game()
end

-- called once per won round, right after the boss streak and the single
-- hand streak (which the game only keeps for unseeded runs)
local orig_set_joker_usage = set_joker_usage
function set_joker_usage()
  if unseeded() then
    if G.GAME.blind:get_type() == 'Boss' then
      G.GAME.current_boss_streak = G.GAME.current_boss_streak + 1
      check_and_set_high_score('boss_streak', G.GAME.current_boss_streak)
    end
    if G.GAME.current_round.hands_played ~= 1 then profile().career_stats.c_single_hand_round_streak = 0 end
  end
  return orig_set_joker_usage()
end

local orig_add_round_eval_row = add_round_eval_row
function add_round_eval_row(config)
  if config.name == 'interest' and unseeded() then
    local cs = profile().career_stats
    if G.GAME.interest_amount*math.min(math.floor(G.GAME.dollars/5), G.GAME.interest_cap/5) == G.GAME.interest_amount*G.GAME.interest_cap/5 then
      cs.c_round_interest_cap_streak = cs.c_round_interest_cap_streak + 1
    else
      cs.c_round_interest_cap_streak = 0
    end
  end
  return orig_add_round_eval_row(config)
end

local orig_update_game_over = Game.update_game_over
function Game:update_game_over(dt)
  if not G.STATE_COMPLETE and G.GAME.round_resets.ante <= G.GAME.win_ante and unseeded() then
    inc_career_stat('c_losses', 1)
    if UNLOCKS and not G.GAME.challenge then set_deck_loss() end
    set_joker_loss()
  end
  return orig_update_game_over(self, dt)
end

local function profile_dump()
  local p = profile()
  local out = { career_stats = {}, high_scores = {}, joker_usage = {}, voucher_usage = {} }
  for k, v in pairs(p.career_stats) do out.career_stats[k] = v end
  for _, k in ipairs(HIGH) do out.high_scores[k] = fmt(p.high_scores[k].amt) end
  for k, v in pairs(p.joker_usage) do
    local u = { count = v.count, wins = {}, losses = {} }
    for st, n in pairs(v.wins or {}) do u.wins[tostring(st)] = n end
    for st, n in pairs(v.losses or {}) do u.losses[tostring(st)] = n end
    out.joker_usage[k] = u
  end
  for k, v in pairs(p.voucher_usage) do out.voucher_usage[k] = v.count end
  if UNLOCKS and not G.GAME.challenge then out.progress = { unlocked = progress.unlocked, discovered = progress.discovered } end
  return out
end

local function card_desc(c)
  local d = {
    key = c.config.center.key,
    sort_id = c.sort_id,
  }
  if c.ability.set == 'Default' or c.ability.set == 'Enhanced' then
    d.card = c.config.card_key
    d.perma_bonus = (c.ability.perma_bonus ~= 0) and c.ability.perma_bonus or nil
  end
  if c.edition then d.edition = c.edition.type end
  if c.seal then d.seal = c.seal end
  if c.debuff then d.debuff = true end
  if c.facing == 'back' then d.facing = 'back' end
  if c.ability.eternal then d.eternal = true end
  if c.ability.perishable then d.perishable = c.ability.perish_tally end
  if c.ability.rental then d.rental = true end
  if c.ability.forced_selection then d.forced = true end
  if c.highlighted then d.highlighted = true end
  d.cost = c.cost
  d.sell_cost = c.sell_cost
  if c.ability.set == 'Joker' then
    local a = {}
    for _, k in ipairs({ 'mult', 'x_mult', 'extra_value', 'caino_xmult', 'yorick_discards', 'invis_rounds',
      'to_do_poker_hand', 'loyalty_remaining', 'perish_tally' }) do
      if c.ability[k] ~= nil then a[k] = fmt(c.ability[k]) end
    end
    if type(c.ability.extra) == 'table' then
      for k, v in pairs(c.ability.extra) do if type(v) ~= 'table' then a['extra.' .. k] = fmt(v) end end
    elseif c.ability.extra ~= nil then
      a.extra = fmt(c.ability.extra)
    end
    d.ability = a
  end
  return d
end

local function area_desc(area)
  if not area or not area.cards then return nil end
  local out = {}
  for i, c in ipairs(area.cards) do out[i] = card_desc(c) end
  return out
end

local function sorted_keys(t)
  local ks = {}
  for k, v in pairs(t or {}) do if v then ks[#ks + 1] = k end end
  table.sort(ks)
  return ks
end

local function hands_order()
  local o = {}
  for k in pairs(G.GAME.hands) do o[#o + 1] = k end
  return o
end

local function dump()
  local GAME = G.GAME
  local s = {
    state = G.STATE,
    state_complete = G.STATE_COMPLETE,
    ante = GAME.round_resets.ante,
    round = GAME.round,
    dollars = GAME.dollars,
    chips = fmt(GAME.chips),
    hands_left = GAME.current_round.hands_left,
    discards_left = GAME.current_round.discards_left,
    hand_size = G.hand and G.hand.config.card_limit,
    joker_slots = G.jokers and G.jokers.config.card_limit,
    consumable_slots = G.consumeables and G.consumeables.config.card_limit,
    reroll_cost = GAME.current_round.reroll_cost,
    blind = GAME.blind and { name = GAME.blind.name, chips = fmt(GAME.blind.chips), disabled = GAME.blind.disabled } or nil,
    blind_on_deck = GAME.blind_on_deck,
    boss = GAME.round_resets.blind_choices.Boss,
    voucher = GAME.current_round.voucher,
    blind_tags = GAME.round_resets.blind_tags,
    blind_states = GAME.round_resets.blind_states,
    tags = {},
    deck = area_desc(G.deck), hand = area_desc(G.hand), discard = area_desc(G.discard), play = area_desc(G.play),
    jokers = area_desc(G.jokers), consumeables = area_desc(G.consumeables),
    shop_jokers = G.shop and area_desc(G.shop_jokers) or nil,
    shop_vouchers = G.shop and area_desc(G.shop_vouchers) or nil,
    shop_booster = G.shop and area_desc(G.shop_booster) or nil,
    pack_cards = G.pack_cards and not G.pack_cards.REMOVED and area_desc(G.pack_cards) or nil,
    pack_choices = GAME.pack_choices,
    hands = {},
    used_jokers = sorted_keys(GAME.used_jokers),
    used_vouchers = sorted_keys(GAME.used_vouchers),
    pool_flags = sorted_keys(GAME.pool_flags),
    current_round = {
      idol = GAME.current_round.idol_card and (GAME.current_round.idol_card.suit .. ':' .. GAME.current_round.idol_card.rank),
      mail = GAME.current_round.mail_card and GAME.current_round.mail_card.rank,
      ancient = GAME.current_round.ancient_card and GAME.current_round.ancient_card.suit,
      castle = GAME.current_round.castle_card and GAME.current_round.castle_card.suit,
      most_played = GAME.current_round.most_played_poker_hand,
      dollars = GAME.current_round.dollars,
    },
    rng = {},
    hands_order = hands_order(),
    round_scores = {},
    profile = profile_dump(),
  }
  for k, v in pairs(GAME.round_scores) do s.round_scores[k] = fmt(v.amt) end
  for i, t in ipairs(GAME.tags) do s.tags[i] = t.key end
  for k, v in pairs(GAME.hands) do
    s.hands[k] = { level = v.level, played = v.played, chips = v.chips, mult = v.mult, visible = v.visible }
  end
  for k, v in pairs(GAME.pseudorandom) do
    if k ~= 'seed' and k ~= 'hashed_seed' then s.rng[k] = fmt(v) end
  end
  return s
end

local function idle_frames_needed() return 4 end

local function is_settled()
  if G.CONTROLLER.locked then return false end
  for _, q in pairs(G.E_MANAGER.queues) do
    for _, e in ipairs(q) do
      if e.blocking and not e.no_delete then return false end
      if e.blockable and not e.no_delete then return false end
    end
  end
  return G.STATE_COMPLETE
end

local function settle(max_frames)
  local quiet = 0
  for _ = 1, max_frames or 100000 do
    -- winning opens a pausing overlay: press 'Endless' like a player would
    if G.SETTINGS.paused and G.OVERLAY_MENU and G.GAME.won and G.STATE ~= G.STATES.GAME_OVER then
      G.FUNCS.exit_overlay_menu()
    end
    boot.pump(1, DT)
    -- the run is over: the game stays paused on the game over screen
    if G.STATE == G.STATES.GAME_OVER and G.STATE_COMPLETE then return true end
    if is_settled() then
      quiet = quiet + 1
      if quiet >= idle_frames_needed() then return true end
    else
      quiet = 0
    end
  end
  return false
end

local function E(ref, extra)
  local e = { config = { ref_table = ref }, UIBox = {} }
  if extra then for k, v in pairs(extra) do e.config[k] = v end end
  e.UIBox.get_UIE_by_ID = function() return nil end
  return e
end

-- select exactly these cards (forced ones stay), then let the game settle,
-- as a player selects cards before pressing a button
local function highlight(area, idxs)
  area:unhighlight_all()
  for _, i in ipairs(idxs or {}) do
    local c = area.cards[i + 1]
    assert(c, 'no card at index ' .. tostring(i))
    local already = false
    for _, h in ipairs(area.highlighted) do if h == c then already = true end end
    if not already then area:add_to_highlighted(c, true) end
  end
  settle()
end

local handlers = {}

function handlers.start(cmd)
  -- every run starts from the same clock, so frame timings are reproducible
  G.TIMERS.TOTAL = 0
  G.TIMERS.REAL = 0
  G.E_MANAGER.queue_timer = 0
  G.E_MANAGER.queue_last_processed = 0
  G.ACC = 0
  G.last_materialized = nil
  reset_profile()
  reset_unlocks()
  boot.start_run({ seed = cmd.seed, deck = cmd.deck or 'Red Deck', stake = cmd.stake or 1, challenge = cmd.challenge })
end

function handlers.select_blind()
  local key = G.GAME.round_resets.blind_choices[G.GAME.blind_on_deck]
  G.FUNCS.select_blind(E(G.P_BLINDS[key]))
end

function handlers.skip_blind()
  local opt = G.blind_select_opts[string.lower(G.GAME.blind_on_deck)]
  local tag_ui = opt:get_UIE_by_ID('tag_container')
  local e = { UIBox = { get_UIE_by_ID = function() return tag_ui end }, config = {} }
  G.FUNCS.skip_blind(e)
end

function handlers.reroll_boss() G.FUNCS.reroll_boss(E(nil)) end

-- the run is continued from the main menu (Game:start_run with a save: its only effect on a run)
function handlers.continue() check_for_unlock({ type = 'continue_game' }) end

function handlers.play(cmd)
  highlight(G.hand, cmd.cards)
  G.FUNCS.play_cards_from_highlighted(E(nil))
end

function handlers.discard(cmd)
  highlight(G.hand, cmd.cards)
  G.FUNCS.discard_cards_from_highlighted(E(nil))
end

function handlers.cash_out() G.FUNCS.cash_out(E(nil)) end
function handlers.reroll() G.FUNCS.reroll_shop(E(nil)) end
function handlers.end_shop() G.FUNCS.toggle_shop(E(nil)) end

function handlers.buy(cmd)
  local area = G[cmd.area]
  local c = area.cards[cmd.index + 1]
  assert(c, 'nothing to buy at ' .. cmd.area .. '[' .. cmd.index .. ']')
  if cmd.area == 'shop_jokers' then
    G.FUNCS.buy_from_shop(E(c, { id = cmd.use and 'buy_and_use' or nil }))
  else
    G.FUNCS.use_card(E(c)) -- vouchers are redeemed, boosters opened
  end
end

function handlers.use(cmd)
  local c = G.consumeables.cards[cmd.index + 1]
  assert(c, 'no consumable at ' .. cmd.index)
  if cmd.targets then highlight(G.hand, cmd.targets) end
  G.FUNCS.use_card(E(c))
end

function handlers.sell(cmd)
  local c = G[cmd.area].cards[cmd.index + 1]
  assert(c, 'nothing to sell')
  G.FUNCS.sell_card(E(c))
end

function handlers.pick(cmd)
  local c = G.pack_cards.cards[cmd.index + 1]
  assert(c, 'no pack card at ' .. cmd.index)
  if cmd.targets then highlight(G.hand, cmd.targets) end
  G.FUNCS.use_card(E(c))
end

function handlers.skip_pack() G.FUNCS.skip_booster(E(nil)) end

function handlers.move(cmd)
  local area = G[cmd.area]
  local c = table.remove(area.cards, cmd.from + 1)
  table.insert(area.cards, cmd.to + 1, c)
  -- give the moved order fixed x positions so align_cards keeps it
  for i, card in ipairs(area.cards) do card.T.x = i end
  area:set_ranks()
end

function handlers.sort(cmd)
  if cmd.mode == 'suit' then G.FUNCS.sort_hand_suit() else G.FUNCS.sort_hand_value() end
end

function handlers.state() end

-- test helpers (no RNG involved)
function handlers.cheat(cmd)
  if cmd.dollars then G.GAME.dollars = cmd.dollars end
  if cmd.ante then G.GAME.round_resets.ante = cmd.ante; G.GAME.round_resets.blind_ante = cmd.ante end
  if cmd.boss then G.GAME.round_resets.blind_choices.Boss = cmd.boss end
  if cmd.win and G.STATE == G.STATES.SELECTING_HAND then
    G.GAME.chips = G.GAME.blind.chips
    G.STATE = G.STATES.NEW_ROUND
    G.STATE_COMPLETE = false
  end
end

function handlers.add_joker(cmd)
  add_joker(cmd.key, cmd.edition)
end

-- (an Orbital Tag needs a poker hand: given the way Double Tag copies get one)
function handlers.add_tag(cmd)
  if cmd.key == 'tag_orbital' then G.orbital_hand = cmd.orbital_hand or 'High Card' end
  add_tag(Tag(cmd.key))
  G.orbital_hand = nil
end

-- redeem a voucher for free (applied through a voucher card, as Reroll
-- Surplus/Glut need one)
function handlers.add_voucher(cmd)
  G.GAME.used_vouchers[cmd.key] = true
  local card = Card(0, 0, G.CARD_W, G.CARD_H, nil, G.P_CENTERS[cmd.key])
  card:apply_to_run()
  card:remove()
end

for line in io.lines() do
  local ok, cmd = pcall(json.decode, line)
  local reply
  if not ok or type(cmd) ~= 'table' then
    reply = { ok = false, error = 'bad json: ' .. tostring(cmd) }
  elseif cmd.cmd == 'quit' then
    break
  else
    local h = handlers[cmd.cmd]
    if not h then
      reply = { ok = false, error = 'unknown cmd ' .. tostring(cmd.cmd) }
    else
      local settled
      local ok2, err = xpcall(function()
        h(cmd)
        settled = settle(cmd.max_frames)
      end, debug.traceback)
      if ok2 then
        reply = { ok = true, settled = settled, state = dump() }
      else
        reply = { ok = false, error = tostring(err) }
      end
    end
  end
  real_stdout:write(json.encode(reply), '\n')
  real_stdout:flush()
end
