-- Remote Spy Pro v2 - Mobile Friendly + Grouped Counts
-- Execute with Script Executor

local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local UserInputService = game:GetService("UserInputService")
local TweenService = game:GetService("TweenService")

local Player = Players.LocalPlayer

local spyEnabled = false
local blockEnabled = false
local minimized = false
local autoBlockSpam = false
local spamThreshold = 50
local totalCalls = 0
local blockedCalls = 0

-- Grouped data: remoteName -> {count, lastArgs, lastCode, type, path, class, blocked, lastTime}
local remoteData = {}
local remoteOrder = {} -- ordered list of remote names for display
local blockedRemotes = {}
local ignoredRemotes = {}
local selectedRemote = nil

local hasHookMeta = type(hookmetamethod) == "function"
local hasHookFunc = type(hookfunction) == "function"
local hasNewCC = type(newcclosure) == "function"
local hasGetNM = type(getnamecallmethod) == "function"
local hasClipboard = type(setclipboard) == "function" or type(toclipboard) == "function"
local hasCheckcaller = type(checkcaller) == "function"
local hasGetInfo = type(debug) == "table" and type(debug.getinfo) == "function"

local function toClip(t)
	if setclipboard then setclipboard(t)
	elseif toclipboard then toclipboard(t) end
end

-- ========================
-- SERIALIZE
-- ========================
local function ser(v, d)
	d = d or 0
	if d > 3 then return "..." end
	local t = typeof(v)
	if t == "string" then return '"' .. v:sub(1, 60):gsub('"', '\\"'):gsub("\n", "\\n") .. '"'
	elseif t == "number" then return v == math.floor(v) and tostring(v) or string.format("%.4f", v)
	elseif t == "boolean" then return tostring(v)
	elseif t == "nil" then return "nil"
	elseif t == "Instance" then return v:GetFullName()
	elseif t == "Vector3" then return string.format("Vector3.new(%.2f,%.2f,%.2f)", v.X, v.Y, v.Z)
	elseif t == "CFrame" then local p = v.Position return string.format("CFrame.new(%.2f,%.2f,%.2f,...)", p.X, p.Y, p.Z)
	elseif t == "Color3" then return string.format("Color3.new(%.2f,%.2f,%.2f)", v.R, v.G, v.B)
	elseif t == "EnumItem" then return tostring(v)
	elseif t == "UDim2" then return string.format("UDim2.new(%.2f,%d,%.2f,%d)", v.X.Scale, v.X.Offset, v.Y.Scale, v.Y.Offset)
	elseif t == "table" then
		local p = {}; local c = 0
		for k, val in pairs(v) do
			c += 1; if c > 6 then table.insert(p, "..."); break end
			local key = type(k) == "number" and "[" .. k .. "]" or tostring(k)
			table.insert(p, key .. "=" .. ser(val, d + 1))
		end
		return "{" .. table.concat(p, ", ") .. "}"
	else return t .. ":" .. tostring(v) end
end

local function serArgs(args)
	if #args == 0 then return "(none)" end
	local p = {}
	for i, v in ipairs(args) do p[i] = "[" .. i .. "]=" .. ser(v) end
	return table.concat(p, "\n")
end

local function genCode(name, path, callType, args)
	local lines = {}
	if #args == 0 then
		table.insert(lines, "local args = {}")
	else
		table.insert(lines, "local args = {")
		for i, v in ipairs(args) do
			local comma = i < #args and "," or ""
			table.insert(lines, "  [" .. i .. "] = " .. ser(v) .. comma)
		end
		table.insert(lines, "}")
	end
	table.insert(lines, 'game:GetService("ReplicatedStorage").' .. path .. ":" .. callType .. "(unpack(args))")
	return table.concat(lines, "\n")
end

-- ========================
-- GET PATH
-- ========================
local function getPath(remote)
	local p = {}
	local c = remote
	while c and c ~= game do
		table.insert(p, 1, c.Name); c = c.Parent
	end
	if p[1] == "ReplicatedStorage" then table.remove(p, 1) end
	return table.concat(p, ".")
end

-- ========================
-- TRACEBACK
-- ========================
local function getTrace()
	if not hasGetInfo then return nil end
	local t = {}
	for i = 4, 7 do
		local ok, info = pcall(debug.getinfo, i)
		if not ok or not info then break end
		table.insert(t, (info.source or "?") .. ":" .. (info.currentline or "?"))
	end
	return #t > 0 and table.concat(t, " → ") or nil
end

-- ========================
-- ADD LOG (grouped by remote name)
-- ========================
local function addLog(remote, callType, args, wasBlocked)
	local name = remote.Name
	if ignoredRemotes[name] then return end

	totalCalls += 1
	if wasBlocked then blockedCalls += 1 end

	local path = getPath(remote)

	if not remoteData[name] then
		remoteData[name] = {
			count = 0,
			name = name,
			path = path,
			class = remote.ClassName,
			type = callType,
			lastArgs = {},
			lastCode = "",
			lastTime = "",
			lastTrace = nil,
			blocked = false,
			perSec = 0,
			secTimer = os.clock(),
			secCount = 0,
		}
		table.insert(remoteOrder, name)
	end

	local data = remoteData[name]
	data.count += 1
	data.lastArgs = args
	data.lastCode = genCode(name, path, callType, args)
	data.lastTime = os.date("%H:%M:%S")
	data.type = callType
	data.blocked = wasBlocked
	data.lastTrace = getTrace()

	-- Per second tracking
	local now = os.clock()
	if now - data.secTimer > 1 then
		data.perSec = data.secCount
		data.secCount = 0
		data.secTimer = now

		if autoBlockSpam and data.perSec >= spamThreshold then
			blockedRemotes[name] = true
		end
	end
	data.secCount += 1
end

-- ========================
-- HOOKS
-- ========================
local hookActive = false

local function setupHooks()
	if hookActive then return "none" end

	if hasHookMeta and hasGetNM and hasNewCC then
		local old
		old = hookmetamethod(game, "__namecall", newcclosure(function(self, ...)
			if hasCheckcaller and checkcaller() then return old(self, ...) end
			local m = getnamecallmethod()
			local a = {...}
			if spyEnabled then
				if m == "FireServer" and self:IsA("RemoteEvent") then
					local b = blockedRemotes[self.Name] == true and blockEnabled
					addLog(self, "FireServer", a, b)
					if b then return end
				elseif m == "InvokeServer" and self:IsA("RemoteFunction") then
					local b = blockedRemotes[self.Name] == true and blockEnabled
					addLog(self, "InvokeServer", a, b)
					if b then return nil end
				elseif m == "Fire" and self:IsA("BindableEvent") then
					local b = blockedRemotes[self.Name] == true and blockEnabled
					addLog(self, "Fire", a, b)
					if b then return end
				elseif m == "Invoke" and self:IsA("BindableFunction") then
					local b = blockedRemotes[self.Name] == true and blockEnabled
					addLog(self, "Invoke", a, b)
					if b then return nil end
				end
			end
			return old(self, ...)
		end))
		hookActive = true
		return "namecall"
	end

	if hasHookFunc and hasNewCC then
		pcall(function()
			local r = Instance.new("RemoteEvent")
			local o = r.FireServer
			hookfunction(o, newcclosure(function(self, ...)
				if hasCheckcaller and checkcaller() then return o(self, ...) end
				if spyEnabled and self:IsA("RemoteEvent") then
					local a = {...}
					local b = blockedRemotes[self.Name] == true and blockEnabled
					addLog(self, "FireServer", a, b)
					if b then return end
				end
				return o(self, ...)
			end))
			r:Destroy()
		end)
		hookActive = true
		return "hookfunc"
	end

	-- Fallback: OnClientEvent only
	local function hookOCE(r)
		pcall(function()
			r.OnClientEvent:Connect(function(...)
				if spyEnabled then addLog(r, "OnClientEvent", {...}, false) end
			end)
		end)
	end
	for _, d in ipairs(game:GetDescendants()) do
		if d:IsA("RemoteEvent") then hookOCE(d) end
	end
	game.DescendantAdded:Connect(function(d)
		if d:IsA("RemoteEvent") then hookOCE(d) end
	end)
	hookActive = true
	return "listener"
end

local hookMethod = setupHooks()

-- ========================
-- COLORS
-- ========================
local C = {
	bg = Color3.fromRGB(10, 10, 16),
	bar = Color3.fromRGB(16, 16, 26),
	barAcc = Color3.fromRGB(200, 40, 40),
	acc = Color3.fromRGB(200, 40, 40),
	accAlt = Color3.fromRGB(40, 130, 200),
	on = Color3.fromRGB(30, 160, 65),
	off = Color3.fromRGB(160, 30, 30),
	txt = Color3.fromRGB(210, 210, 225),
	dim = Color3.fromRGB(75, 75, 95),
	sec = Color3.fromRGB(13, 13, 22),
	brd = Color3.fromRGB(30, 30, 44),
	logBg = Color3.fromRGB(8, 8, 14),
	hover = Color3.fromRGB(22, 22, 36),
	fire = Color3.fromRGB(255, 120, 40),
	invoke = Color3.fromRGB(70, 170, 255),
	onclient = Color3.fromRGB(70, 230, 100),
	bind = Color3.fromRGB(180, 130, 255),
	blocked = Color3.fromRGB(255, 35, 35),
	spam = Color3.fromRGB(255, 190, 30),
	tabA = Color3.fromRGB(200, 40, 40),
	tabI = Color3.fromRGB(20, 20, 32),
	tabTA = Color3.fromRGB(255, 255, 255),
	tabTI = Color3.fromRGB(65, 65, 85),
}

-- ========================
-- GUI
-- ========================
local Gui = Instance.new("ScreenGui")
Gui.Name = "RSP"
Gui.ResetOnSpawn = false
Gui.ZIndexBehavior = Enum.ZIndexBehavior.Sibling
Gui.Parent = Player:WaitForChild("PlayerGui")

local Main = Instance.new("Frame")
Main.Size = UDim2.new(0, 280, 0, 380)
Main.Position = UDim2.new(0.5, -140, 0.5, -190)
Main.BackgroundColor3 = C.bg
Main.BorderSizePixel = 0
Main.Active = true
Main.Parent = Gui
Instance.new("UICorner", Main).CornerRadius = UDim.new(0, 8)
Instance.new("UIStroke", Main).Color = C.brd

local Bar = Instance.new("Frame")
Bar.Size = UDim2.new(1, 0, 0, 30)
Bar.BackgroundColor3 = C.bar
Bar.BorderSizePixel = 0
Bar.Parent = Main
Instance.new("UICorner", Bar).CornerRadius = UDim.new(0, 8)
local bf = Instance.new("Frame"); bf.Size = UDim2.new(1, 0, 0, 8); bf.Position = UDim2.new(0, 0, 1, -8); bf.BackgroundColor3 = C.bar; bf.BorderSizePixel = 0; bf.Parent = Bar
local al = Instance.new("Frame"); al.Size = UDim2.new(1, -12, 0, 1); al.Position = UDim2.new(0, 6, 1, -1); al.BackgroundColor3 = C.barAcc; al.BorderSizePixel = 0; al.Parent = Bar

local lg = Instance.new("TextLabel"); lg.Size = UDim2.new(1, -36, 1, 0); lg.Position = UDim2.new(0, 8, 0, 0)
lg.BackgroundTransparency = 1; lg.Text = "🔍 Remote Spy"; lg.TextColor3 = C.txt; lg.TextSize = 12
lg.Font = Enum.Font.GothamBold; lg.TextXAlignment = Enum.TextXAlignment.Left; lg.Parent = Bar

local MinBtn = Instance.new("TextButton"); MinBtn.Size = UDim2.new(0, 22, 0, 22); MinBtn.Position = UDim2.new(1, -28, 0, 4)
MinBtn.BackgroundColor3 = C.acc; MinBtn.Text = "—"; MinBtn.TextColor3 = C.txt; MinBtn.TextSize = 12
MinBtn.Font = Enum.Font.GothamBold; MinBtn.BorderSizePixel = 0; MinBtn.Parent = Bar
Instance.new("UICorner", MinBtn).CornerRadius = UDim.new(0, 4)

-- TABS
local TB = Instance.new("Frame"); TB.Size = UDim2.new(1, -10, 0, 22); TB.Position = UDim2.new(0, 5, 0, 33)
TB.BackgroundTransparency = 1; TB.Parent = Main
local tbl = Instance.new("UIListLayout", TB); tbl.FillDirection = Enum.FillDirection.Horizontal; tbl.Padding = UDim.new(0, 3); tbl.SortOrder = Enum.SortOrder.LayoutOrder

local tabButtons = {}; local tabPages = {}
for i, info in ipairs({{"Spy", "🔍 Spy"}, {"Detail", "📋 Detail"}, {"Block", "🚫 Block"}, {"Info", "📊 Info"}}) do
	local b = Instance.new("TextButton"); b.Size = UDim2.new(0, 64, 1, 0)
	b.BackgroundColor3 = i == 1 and C.tabA or C.tabI; b.Text = info[2]
	b.TextColor3 = i == 1 and C.tabTA or C.tabTI; b.TextSize = 9; b.Font = Enum.Font.GothamBold
	b.BorderSizePixel = 0; b.LayoutOrder = i; b.Parent = TB
	Instance.new("UICorner", b).CornerRadius = UDim.new(0, 4)
	tabButtons[info[1]] = b
end

local CA = Instance.new("Frame"); CA.Size = UDim2.new(1, -10, 1, -60); CA.Position = UDim2.new(0, 5, 0, 58)
CA.BackgroundTransparency = 1; CA.ClipsDescendants = true; CA.Parent = Main

-- HELPERS
local function mkP(n) local p = Instance.new("ScrollingFrame"); p.Size = UDim2.new(1, 0, 1, 0); p.BackgroundTransparency = 1; p.ScrollBarThickness = 2; p.ScrollBarImageColor3 = C.acc; p.AutomaticCanvasSize = Enum.AutomaticSize.Y; p.CanvasSize = UDim2.new(0, 0, 0, 0); p.BorderSizePixel = 0; p.Visible = (n == "Spy"); p.Name = n; p.Parent = CA; local l = Instance.new("UIListLayout", p); l.Padding = UDim.new(0, 3); l.SortOrder = Enum.SortOrder.LayoutOrder; tabPages[n] = p; return p end
local function mkSc(p, o) local f = Instance.new("Frame"); f.Size = UDim2.new(1, 0, 0, 0); f.AutomaticSize = Enum.AutomaticSize.Y; f.BackgroundColor3 = C.sec; f.BorderSizePixel = 0; f.LayoutOrder = o; f.Parent = p; Instance.new("UICorner", f).CornerRadius = UDim.new(0, 5); Instance.new("UIStroke", f).Color = C.brd; local pd = Instance.new("UIPadding", f); pd.PaddingTop = UDim.new(0, 5); pd.PaddingBottom = UDim.new(0, 5); pd.PaddingLeft = UDim.new(0, 6); pd.PaddingRight = UDim.new(0, 6); local l = Instance.new("UIListLayout", f); l.Padding = UDim.new(0, 3); l.SortOrder = Enum.SortOrder.LayoutOrder; return f end
local function mkH(p, t, o) local l = Instance.new("TextLabel"); l.Size = UDim2.new(1, 0, 0, 12); l.BackgroundTransparency = 1; l.Text = t; l.TextColor3 = C.acc; l.TextSize = 9; l.Font = Enum.Font.GothamBold; l.TextXAlignment = Enum.TextXAlignment.Left; l.LayoutOrder = o; l.Parent = p end
local function mkL(p, t, o) local l = Instance.new("TextLabel"); l.Size = UDim2.new(1, 0, 0, 12); l.AutomaticSize = Enum.AutomaticSize.Y; l.BackgroundTransparency = 1; l.Text = t; l.TextColor3 = C.dim; l.TextSize = 9; l.Font = Enum.Font.Gotham; l.TextXAlignment = Enum.TextXAlignment.Left; l.TextWrapped = true; l.LayoutOrder = o; l.Parent = p; return l end

local function mkT(p, n, o, def, lc, cb)
	local r = Instance.new("Frame"); r.Size = UDim2.new(1, 0, 0, 20); r.BackgroundTransparency = 1; r.LayoutOrder = o; r.Parent = p
	local l = Instance.new("TextLabel"); l.Size = UDim2.new(1, -40, 1, 0); l.BackgroundTransparency = 1; l.Text = n; l.TextColor3 = lc or C.txt; l.TextSize = 10; l.Font = Enum.Font.GothamMedium; l.TextXAlignment = Enum.TextXAlignment.Left; l.Parent = r
	local b = Instance.new("TextButton"); b.Size = UDim2.new(0, 36, 0, 16); b.Position = UDim2.new(1, -36, 0.5, -8); b.BackgroundColor3 = def and C.on or C.off; b.Text = def and "ON" or "OFF"; b.TextColor3 = Color3.new(1, 1, 1); b.TextSize = 8; b.Font = Enum.Font.GothamBold; b.BorderSizePixel = 0; b.Parent = r; Instance.new("UICorner", b).CornerRadius = UDim.new(0, 3)
	local on = def or false; b.MouseButton1Click:Connect(function() on = not on; b.BackgroundColor3 = on and C.on or C.off; b.Text = on and "ON" or "OFF"; cb(on) end)
end

local function mkB(p, n, o, c, cb) local b = Instance.new("TextButton"); b.Size = UDim2.new(1, 0, 0, 20); b.BackgroundColor3 = c or C.acc; b.Text = n; b.TextColor3 = Color3.new(1, 1, 1); b.TextSize = 9; b.Font = Enum.Font.GothamBold; b.BorderSizePixel = 0; b.LayoutOrder = o; b.Parent = p; Instance.new("UICorner", b).CornerRadius = UDim.new(0, 3); b.MouseButton1Click:Connect(function() if cb then cb() end end) end

local function switchTab(tn) for n, pg in pairs(tabPages) do pg.Visible = (n == tn) end; for n, bt in pairs(tabButtons) do bt.BackgroundColor3 = (n == tn) and C.tabA or C.tabI; bt.TextColor3 = (n == tn) and C.tabTA or C.tabTI end end
for n, bt in pairs(tabButtons) do bt.MouseButton1Click:Connect(function() switchTab(n) end) end

-- ========================
-- PAGE 1: SPY (grouped counts)
-- ========================
local p1 = mkP("Spy")

local spyCtrl = mkSc(p1, 1)
mkH(spyCtrl, "CONTROL", 0)
mkT(spyCtrl, "🔍 Enable Spy", 1, false, C.txt, function(v) spyEnabled = v end)

local btnRow = Instance.new("Frame"); btnRow.Size = UDim2.new(1, 0, 0, 20); btnRow.BackgroundTransparency = 1; btnRow.LayoutOrder = 2; btnRow.Parent = spyCtrl
local clrBtn = Instance.new("TextButton"); clrBtn.Size = UDim2.new(0.48, 0, 1, 0); clrBtn.BackgroundColor3 = Color3.fromRGB(140, 35, 35); clrBtn.Text = "🗑 Clear"; clrBtn.TextColor3 = C.txt; clrBtn.TextSize = 9; clrBtn.Font = Enum.Font.GothamBold; clrBtn.BorderSizePixel = 0; clrBtn.Parent = btnRow; Instance.new("UICorner", clrBtn).CornerRadius = UDim.new(0, 3)
clrBtn.MouseButton1Click:Connect(function() remoteData = {}; remoteOrder = {}; totalCalls = 0; blockedCalls = 0 end)
local cpBtn = Instance.new("TextButton"); cpBtn.Size = UDim2.new(0.48, 0, 1, 0); cpBtn.Position = UDim2.new(0.52, 0, 0, 0); cpBtn.BackgroundColor3 = C.accAlt; cpBtn.Text = "📋 Copy All"; cpBtn.TextColor3 = C.txt; cpBtn.TextSize = 9; cpBtn.Font = Enum.Font.GothamBold; cpBtn.BorderSizePixel = 0; cpBtn.Parent = btnRow; Instance.new("UICorner", cpBtn).CornerRadius = UDim.new(0, 3)
cpBtn.MouseButton1Click:Connect(function()
	local all = {}
	for _, name in ipairs(remoteOrder) do
		local d = remoteData[name]
		if d then table.insert(all, "-- " .. d.name .. " (" .. d.count .. "x)"); table.insert(all, d.lastCode); table.insert(all, "") end
	end
	toClip(table.concat(all, "\n"))
end)

local lblStats = mkL(spyCtrl, "Calls: 0 | Blocked: 0", 3)

-- Log list (grouped)
local logFrame = Instance.new("Frame"); logFrame.Size = UDim2.new(1, 0, 0, 240); logFrame.BackgroundColor3 = C.logBg; logFrame.BorderSizePixel = 0; logFrame.LayoutOrder = 2; logFrame.Parent = p1; Instance.new("UICorner", logFrame).CornerRadius = UDim.new(0, 4); Instance.new("UIStroke", logFrame).Color = C.brd
local logScroll = Instance.new("ScrollingFrame"); logScroll.Size = UDim2.new(1, -4, 1, -4); logScroll.Position = UDim2.new(0, 2, 0, 2); logScroll.BackgroundTransparency = 1; logScroll.ScrollBarThickness = 2; logScroll.ScrollBarImageColor3 = C.acc; logScroll.AutomaticCanvasSize = Enum.AutomaticSize.Y; logScroll.CanvasSize = UDim2.new(0, 0, 0, 0); logScroll.BorderSizePixel = 0; logScroll.Parent = logFrame
local logLayout = Instance.new("UIListLayout", logScroll); logLayout.Padding = UDim.new(0, 1); logLayout.SortOrder = Enum.SortOrder.LayoutOrder

-- ========================
-- PAGE 2: DETAIL
-- ========================
local p2 = mkP("Detail")
local dSec = mkSc(p2, 1); mkH(dSec, "SELECTED REMOTE", 0)
local lblDName = mkL(dSec, "Name: (tap a log entry)", 1)
local lblDType = mkL(dSec, "Type: ---", 2)
local lblDPath = mkL(dSec, "Path: ---", 3)
local lblDCount = mkL(dSec, "Total Calls: ---", 4)
local lblDPerSec = mkL(dSec, "Per Second: ---", 5)
local lblDTime = mkL(dSec, "Last Fire: ---", 6)
local lblDBlocked = mkL(dSec, "Blocked: ---", 7)
local lblDTrace = mkL(dSec, "Trace: ---", 8)

local aSec = mkSc(p2, 2); mkH(aSec, "LAST ARGUMENTS", 0)
local lblDArgs = mkL(aSec, "(none)", 1)

local cSec = mkSc(p2, 3); mkH(cSec, "CODE", 0)
local lblDCode = mkL(cSec, "(none)", 1); lblDCode.Font = Enum.Font.Code; lblDCode.TextSize = 8
mkB(cSec, "📋 Copy Code", 2, C.accAlt, function() if selectedRemote and remoteData[selectedRemote] then toClip(remoteData[selectedRemote].lastCode) end end)
mkB(cSec, "🚫 Block This", 3, C.acc, function() if selectedRemote then blockedRemotes[selectedRemote] = true end end)
mkB(cSec, "🔇 Ignore This", 4, Color3.fromRGB(140, 90, 30), function() if selectedRemote then ignoredRemotes[selectedRemote] = true end end)

-- ========================
-- PAGE 3: BLOCK
-- ========================
local p3 = mkP("Block")
local bCtrl = mkSc(p3, 1); mkH(bCtrl, "BLOCKING", 0)
mkT(bCtrl, "🚫 Enable Blocking", 1, false, C.txt, function(v) blockEnabled = v end)
mkT(bCtrl, "⚡ Auto-Block Spam", 2, false, C.spam, function(v) autoBlockSpam = v end)
mkL(bCtrl, "Spam = " .. spamThreshold .. "+ calls/sec", 3)

local bInput = mkSc(p3, 2); mkH(bInput, "ADD REMOTE", 0)
local blockBox = Instance.new("TextBox"); blockBox.Size = UDim2.new(1, 0, 0, 22); blockBox.BackgroundColor3 = C.logBg; blockBox.Text = ""; blockBox.PlaceholderText = "Remote name..."; blockBox.TextColor3 = C.txt; blockBox.PlaceholderColor3 = C.dim; blockBox.TextSize = 10; blockBox.Font = Enum.Font.Gotham; blockBox.BorderSizePixel = 0; blockBox.LayoutOrder = 1; blockBox.ClearTextOnFocus = false; blockBox.Parent = bInput; Instance.new("UICorner", blockBox).CornerRadius = UDim.new(0, 3); Instance.new("UIPadding", blockBox).PaddingLeft = UDim.new(0, 5)
mkB(bInput, "➕ Block", 2, C.acc, function() if blockBox.Text ~= "" then blockedRemotes[blockBox.Text] = true; blockBox.Text = "" end end)
mkB(bInput, "🔇 Ignore", 3, Color3.fromRGB(140, 90, 30), function() if blockBox.Text ~= "" then ignoredRemotes[blockBox.Text] = true; blockBox.Text = "" end end)

local bList = mkSc(p3, 3); mkH(bList, "BLOCKED", 0); local lblBList = mkL(bList, "None", 1)
local iList = mkSc(p3, 4); mkH(iList, "IGNORED", 0); local lblIList = mkL(iList, "None", 1)
mkB(p3, "🗑 Clear Blocks", 5, Color3.fromRGB(140, 35, 35), function() blockedRemotes = {} end)
mkB(p3, "🗑 Clear Ignores", 6, Color3.fromRGB(140, 90, 30), function() ignoredRemotes = {} end)

-- ========================
-- PAGE 4: INFO
-- ========================
local p4 = mkP("Info")
local hSec = mkSc(p4, 1); mkH(hSec, "HOOK", 0)
local hText = "❌ None"
if hookMethod == "namecall" then hText = "✅ __namecall (full)"
elseif hookMethod == "hookfunc" then hText = "⚠ hookfunction (partial)"
elseif hookMethod == "listener" then hText = "📩 Listener only" end
mkL(hSec, hText, 1)

local cSec2 = mkSc(p4, 2); mkH(cSec2, "EXECUTOR", 0)
for i, cap in ipairs({
	{"hookmetamethod", hasHookMeta}, {"hookfunction", hasHookFunc},
	{"newcclosure", hasNewCC}, {"getnamecallmethod", hasGetNM},
	{"checkcaller", hasCheckcaller}, {"clipboard", hasClipboard},
	{"debug.getinfo", hasGetInfo},
}) do
	mkL(cSec2, (cap[2] and "✅ " or "❌ ") .. cap[1], i)
end

local tSec = mkSc(p4, 3); mkH(tSec, "LEGEND", 0)
mkL(tSec, "📤 FireServer | 📥 InvokeServer", 1)
mkL(tSec, "📩 OnClientEvent | 🔗 Bindable", 2)
mkL(tSec, "🚫 Blocked | ⚡ Spam", 3)
mkL(tSec, "Tap entry → Detail | Numbers = call count", 4)

-- ========================
-- DRAG (works on mobile too)
-- ========================
do
	local dg, di, ds, sp = false, nil, nil, nil
	Bar.InputBegan:Connect(function(i)
		if i.UserInputType == Enum.UserInputType.MouseButton1 or i.UserInputType == Enum.UserInputType.Touch then
			dg = true; ds = i.Position; sp = Main.Position
			i.Changed:Connect(function() if i.UserInputState == Enum.UserInputState.End then dg = false end end)
		end
	end)
	Bar.InputChanged:Connect(function(i)
		if i.UserInputType == Enum.UserInputType.MouseMovement or i.UserInputType == Enum.UserInputType.Touch then di = i end
	end)
	UserInputService.InputChanged:Connect(function(i)
		if i == di and dg then
			local d = i.Position - ds
			Main.Position = UDim2.new(sp.X.Scale, sp.X.Offset + d.X, sp.Y.Scale, sp.Y.Offset + d.Y)
		end
	end)
end

local full = Main.Size
local function toggleMin()
	minimized = not minimized
	if minimized then
		CA.Visible = false; TB.Visible = false
		TweenService:Create(Main, TweenInfo.new(0.15), {Size = UDim2.new(0, 280, 0, 30)}):Play()
		MinBtn.Text = "+"
	else
		TweenService:Create(Main, TweenInfo.new(0.15), {Size = full}):Play()
		task.delay(0.15, function() CA.Visible = true; TB.Visible = true end)
		MinBtn.Text = "—"
	end
end
MinBtn.MouseButton1Click:Connect(toggleMin)
UserInputService.InputBegan:Connect(function(i, g)
	if not g and i.KeyCode == Enum.KeyCode.RightControl then toggleMin() end
end)

-- ========================
-- UPDATE LOOP - GROUPED DISPLAY
-- ========================
task.spawn(function()
	local lastUpdate = 0

	while true do
		lblStats.Text = "Calls: " .. totalCalls .. " | Blocked: " .. blockedCalls .. " | Remotes: " .. #remoteOrder

		-- Rebuild log display
		local now = os.clock()
		if now - lastUpdate > 0.4 then
			lastUpdate = now

			for _, child in ipairs(logScroll:GetChildren()) do
				if child:IsA("TextButton") then child:Destroy() end
			end

			-- Sort by most recent activity
			local sorted = {}
			for _, name in ipairs(remoteOrder) do
				if remoteData[name] then table.insert(sorted, remoteData[name]) end
			end
			table.sort(sorted, function(a, b) return a.count > b.count end)

			for i, data in ipairs(sorted) do
				if i > 40 then break end

				local color = C.fire
				if data.type == "InvokeServer" then color = C.invoke end
				if data.type == "OnClientEvent" then color = C.onclient end
				if data.type == "Fire" or data.type == "Invoke" then color = C.bind end
				if blockedRemotes[data.name] then color = C.blocked end
				if data.perSec >= spamThreshold then color = C.spam end

				local icon = "📤"
				if data.type == "InvokeServer" then icon = "📥" end
				if data.type == "OnClientEvent" then icon = "📩" end
				if data.type == "Fire" or data.type == "Invoke" then icon = "🔗" end
				if blockedRemotes[data.name] then icon = "🚫" end
				if data.perSec >= spamThreshold then icon = "⚡" end

				local btn = Instance.new("TextButton")
				btn.Size = UDim2.new(1, 0, 0, 20)
				btn.BackgroundColor3 = C.sec
				btn.BorderSizePixel = 0
				btn.LayoutOrder = i
				btn.Parent = logScroll
				btn.TextXAlignment = Enum.TextXAlignment.Left
				btn.Font = Enum.Font.Code
				btn.TextSize = 9
				btn.TextWrapped = false
				btn.TextColor3 = color
				Instance.new("UICorner", btn).CornerRadius = UDim.new(0, 2)
				local bp = Instance.new("UIPadding", btn); bp.PaddingLeft = UDim.new(0, 4)

				local countStr = "(" .. data.count .. ")"
				if data.perSec > 0 then
					countStr = "(" .. data.count .. ") [" .. data.perSec .. "/s]"
				end

				btn.Text = icon .. " " .. data.name .. " " .. countStr

				local capturedName = data.name
				btn.MouseButton1Click:Connect(function()
					selectedRemote = capturedName
					switchTab("Detail")

					local d = remoteData[capturedName]
					if d then
						lblDName.Text = "Name: " .. d.name
						lblDType.Text = "Type: " .. d.type
						lblDPath.Text = "Path: " .. d.path
						lblDCount.Text = "Total Calls: " .. d.count
						lblDPerSec.Text = "Per Second: " .. d.perSec
						lblDTime.Text = "Last Fire: " .. d.lastTime
						lblDBlocked.Text = "Blocked: " .. (blockedRemotes[d.name] and "YES" or "No")
						lblDTrace.Text = "Trace: " .. (d.lastTrace or "N/A")
						lblDArgs.Text = serArgs(d.lastArgs)
						lblDCode.Text = d.lastCode
					end
				end)
			end
		end

		-- Update block/ignore lists
		local bN = {}; for n in pairs(blockedRemotes) do table.insert(bN, "🚫 " .. n) end
		lblBList.Text = #bN > 0 and table.concat(bN, "\n") or "None"
		local iN = {}; for n in pairs(ignoredRemotes) do table.insert(iN, "🔇 " .. n) end
		lblIList.Text = #iN > 0 and table.concat(iN, "\n") or "None"

		-- Update detail if viewing
		if selectedRemote and remoteData[selectedRemote] then
			local d = remoteData[selectedRemote]
			lblDCount.Text = "Total Calls: " .. d.count
			lblDPerSec.Text = "Per Second: " .. d.perSec
			lblDTime.Text = "Last Fire: " .. d.lastTime
		end

		task.wait(0.4)
	end
end)
