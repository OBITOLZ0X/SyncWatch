--[==========================================================================[
 syncwatch_osd.lua: SyncWatch OSD interface for VLC
 Reads a text file periodically and displays its contents as an OSD overlay.
 Set SYNCWATCH_OSD_FILE environment variable to the path of the text file.
--]==========================================================================]

local osd_file = os.getenv("SYNCWATCH_OSD_FILE") or ""
local channel = nil
local last_text = ""
local running = true

-- How often to check the file (in microseconds). 300ms = 300000
local check_interval = 300000

function read_osd()
    if osd_file == "" then return "" end
    local f = io.open(osd_file, "r")
    if not f then return "" end
    local text = f:read("*all")
    f:close()
    return (text or ""):match("^%s*(.-)%s*$") -- trim whitespace
end

function show_osd(text)
    local input = vlc.object.input()
    if input and vlc.osd and vlc.object.vout() then
        if not channel then
            channel = vlc.osd.channel_register()
        end
        -- Show at top-right, refresh faster than check_interval so text stays visible
        vlc.osd.message(text, channel, "top-right", 1000000)
    end
end

function clear_osd()
    local input = vlc.object.input()
    if input and vlc.osd and vlc.object.vout() and channel then
        vlc.osd.message("", channel, "top-right", 1)
    end
end

-- Main loop
while running do
    local ok, err = pcall(function()
        local text = read_osd()
        if text ~= "" then
            show_osd(text)
            last_text = text
        elseif last_text ~= "" then
            clear_osd()
            last_text = ""
        end
    end)
    if not ok then
        -- Ignore errors silently (VLC may not have input yet)
    end

    -- Check if VLC is still running
    if vlc.misc and vlc.misc.mwait and vlc.misc.mdate then
        vlc.misc.mwait(vlc.misc.mdate() + check_interval)
    else
        running = false
    end
end
