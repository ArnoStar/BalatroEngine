-- Minimal JSON encoder/decoder for the headless Balatro tooling.
local json = {}

local function is_array(t)
  local n = 0
  for k in pairs(t) do
    if type(k) ~= 'number' or k < 1 or k % 1 ~= 0 then return false end
    n = n + 1
  end
  for i = 1, n do
    if t[i] == nil then return false end
  end
  return true, n
end

local escapes = { ['"'] = '\\"', ['\\'] = '\\\\', ['\b'] = '\\b', ['\f'] = '\\f',
  ['\n'] = '\\n', ['\r'] = '\\r', ['\t'] = '\\t' }

local function encode_string(s)
  return '"' .. s:gsub('[%c"\\]', function(c)
    return escapes[c] or string.format('\\u%04x', c:byte())
  end) .. '"'
end

local function encode_number(x)
  if x ~= x then return '"nan"' end
  if x == math.huge then return '"inf"' end
  if x == -math.huge then return '"-inf"' end
  if x % 1 == 0 and math.abs(x) < 2 ^ 53 then return string.format('%d', x) end
  return string.format('%.17g', x)
end

local function encode(v, seen, sort_keys)
  local t = type(v)
  if t == 'nil' then return 'null' end
  if t == 'boolean' then return v and 'true' or 'false' end
  if t == 'number' then return encode_number(v) end
  if t == 'string' then return encode_string(v) end
  if t == 'table' then
    if seen[v] then error('json: cycle') end
    seen[v] = true
    local out = {}
    local arr, n = is_array(v)
    if arr and n > 0 then
      for i = 1, n do out[i] = encode(v[i], seen, sort_keys) end
      seen[v] = nil
      return '[' .. table.concat(out, ',') .. ']'
    end
    local keys = {}
    for k, val in pairs(v) do
      local vt = type(val)
      if vt ~= 'function' and vt ~= 'userdata' and vt ~= 'thread' then
        keys[#keys + 1] = k
      end
    end
    if sort_keys ~= false then
      table.sort(keys, function(a, b) return tostring(a) < tostring(b) end)
    end
    for _, k in ipairs(keys) do
      out[#out + 1] = encode_string(tostring(k)) .. ':' .. encode(v[k], seen, sort_keys)
    end
    seen[v] = nil
    return '{' .. table.concat(out, ',') .. '}'
  end
  return 'null'
end

function json.encode(v, sort_keys)
  return encode(v, {}, sort_keys)
end

-- decoder (enough for the oracle command protocol)
local function skip_ws(s, i)
  return s:find('[^ \t\r\n]', i) or #s + 1
end

local decode_value

local function decode_string(s, i)
  local out, j = {}, i + 1
  while true do
    local c = s:sub(j, j)
    if c == '"' then return table.concat(out), j + 1 end
    if c == '\\' then
      local e = s:sub(j + 1, j + 1)
      local map = { b = '\b', f = '\f', n = '\n', r = '\r', t = '\t', ['"'] = '"', ['\\'] = '\\', ['/'] = '/' }
      if e == 'u' then
        out[#out + 1] = string.char(tonumber(s:sub(j + 2, j + 5), 16) % 256)
        j = j + 6
      else
        out[#out + 1] = map[e]
        j = j + 2
      end
    else
      out[#out + 1] = c
      j = j + 1
    end
  end
end

function decode_value(s, i)
  i = skip_ws(s, i)
  local c = s:sub(i, i)
  if c == '{' then
    local t = {}
    i = skip_ws(s, i + 1)
    if s:sub(i, i) == '}' then return t, i + 1 end
    while true do
      local k
      k, i = decode_string(s, skip_ws(s, i))
      i = skip_ws(s, i)
      assert(s:sub(i, i) == ':', 'json: expected :')
      t[k], i = decode_value(s, i + 1)
      i = skip_ws(s, i)
      local d = s:sub(i, i)
      if d == '}' then return t, i + 1 end
      assert(d == ',', 'json: expected ,')
      i = i + 1
    end
  elseif c == '[' then
    local t = {}
    i = skip_ws(s, i + 1)
    if s:sub(i, i) == ']' then return t, i + 1 end
    while true do
      t[#t + 1], i = decode_value(s, i)
      i = skip_ws(s, i)
      local d = s:sub(i, i)
      if d == ']' then return t, i + 1 end
      assert(d == ',', 'json: expected ,')
      i = i + 1
    end
  elseif c == '"' then
    return decode_string(s, i)
  elseif s:sub(i, i + 3) == 'true' then return true, i + 4
  elseif s:sub(i, i + 4) == 'false' then return false, i + 5
  elseif s:sub(i, i + 3) == 'null' then return nil, i + 4
  else
    local num = s:match('^-?%d+%.?%d*[eE]?[-+]?%d*', i)
    return tonumber(num), i + #num
  end
end

function json.decode(s)
  local v = decode_value(s, 1)
  return v
end

return json
