-- Audio track preference for friend-library items (E-films / E-serial .strm on Bizon).
-- Loaded by server_proxy.conf (bizon_jellyfin_friend_redirect.conf) as
-- /data/nginx/custom/friend_audio.lua. Reference copy: packages/bizon_jellyfin_friend_audio.lua.
--
-- Remuxes on the friend's server often have a TrueHD/DTS track as the default one. TVs
-- cannot play those, so Jellyfin falls back to transcoding on Bizon, which pulls the whole
-- remux through Bizon's slow internet. When the default audio track is such a codec and a
-- track in the same language with E-AC3/AC3/AAC exists, we make that one the default
-- (item JSON + PlaybackInfo answer) and request it in PlaybackInfo, so direct play (and the
-- 302 to the friend's server) keeps working.
local cjson = require "cjson.safe"
cjson.decode_array_with_array_mt(true)

local M = {}
local HEAVY = { truehd = true, mlp = true, dts = true, ["dts-hd"] = true, dtshd = true,
                pcm_s16le = true, pcm_s24le = true, pcm_bluray = true, flac = true }
local LIGHT = { eac3 = 1, ac3 = 2, aac = 3 }

local function is_friend(ms)
  return type(ms) == "table" and type(ms.Path) == "string" and ms.Path:find("^https://jf%.ekachur%.xyz/") ~= nil
end
M.is_friend = is_friend

-- Query argument, case-insensitive
function M.arg(name)
  for k, v in pairs(ngx.req.get_uri_args()) do
    if k:lower() == name then return type(v) == "table" and v[1] or v end
  end
end

-- Item id from /Videos/<id>/... or /Items/<id>/..., without dashes
function M.item_id()
  local id = ngx.var.uri:match("^/[^/]+/([0-9a-fA-F%-]+)")
  if not id then return nil end
  id = id:gsub("-", ""):lower()
  if #id ~= 32 then return nil end
  return id
end

-- This Jellyfin rejects api_key in the query of /Items, so pass it on as a header
function M.auth_from_query()
  local tok = M.arg("api_key")
  if tok and not ngx.var.http_authorization then
    ngx.req.set_header("Authorization", 'MediaBrowser Token="' .. tok .. '"')
  end
end

-- Index of the better audio stream for this media source (and of the heavy default one),
-- or nil to leave it alone
function M.pick(ms)
  if not is_friend(ms) or type(ms.MediaStreams) ~= "table" then return nil end
  local audio = {}
  for _, s in ipairs(ms.MediaStreams) do
    if s.Type == "Audio" then audio[#audio + 1] = s end
  end
  local def
  for _, s in ipairs(audio) do if s.Index == ms.DefaultAudioStreamIndex then def = s end end
  if not def then for _, s in ipairs(audio) do if s.IsDefault == true then def = s; break end end end
  def = def or audio[1]
  if not def or not HEAVY[string.lower(def.Codec or "")] then return nil end
  local best, rank
  for _, s in ipairs(audio) do
    local r = LIGHT[string.lower(s.Codec or "")]
    if r and s.Language == def.Language and (not rank or r < rank) then best, rank = s, r end
  end
  if not best then return nil end
  return best.Index, def.Index
end

local function apply(ms, idx)
  ms.DefaultAudioStreamIndex = idx
  for _, s in ipairs(ms.MediaStreams) do
    if s.Type == "Audio" then s.IsDefault = (s.Index == idx) end
  end
end

-- Rewrite a JSON body (item, items list or PlaybackInfo answer). Returns new body or nil.
function M.fix_body(body)
  if not body or not body:find("jf.ekachur.xyz", 1, true) then return nil end
  local j = cjson.decode(body)
  if type(j) ~= "table" then return nil end
  local changed = false
  local function fix_sources(list)
    if type(list) ~= "table" then return end
    for _, ms in ipairs(list) do
      local idx = M.pick(ms)
      if idx then apply(ms, idx); changed = true end
    end
  end
  fix_sources(j.MediaSources)
  if type(j.Items) == "table" then
    for _, it in ipairs(j.Items) do fix_sources(it.MediaSources) end
  end
  if not changed then return nil end
  return cjson.encode(j)
end

-- Look the item up on Bizon with the client's credentials; returns its first media source
function M.lookup(id)
  local r = ngx.location.capture("/__jf_friend_lookup",
    { args = { ids = id, Fields = "MediaSources,Path", EnableImages = "false" } })
  if r.status ~= 200 then return nil, r.status end
  local j = cjson.decode(r.body)
  local it = j and j.Items and j.Items[1]
  return it and it.MediaSources and it.MediaSources[1], 200
end

-- PlaybackInfo without a device profile: makes Bizon analyse a not yet probed .strm
function M.probe(id)
  local r = ngx.location.capture("/__jf_friend_probe/" .. id, { method = ngx.HTTP_POST, body = "{}" })
  if r.status ~= 200 then return nil end
  local j = cjson.decode(r.body)
  return j and j.MediaSources and j.MediaSources[1]
end

-- Ask for audio track idx unless the client explicitly chose a track other than the default
function M.request_audio(idx, orig_default)
  local function want(cur)
    cur = tonumber(cur)
    return cur == nil or cur == orig_default
  end
  local args = ngx.req.get_uri_args()
  for k, v in pairs(args) do
    if k:lower() == "audiostreamindex" then
      if want(type(v) == "table" and v[1] or v) then args[k] = tostring(idx); ngx.req.set_uri_args(args) end
    end
  end
  ngx.req.read_body()
  local body = ngx.req.get_body_data()
  if not body then
    local f = ngx.req.get_body_file()
    if f then local h = io.open(f, "rb"); if h then body = h:read("*a"); h:close() end end
  end
  local j = body and body ~= "" and cjson.decode(body) or {}
  if type(j) ~= "table" then return end
  if want(j.AudioStreamIndex) then
    j.AudioStreamIndex = idx
    ngx.req.set_body_data(cjson.encode(j))
    ngx.req.set_header("Content-Type", "application/json")
    ngx.log(ngx.WARN, "friend audio: requested stream ", idx, " for ", ngx.var.uri)
  end
end

-- Body filter: collect the JSON answer and rewrite it at the end
function M.filter()
  local ctx = ngx.ctx
  ctx.friend_buf = ctx.friend_buf or {}
  if ngx.arg[1] and ngx.arg[1] ~= "" then table.insert(ctx.friend_buf, ngx.arg[1]) end
  if not ngx.arg[2] then ngx.arg[1] = nil; return end
  local body = table.concat(ctx.friend_buf)
  ngx.arg[1] = M.fix_body(body) or body
end

return M
