-- Extract all static game data from the original Balatro source into JSON.
--   luajit tools/lua/extract_data.lua [out.json]
-- (set BALATRO_SRC to the extracted game directory if it isn't ../balatro_src)
local here = debug.getinfo(1, 'S').source:match('^@(.*/)') or './'
local boot = dofile(here .. 'boot.lua')
local json = dofile(here .. 'json.lua')

-- extract with prototype defaults so unlock state is preserved as shipped
boot.init({ profile = 'fresh' })

local function strip(t, drop)
  if type(t) ~= 'table' then return t end
  local out = {}
  for k, v in pairs(t) do
    if not (drop and drop[k]) then
      if type(v) == 'table' then out[k] = strip(v) else out[k] = v end
    end
  end
  return out
end

local function name_of(set, key)
  local ok, res = pcall(function() return localize { type = 'name_text', set = set, key = key } end)
  if ok and type(res) == 'string' and res ~= 'ERROR' then return res end
  return nil
end

local VISUAL = { pos = true, soul_pos = true, atlas = true, boss_colour = true, alerted = true,
  start_alerted = true, discovered = true, unlock_condition = false }

local data = { version = G.VERSION }

data.centers = {}
for k, v in pairs(G.P_CENTERS) do
  local c = strip(v, VISUAL)
  c.discovered = v.discovered
  c.display_name = v.set and name_of(v.set == 'Default' and 'Other' or v.set, k) or nil
  data.centers[k] = c
end

data.cards = {}
for k, v in pairs(G.P_CARDS) do data.cards[k] = strip(v, VISUAL) end

data.blinds = {}
for k, v in pairs(G.P_BLINDS) do
  local b = strip(v, VISUAL)
  b.display_name = name_of('Blind', k)
  data.blinds[k] = b
end

data.tags = {}
for k, v in pairs(G.P_TAGS) do
  local t = strip(v, VISUAL)
  t.discovered = v.discovered
  t.display_name = name_of('Tag', k)
  data.tags[k] = t
end

data.seals = {}
for k, v in pairs(G.P_SEALS) do data.seals[k] = strip(v, VISUAL) end

data.stakes = {}
for k, v in pairs(G.P_STAKES) do data.stakes[k] = strip(v, VISUAL) end

data.center_pools = {}
for pool, list in pairs(G.P_CENTER_POOLS) do
  local keys = {}
  for i, v in ipairs(list) do keys[i] = v.key end
  data.center_pools[pool] = keys
end

data.joker_rarity_pools = {}
for r = 1, 4 do
  local keys = {}
  for i, v in ipairs(G.P_JOKER_RARITY_POOLS[r]) do keys[i] = v.key end
  data.joker_rarity_pools[r] = keys
end

data.handlist = G.handlist
local game = G:init_game_object()
data.hands = strip(game.hands)
data.init_game = strip(game, { hands = true, round_scores = true, cards_played = true })
data.starting_params = get_starting_params()
data.challenges = strip(G.CHALLENGES)

data.poker_hand_names = {}
for _, h in ipairs(G.handlist) do
  data.poker_hand_names[h] = localize(h, 'poker_hands')
end

local out = arg[1] or (here .. '../../balatro/data/game_data.json')
local f = assert(io.open(out, 'w'))
f:write(json.encode(data))
f:close()
io.stderr:write('wrote ' .. out .. '\n')
