-- Emit RNG test vectors computed by the game's own functions (misc_functions.lua).
--   luajit tools/lua/rng_vectors.lua > vectors.json
local here = debug.getinfo(1, 'S').source:match('^@(.*/)') or './'
local json = dofile(here .. 'json.lua')
local SRC = os.getenv('BALATRO_SRC') or (here .. '../../../balatro_src')

-- misc_functions.lua only defines functions at top level
G = { GAME = { pseudorandom = {} } }
dofile(SRC .. '/functions/misc_functions.lua')

local out = { hashes = {}, streams = {}, randoms = {}, ints = {}, shuffles = {}, strings = {} }

local seeds = { 'TESTSEED', '11111111', 'ABCDEFGH', 'Z', 'O1O1O1O1', 'TUTORIAL', 'K5H8L4PZ', '7LB2WVPK' }
local keys = { 'shuffle', 'boss', 'Tag1', 'Voucher1', 'cdt1', 'rarity1sho', 'Joker1sho1', 'edisho1',
  'soul_Tarot1', 'nr1', 'cashout1', 'erratic', 'lucky_mult', 'Tag1_resample2', 'shop_pack1' }

-- pseudohash over assorted strings
for _, s in ipairs(seeds) do out.hashes[#out.hashes + 1] = { s, string.format('%.17g', pseudohash(s)) } end
for _, k in ipairs(keys) do
  for _, s in ipairs(seeds) do
    out.hashes[#out.hashes + 1] = { k .. s, string.format('%.17g', pseudohash(k .. s)) }
  end
end

-- pseudoseed streams: 25 successive values per (seed, key)
for _, s in ipairs(seeds) do
  G.GAME.pseudorandom = { seed = s, hashed_seed = pseudohash(s) }
  for _, k in ipairs(keys) do
    local vals = {}
    for i = 1, 25 do vals[i] = string.format('%.17g', pseudoseed(k)) end
    out.streams[#out.streams + 1] = { s, k, vals }
  end
end

-- math.randomseed(d); several draws
local ds = { 0, 0.5, 0.123456789, 0.9999999, 1e-9, 0.3333333333333, 12345.678, 0.7071067811865476 }
for i = 1, 40 do ds[#ds + 1] = (i * 0.618033988749895) % 1 end
for _, d in ipairs(ds) do
  math.randomseed(d)
  local vals = {}
  for i = 1, 12 do vals[i] = string.format('%.17g', math.random()) end
  out.randoms[#out.randoms + 1] = { string.format('%.17g', d), vals }
  math.randomseed(d)
  local ints = {}
  for i = 1, 12 do ints[i] = math.random(i * 7) end
  math.randomseed(d)
  local rng2 = {}
  for i = 1, 6 do rng2[i] = math.random(i, i * 9) end
  out.ints[#out.ints + 1] = { string.format('%.17g', d), ints, rng2 }
end

-- pseudoshuffle of 52 items
for _, s in ipairs(seeds) do
  G.GAME.pseudorandom = { seed = s, hashed_seed = pseudohash(s) }
  local list = {}
  for i = 1, 52 do list[i] = { sort_id = i } end
  pseudoshuffle(list, pseudoseed('shuffle'))
  local ids = {}
  for i = 1, 52 do ids[i] = list[i].sort_id end
  out.shuffles[#out.shuffles + 1] = { s, ids }
end

for i = 1, 20 do
  local d = (i * 0.137) % 1
  out.strings[#out.strings + 1] = { string.format('%.17g', d), random_string(8, d) }
end

print(json.encode(out))
