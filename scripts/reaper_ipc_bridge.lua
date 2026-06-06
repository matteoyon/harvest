-- reaper_ipc_bridge.lua
-- Runs inside REAPER as a deferred ReaScript.
-- Polls /tmp/harvest_cmd.json, executes REAPER API calls, writes to /tmp/harvest_result.json.

local CMD_PATH    = "/tmp/harvest_cmd.json"
local RESULT_PATH = "/tmp/harvest_result.json"
local POLL_MS     = 50
local last_id     = nil  -- initialised after read_file is defined (see below)

-- ---------------------------------------------------------------------------
-- Minimal JSON encode/decode (flat objects and arrays only)
-- ---------------------------------------------------------------------------

local function json_encode(val)
    local t = type(val)
    if val == nil  then return "null" end
    if t == "boolean" then return val and "true" or "false" end
    if t == "number"  then return tostring(val) end
    if t == "string"  then
        return '"' .. val:gsub('\\','\\\\'):gsub('"','\\"'):gsub('\n','\\n'):gsub('\r','\\r') .. '"'
    end
    if t == "table" then
        -- array vs object heuristic
        if #val > 0 then
            local parts = {}
            for _, v in ipairs(val) do parts[#parts+1] = json_encode(v) end
            return "[" .. table.concat(parts, ",") .. "]"
        else
            local parts = {}
            for k, v in pairs(val) do
                parts[#parts+1] = json_encode(tostring(k)) .. ":" .. json_encode(v)
            end
            return "{" .. table.concat(parts, ",") .. "}"
        end
    end
    return "null"
end

local function json_decode(s)
    -- Use REAPER's built-in JSON if available (REAPER 6.44+), else minimal parser
    if reaper.APIExists("JSON_Decode") then
        local ok, val = reaper.JSON_Decode(s)
        if ok then return val end
    end
    -- Minimal recursive-descent parser for our known shapes
    local pos = 1
    local function skip() while pos <= #s and s:sub(pos,pos):match("%s") do pos=pos+1 end end
    local parse  -- forward decl
    local function parse_string()
        pos = pos + 1  -- skip opening "
        local buf = {}
        while pos <= #s do
            local c = s:sub(pos,pos)
            if c == '"' then pos=pos+1; break end
            if c == '\\' then
                pos=pos+1; c=s:sub(pos,pos)
                local esc = {['"']='"',['\\']='\\',['/']=  '/',['n']='\n',['r']='\r',['t']='\t'}
                buf[#buf+1] = esc[c] or c
            else buf[#buf+1] = c end
            pos=pos+1
        end
        return table.concat(buf)
    end
    local function parse_number()
        local n,e = s:match("^(-?%d+%.?%d*[eE]?[+-]?%d*)()", pos)
        pos = e; return tonumber(n)
    end
    local function parse_object()
        local obj = {}; pos=pos+1  -- skip {
        skip()
        if s:sub(pos,pos) == '}' then pos=pos+1; return obj end
        while true do
            skip(); local k = parse_string(); skip()
            pos=pos+1  -- skip :
            skip(); obj[k] = parse(); skip()
            if s:sub(pos,pos) == ',' then pos=pos+1 else break end
        end
        pos=pos+1; return obj  -- skip }
    end
    local function parse_array()
        local arr = {}; pos=pos+1  -- skip [
        skip()
        if s:sub(pos,pos) == ']' then pos=pos+1; return arr end
        while true do
            skip(); arr[#arr+1] = parse(); skip()
            if s:sub(pos,pos) == ',' then pos=pos+1 else break end
        end
        pos=pos+1; return arr  -- skip ]
    end
    parse = function()
        skip()
        local c = s:sub(pos,pos)
        if c == '"' then return parse_string()
        elseif c == '{' then return parse_object()
        elseif c == '[' then return parse_array()
        elseif c == 't' then pos=pos+4; return true
        elseif c == 'f' then pos=pos+5; return false
        elseif c == 'n' then pos=pos+4; return nil
        else return parse_number() end
    end
    return parse()
end

-- ---------------------------------------------------------------------------
-- File helpers
-- ---------------------------------------------------------------------------

local function read_file(path)
    local f = io.open(path, "r")
    if not f then return nil end
    local s = f:read("*a"); f:close()
    return s
end

local function write_file(path, content)
    local tmp = path .. ".tmp"
    local f = io.open(tmp, "w")
    if not f then return end
    f:write(content); f:close()
    os.rename(tmp, path)
end

-- Consume any stale cmd file on startup so we don't re-run old commands
-- (read_file and json_decode are now defined above)
do
    local stale_raw = read_file(CMD_PATH)
    if stale_raw then
        local ok, stale = pcall(json_decode, stale_raw)
        if ok and stale then last_id = stale.id end
    end
end

-- ---------------------------------------------------------------------------
-- Tool handlers (REAPER API)
-- ---------------------------------------------------------------------------

local function get_project_state(params)
    local proj = reaper.EnumProjects(-1)
    local name = reaper.GetProjectName(proj, "")
    local bpm,_  = reaper.GetProjectTimeSignature2(proj)
    local num,den = reaper.TimeMap_GetTimeSigAtTime(proj, 0)
    local sr = reaper.GetSetProjectInfo(proj, "PROJECT_SRATE", 0, false)
    local cursor = reaper.GetCursorPosition()
    local length = reaper.GetProjectLength(proj)

    local tracks = {}
    for i = 0, reaper.CountTracks(proj)-1 do
        local tr = reaper.GetTrack(proj, i)
        local _, tname = reaper.GetTrackName(tr)
        local vol,pan = reaper.GetTrackUIVolPan(tr, 0, 0)
        local vol_db = 20 * math.log(math.max(vol, 1e-10)) / math.log(10)
        local muted  = reaper.GetMediaTrackInfo_Value(tr, "B_MUTE") == 1
        local soloed = reaper.GetMediaTrackInfo_Value(tr, "I_SOLO") ~= 0
        local color  = reaper.GetTrackColor(tr)
        local hex    = string.format("#%06X", color)

        local fx_list = {}
        for fi = 0, reaper.TrackFX_GetCount(tr)-1 do
            local _, fname = reaper.TrackFX_GetFXName(tr, fi, "")
            fx_list[#fx_list+1] = {idx=fi, name=fname, enabled=reaper.TrackFX_GetEnabled(tr,fi)}
        end

        local items = {}
        for ii = 0, reaper.CountTrackMediaItems(tr)-1 do
            local item = reaper.GetTrackMediaItem(tr, ii)
            local start = reaper.GetMediaItemInfo_Value(item, "D_POSITION")
            local len   = reaper.GetMediaItemInfo_Value(item, "D_LENGTH")
            items[#items+1] = {id="i"..ii, start=start, len=len, type="audio"}
        end

        tracks[#tracks+1] = {
            id=i, name=tname, vol_db=math.floor(vol_db*10+0.5)/10,
            pan=pan, muted=muted, soloed=soloed, color=hex, fx=fx_list, sends={}, items=items
        }
    end

    return {
        project={name=name,bpm=bpm,time_sig=num.."/"..den,
                 sample_rate=sr,cursor=cursor,length=length},
        tracks=tracks
    }
end

local function list_tracks(params)
    local proj = reaper.EnumProjects(-1)
    local out = {}
    for i = 0, reaper.CountTracks(proj)-1 do
        local tr = reaper.GetTrack(proj, i)
        local _, tname = reaper.GetTrackName(tr)
        out[#out+1] = {id=i, name=tname}
    end
    return {tracks=out}
end

local function add_track(params)
    local name  = params.name or "New Track"
    local color = params.color or "#888888"
    local proj  = reaper.EnumProjects(-1)
    local idx   = reaper.CountTracks(proj)
    reaper.InsertTrackAtIndex(idx, true)
    local tr = reaper.GetTrack(proj, idx)
    reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", name, true)
    local r = tonumber("0x"..color:sub(2,3)) or 0
    local g = tonumber("0x"..color:sub(4,5)) or 0
    local b = tonumber("0x"..color:sub(6,7)) or 0
    reaper.SetTrackColor(tr, reaper.ColorToNative(r,g,b))
    reaper.UpdateArrange()
    return {id=idx, name=name}
end

local function delete_track(params)
    local proj = reaper.EnumProjects(-1)
    local tr = reaper.GetTrack(proj, params.track_id)
    if not tr then return {deleted=0} end
    reaper.DeleteTrack(tr)
    reaper.UpdateArrange()
    return {deleted=1}
end

local function rename_track(params)
    local proj = reaper.EnumProjects(-1)
    local tr = reaper.GetTrack(proj, params.track_id)
    if not tr then error("Track not found") end
    reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", params.name, true)
    reaper.UpdateArrange()
    return {id=params.track_id, name=params.name}
end

local function set_track_volume(params)
    local proj = reaper.EnumProjects(-1)
    local tr = reaper.GetTrack(proj, params.track_id)
    if not tr then error("Track not found") end
    local vol = 10^(params.vol_db/20)
    reaper.SetMediaTrackInfo_Value(tr, "D_VOL", vol)
    reaper.UpdateArrange()
    return {id=params.track_id, vol_db=params.vol_db}
end

local function insert_midi_item(params)
    local proj = reaper.EnumProjects(-1)
    local tr = reaper.GetTrack(proj, params.track_id)
    if not tr then error("Track not found") end
    local start  = params.start or 0.0
    local length = params.length or 4.0
    local item = reaper.CreateNewMIDIItemInProj(tr, start, start+length)
    local item_id = "i"..reaper.CountTrackMediaItems(tr)-1
    reaper.UpdateArrange()
    return {item_id=item_id, track_id=params.track_id, start=start, len=length}
end

local function add_midi_note(params)
    local proj = reaper.EnumProjects(-1)
    local tr = reaper.GetTrack(proj, params.track_id)
    if not tr then error("Track not found") end
    -- Find item by position (we use item index embedded in id "iN")
    local item_idx = tonumber(params.item_id:match("i(%d+)")) or 0
    local item = reaper.GetTrackMediaItem(tr, item_idx)
    if not item then error("Item not found") end
    local take = reaper.GetActiveTake(item)
    if not take or not reaper.TakeIsMIDI(take) then error("Not a MIDI take") end

    local bpm = select(1, reaper.GetProjectTimeSignature2(reaper.EnumProjects(-1)))
    local beat_len = 60.0 / bpm
    local item_start = reaper.GetMediaItemInfo_Value(item, "D_POSITION")
    local note_start = item_start + (params.start_beat or 0) * beat_len
    local note_end   = note_start + (params.duration_beats or 1) * beat_len

    reaper.MIDI_InsertNote(take, false, false,
        reaper.TimeMap2_timeToBeats(nil, note_start),
        reaper.TimeMap2_timeToBeats(nil, note_end),
        0, params.pitch, params.velocity or 100, false)
    reaper.MIDI_Sort(take)
    reaper.UpdateArrange()
    return {added={pitch=params.pitch, start_beat=params.start_beat,
                   duration_beats=params.duration_beats, velocity=params.velocity or 100}}
end

local function add_fx(params)
    local proj = reaper.EnumProjects(-1)
    local tr = reaper.GetTrack(proj, params.track_id)
    if not tr then error("Track not found") end
    local idx = reaper.TrackFX_AddByName(tr, params.fx_name, false, -1)
    if idx < 0 then error("FX not found: " .. params.fx_name) end
    return {track_id=params.track_id, fx_idx=idx, name=params.fx_name}
end

local function transport_play(params)
    reaper.OnPlayButton()
    return {status="playing"}
end

local function transport_stop(params)
    reaper.OnStopButton()
    return {status="stopped"}
end

local HANDLERS = {
    get_project_state = get_project_state,
    list_tracks       = list_tracks,
    add_track         = add_track,
    delete_track      = delete_track,
    rename_track      = rename_track,
    set_track_volume  = set_track_volume,
    insert_midi_item  = insert_midi_item,
    add_midi_note     = add_midi_note,
    add_fx            = add_fx,
    play              = transport_play,
    stop              = transport_stop,
}

-- ---------------------------------------------------------------------------
-- Deferred polling loop
-- ---------------------------------------------------------------------------

local function tick()
    -- Wrap everything in pcall: any Lua error here must NOT kill the defer loop.
    local ok, err = pcall(function()
        local raw = read_file(CMD_PATH)
        if not raw then return end

        local dok, cmd = pcall(json_decode, raw)
        if not (dok and cmd and cmd.id and cmd.id ~= last_id) then return end

        last_id = cmd.id
        local handler = HANDLERS[cmd.tool]
        local resp
        if not handler then
            resp = {id=cmd.id, ok=false, error="Unknown tool: "..(cmd.tool or "?")}
        else
            local success, result = pcall(handler, cmd.params or {})
            if success then
                resp = {id=cmd.id, ok=true, result=result}
            else
                resp = {id=cmd.id, ok=false, error=tostring(result)}
            end
        end
        write_file(RESULT_PATH, json_encode(resp))
    end)

    if not ok then
        reaper.ShowConsoleMsg("[harvest] bridge error: " .. tostring(err) .. "\n")
    end

    reaper.defer(tick)
end

tick()
