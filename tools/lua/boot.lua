-- Headless bootstrap for the original Balatro Lua source.
--
-- Loads the unmodified game code under plain LuaJIT with a stubbed `love`
-- table, so game logic (RNG, shop generation, scoring, ...) can be executed
-- without a window.  Used for data extraction and as a ground-truth oracle
-- for the Python engine.
--
--   local boot = dofile('tools/lua/boot.lua')
--   boot.init()            -- BALATRO_SRC env var or ../balatro_src
--   boot.start_run{seed='ABCD1234', deck='Red Deck', stake=1}
--   boot.pump(300)
local boot = {}

local script_dir = (debug.getinfo(1, 'S').source:match('^@(.*/)') or './')
boot.script_dir = script_dir

local function default_src()
  return os.getenv('BALATRO_SRC') or (script_dir .. '../../../balatro_src')
end

---------------------------------------------------------------------------
-- universal stub: every field access / call returns another stub
---------------------------------------------------------------------------
local stub_mt = {}
local function S(name) return setmetatable({ __stubname = name }, stub_mt) end
stub_mt.__index = function(t, k)
  local v = S(k)
  rawset(t, k, v)
  return v
end
stub_mt.__call = function() return S('ret') end
stub_mt.__add = function() return 0 end
stub_mt.__sub = function() return 0 end
stub_mt.__mul = function() return 0 end
stub_mt.__div = function() return 0 end
stub_mt.__unm = function() return 0 end
stub_mt.__concat = function(a, b)
  return (type(a) == 'string' and a or '') .. (type(b) == 'string' and b or '')
end

local TIME = 0

local function install_love(SRC)
  local function readfile(path)
    local f = io.open(SRC .. '/' .. path, 'rb')
    if not f then return nil end
    local s = f:read('*a')
    f:close()
    return s
  end

  love = S('love')
  love.system = { getOS = function() return 'Linux' end, openURL = function() end,
    getClipboardText = function() return '' end, setClipboardText = function() end }
  love.timer = { getTime = function() return TIME end, step = function() return 1 / 60 end,
    sleep = function() end, getFPS = function() return 60 end }
  love.window = S('window')
  love.window.getMode = function() return 1920, 1080, { fullscreen = false, display = 1, vsync = 1 } end
  love.window.getDesktopDimensions = function() return 1920, 1080 end
  love.window.getDisplayCount = function() return 1 end
  love.window.getDisplayName = function() return 'stub' end
  love.window.getFullscreenModes = function() return { { width = 1920, height = 1080 } } end
  love.window.toPixels = function(x) return x end
  love.window.getDPIScale = function() return 1 end
  love.graphics = S('graphics')
  love.graphics.getWidth = function() return 1920 end
  love.graphics.getHeight = function() return 1080 end
  love.graphics.getDimensions = function() return 1920, 1080 end
  love.graphics.getDPIScale = function() return 1 end
  love.graphics.isActive = function() return false end
  local function image_stub()
    local s = S('image')
    s.getDimensions = function() return 710, 950 end
    s.getWidth = function() return 710 end
    s.getHeight = function() return 950 end
    return s
  end
  love.graphics.newImage = function() return image_stub() end
  love.graphics.newCanvas = function() return image_stub() end
  love.graphics.newFont = function()
    local f = S('font')
    f.getWidth = function(_, text) return #tostring(text or '') * 10 end
    f.getHeight = function() return 20 end
    f.getLineHeight = function() return 1 end
    return f
  end
  love.graphics.setNewFont = love.graphics.newFont
  love.filesystem = {
    getInfo = function(path)
      local f = io.open(SRC .. '/' .. path, 'rb')
      if f then f:close(); return { type = 'file' } end
      return nil
    end,
    read = function(path) local s = readfile(path); return s, s and #s end,
    write = function() return true end,
    append = function() return true end,
    remove = function() return true end,
    createDirectory = function() return true end,
    getDirectoryItems = function() return {} end,
    getSaveDirectory = function() return '/nonexistent' end,
    getSourceBaseDirectory = function() return SRC end,
    load = function(path)
      local s = readfile(path)
      if not s then return nil end
      return loadstring(s, '@' .. path)
    end,
    setIdentity = function() end,
  }
  love.data = S('data')
  love.thread = S('thread')
  love.thread.getChannel = function()
    return { push = function() end, pop = function() return nil end, demand = function() return nil end,
      supply = function() end, peek = function() return nil end }
  end
  love.audio = S('audio')
  love.mouse = S('mouse')
  love.mouse.getPosition = function() return 0, 0 end
  love.keyboard = S('keyboard')
  love.keyboard.isDown = function() return false end
  love.joystick = S('joystick')
  love.joystick.getJoysticks = function() return {} end
  love.touch = { getTouches = function() return {} end }
  love.event = S('event')
  love.handlers = {}
  love.arg = { parseGameArguments = function(a) return a end }
end

local function load_game()
  -- same order as main.lua
  require "engine/object"
  bit = require "bit"
  require "engine/string_packer"
  require "engine/controller"
  require "back"
  require "tag"
  require "engine/event"
  require "engine/node"
  require "engine/moveable"
  require "engine/sprite"
  require "engine/animatedsprite"
  require "functions/misc_functions"
  require "game"
  require "globals"
  require "engine/ui"
  require "functions/UI_definitions"
  require "functions/state_events"
  require "functions/common_events"
  require "functions/button_callbacks"
  require "functions/misc_functions"
  require "functions/test_functions"
  require "card"
  require "cardarea"
  require "blind"
  require "card_character"
  require "engine/particles"
  require "engine/text"
  require "challenges"
end

local function install_headless_overrides()
  -- purely visual / platform code that needs a real window or audio device
  update_canvas_juice = function() end
  play_sound = function() end
  -- keep the controller's lock bookkeeping, drop cursor/input handling
  function Controller:update(dt)
    self.locked = false
    if G.screenwipe then self.locks.wipe = true else self.locks.wipe = false end
    self.locks.frame_set = nil
    self.locks.frame = nil
    for _, v in pairs(self.locks) do if v then self.locked = true end end
  end
end

function boot.check(ok, err)
  if not ok then error(err, 0) end
  return ok
end

local function try(f, ...)
  local args = { ... }
  return boot.check(xpcall(function() return f(unpack(args)) end, debug.traceback))
end

-- Load the game and run Game:start_up().  `profile` controls unlocks:
--   'all' (default) -> everything unlocked & discovered (seed-finder convention)
--   'fresh'         -> prototype defaults (a brand new profile)
function boot.init(opts)
  opts = opts or {}
  local SRC = opts.src or default_src()
  boot.src = SRC
  package.path = SRC .. '/?.lua;' .. package.path
  install_love(SRC)
  load_game()
  install_headless_overrides()
  try(function() G:start_up() end)
  G.F_SKIP_TUTORIAL = true
  G.F_NO_SAVING = true
  G.SETTINGS.tutorial_complete = true
  G.SETTINGS.tutorial_progress = nil
  if (opts.profile or 'all') == 'all' then
    for _, v in pairs(G.P_CENTERS) do v.unlocked = true; v.discovered = true; v.alerted = true end
    for _, v in pairs(G.P_BLINDS) do v.discovered = true; v.alerted = true end
    for _, v in pairs(G.P_TAGS) do v.discovered = true; v.alerted = true end
    for _, v in pairs(G.P_SEALS) do v.discovered = true; v.alerted = true end
  end
end

function boot.start_run(opts)
  opts = opts or {}
  -- like G.FUNCS.start_run: drop pending (splash/menu) events, delete the old run
  G.E_MANAGER:clear_queue()
  try(function() G:delete_run() end)
  G.GAME.viewed_back = { name = opts.deck or 'Red Deck' }
  local args = { seed = opts.seed, stake = opts.stake or 1 }
  if opts.challenge then
    for _, ch in ipairs(G.CHALLENGES) do
      if ch.id == opts.challenge then args.challenge = ch end
    end
    assert(args.challenge, 'unknown challenge ' .. tostring(opts.challenge))
  end
  try(function() G:start_run(args) end)
end

function boot.pump(n, dt)
  dt = dt or (1 / 60)
  for _ = 1, n or 1 do
    TIME = TIME + dt
    try(function() G:update(dt) end)
  end
end

boot.try = try
return boot
