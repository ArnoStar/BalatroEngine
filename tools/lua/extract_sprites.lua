-- Extract where every card, blind, tag, seal and stake is drawn in the game's
-- sprite sheets, for front ends that render with the game's own textures.
--   luajit tools/lua/extract_sprites.lua [out.json]
-- (set BALATRO_SRC to the extracted game directory if it isn't ../balatro_src)
--
-- Positions are in sprite cells (multiply by the atlas px/py); the atlas
-- choice follows Card:set_sprites, get_front_spriteinfo and the blind/tag UI.
local here = debug.getinfo(1, 'S').source:match('^@(.*/)') or './'
local boot = dofile(here .. 'boot.lua')
local json = dofile(here .. 'json.lua')

boot.init({ profile = 'fresh' })

local function pos(p)
  if type(p) ~= 'table' then return nil end
  return { x = p.x, y = p.y }
end

local function colour(c)
  if type(c) ~= 'table' or type(c[1]) ~= 'number' then return nil end
  return string.format('#%02x%02x%02x', math.floor(c[1] * 255 + 0.5), math.floor(c[2] * 255 + 0.5),
    math.floor(c[3] * 255 + 0.5))
end

local data = { version = G.VERSION, atlases = {}, centers = {}, cards = {}, blinds = {}, tags = {}, seals = {},
  stakes = {}, stickers = {} }

for _, list in ipairs({ G.asset_atli, G.animation_atli }) do
  for _, a in ipairs(list) do
    data.atlases[a.name] = { file = a.path:match('[^/]+$'), px = a.px, py = a.py, frames = a.frames }
  end
end

for k, v in pairs(G.P_CENTERS) do
  local atlas = v.atlas or ((v.set == 'Joker' or v.consumeable or v.set == 'Voucher') and v.set) or 'centers'
  data.centers[k] = { atlas = atlas, pos = pos(v.pos), soul_pos = pos(v.soul_pos) }
end

for k, v in pairs(G.P_CARDS) do
  data.cards[k] = { atlas = 'cards_1', atlas_high_contrast = 'cards_2', pos = pos(v.pos) }
end

for k, v in pairs(G.P_BLINDS) do
  data.blinds[k] = { atlas = 'blind_chips', pos = pos(v.pos), colour = colour(v.boss_colour) }
end

for k, v in pairs(G.P_TAGS) do
  data.tags[k] = { atlas = v.atlas or 'tags', pos = pos(v.pos) }
end

-- (Planet and Spectral cards share the Tarot sheet: game.lua aliases them)
data.atlases.Planet = data.atlases.Tarot
data.atlases.Spectral = data.atlases.Tarot

local function sprite_pos(sprite)
  return type(sprite) == 'table' and pos(rawget(sprite, 'sprite_pos')) or nil
end

for k, v in pairs(G.P_SEALS) do
  data.seals[k] = { atlas = 'centers', pos = pos(v.pos) or sprite_pos(G.shared_seals[k]) }
end

data.stickers = {
  eternal = { atlas = 'stickers', pos = sprite_pos(G.shared_sticker_eternal) },
  perishable = { atlas = 'stickers', pos = sprite_pos(G.shared_sticker_perishable) },
  rental = { atlas = 'stickers', pos = sprite_pos(G.shared_sticker_rental) },
  debuff = { atlas = 'centers', pos = sprite_pos(G.shared_debuff) },
}

for k, v in pairs(G.P_STAKES) do
  data.stakes[k] = { atlas = v.atlas or 'chips', pos = pos(v.pos) }
end

local out = arg[1] or (here .. '../../balatro/data/sprites.json')
local f = assert(io.open(out, 'w'))
f:write(json.encode(data))
f:close()
io.stderr:write('wrote ' .. out .. '\n')
