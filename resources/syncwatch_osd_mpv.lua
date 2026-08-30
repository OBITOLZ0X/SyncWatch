--[==========================================================================[
 syncwatch_osd_mpv.lua: SyncWatch OSD interface for MPV
 Reads a text file periodically and displays its contents as an OSD overlay.
 Set SYNCWATCH_OSD_FILE environment variable to the path of the text file.
--]==========================================================================]

local osd_file = os.getenv("SYNCWATCH_OSD_FILE") or ""
local last_text = ""

-- Confirm the script loaded
mp.msg.info("SyncWatch OSD script loaded. File: " .. osd_file)

-- Check the file every 300 ms
local check_interval = 0.300

local function show_osd(text)
    -- Duration: 1 second so the message overlays the next timer tick
    -- and never flickers off between checks.
    mp.osd_message(text, 1.0)
end

local function clear_osd()
    mp.osd_message("", 0.01)
end

mp.add_periodic_timer(check_interval, function()
    local ok, text = pcall(function()
        if osd_file == "" then return "" end
        local f = io.open(osd_file, "r")
        if not f then return "" end
        local content = f:read("*all")
        f:close()
        return (content or ""):match("^%s*(.-)%s*$")
    end)

    if not ok then return end

    if text ~= "" then
        if text ~= last_text then
            mp.msg.info("SyncWatch OSD: " .. text:gsub("\n", " | "))
        end
        show_osd(text)
        last_text = text
    elseif last_text ~= "" then
        clear_osd()
        last_text = ""
    end
end)
