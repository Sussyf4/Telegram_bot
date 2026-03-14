-- Remote Spy & Anti-Cheat Testing Tool
-- LocalScript: Place in StarterPlayerScripts
-- PURPOSE: Test your own game's anti-cheat by monitoring all remote traffic

local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local UserInputService = game:GetService("UserInputService")
local TweenService = game:GetService("TweenService")
local HttpService = game:GetService("HttpService")

local Player = Players.LocalPlayer

-- ========================
-- STATE
-- ========================
local spyEnabled = false
local logFireServer = true
local logInvokeServer = true
local logOnClientEvent = true
local blockEnabled = false
local minimized = false
local logs = {}
local maxLogs = 200
local blockedRemotes = {} -- remotes to block
local hookedRemotes = {} -- track what we hooked
local originalFunctions = {} -- store originals

-- ========================
-- COLORS
-- ========================
local C = {
	bg = Color3.fromRGB(10, 10, 18),
	bar = Color3.fromRGB(16, 16, 28),
	barAccent = Color3.fromRGB(200, 50, 50),
	acc = Color3.fromRGB(200, 50, 50),
	accAlt = Color3.fromRGB(50, 150, 200),
	on = Color3.fromRGB(30, 170, 70),
	off = Color3.fromRGB(170, 30, 30),
	txt = Color3.fromRGB(220, 220, 235),
	dim = Color3.fromRGB(90, 90, 110),
	sec = Color3.fromRGB(14, 14, 24),
	brd = Color3.fromRGB(35, 35, 50),
	drop = Color3.fromRGB(12, 12, 20),
	hover = Color3.fromRGB(28, 28, 42),
	fire = Color3.fromRGB(255, 100, 50),
	invoke = Color3.fromRGB(100, 200, 255),
	onclient = Color3.fromRGB(100, 255, 100),
	blocked = Color3.fromRGB(255, 50, 50),
	tabA = Color3.fromRGB(200, 50, 50),
	tabI = Color3.fromRGB(22, 22, 36),
	tabTA = Color3.fromRGB(255, 255, 255),
	tabTI = Color3.fromRGB(80, 80, 100),
	logBg = Color3.fromRGB(8, 8, 16),
}

-- ========================
-- SERIALIZE ARGS FOR DISPLAY
-- ========================
local function serializeValue(v, depth)
	depth = depth or 0
	if depth > 3 then return "..." end

	local t = typeof(v)

	if t == "string" then
		return '"' .. v:sub(1, 80) .. '"'
	elseif t == "number" then
		return tostring(v)
	elseif t == "boolean" then
		return tostring(v)
	elseif t == "nil" then
		return "nil"
	elseif t == "Instance" then
		return v:GetFullName()
	elseif t == "Vector3" then
		return string.format("Vector3.new(%.1f, %.1f, %.1f)", v.X, v.Y, v.Z)
	elseif t == "CFrame" then
		local p = v.Position
		return string.format("CFrame.new(%.1f, %.1f, %.1f, ...)", p.X, p.Y, p.Z)
	elseif t == "Color3" then
		return string.format("Color3.new(%.2f, %.2f, %.2f)", v.R, v.G, v.B)
	elseif t == "UDim2" then
		return string.format("UDim2.new(%.2f, %d, %.2f, %d)", v.X.Scale, v.X.Offset, v.Y.Scale, v.Y.Offset)
	elseif t == "EnumItem" then
		return tostring(v)
	elseif t == "table" then
		local parts = {}
		local count = 0
		for k, val in pairs(v) do
			count += 1
			if count > 8 then
				table.insert(parts, "...")
				break
			end
			local key
			if type(k) == "number" then
				key = "[" .. k .. "]"
			else
				key = tostring(k)
			end
			table.insert(parts, key .. " = " .. serializeValue(val, depth + 1))
		end
		return "{" .. table.concat(parts, ", ") .. "}"
	else
		return t .. "(" .. tostring(v) .. ")"
	end
end

local function serializeArgs(...)
	local args = {...}
	if #args == 0 then return "()" end
	local parts = {}
	for i, v in ipairs(args) do
		table.insert(parts, serializeValue(v))
	end
	return "(" .. table.concat(parts, ", ") .. ")"
end

-- ========================
-- GENERATE LUA CODE FOR REMOTE CALL
-- ========================
local function generateCode(remoteName, remoteType, args)
	local lines = {}

	if remoteType == "FireServer" then
		if #args == 0 then
			table.insert(lines, 'local args = {}')
		else
			table.insert(lines, 'local args = {')
			for i, v in ipairs(args) do
				table.insert(lines, '    [' .. i .. '] = ' .. serializeValue(v))
				if i < #args then lines[#lines] = lines[#lines] .. "," end
			end
			table.insert(lines, '}')
		end
		table.insert(lines, 'game:GetService("ReplicatedStorage").' .. remoteName .. ':FireServer(unpack(args))')
	elseif remoteType == "InvokeServer" then
		if #args == 0 then
			table.insert(lines, 'local args = {}')
		else
			table.insert(lines, 'local args = {')
			for i, v in ipairs(args) do
				table.insert(lines, '    [' .. i .. '] = ' .. serializeValue(v))
				if i < #args then lines[#lines] = lines[#lines] .. "," end
			end
			table.insert(lines, '}')
		end
		table.insert(lines, 'game:GetService("ReplicatedStorage").' .. remoteName .. ':InvokeServer(unpack(args))')
	end

	return table.concat(lines, "\n")
end

-- ========================
-- LOG ENTRY
-- ========================
local function addLog(remoteName, remoteType, args, wasBlocked)
	local entry = {
		time = os.clock(),
		name = remoteName,
		type = remoteType,
		args = args,
		argsText = serializeArgs(unpack(args)),
		code = generateCode(remoteName, remoteType, args),
		blocked = wasBlocked,
		timestamp = os.date("%H:%M:%S"),
	}

	table.insert(logs, 1, entry) -- newest first

	if #logs > maxLogs then
		table.remove(logs, #logs)
	end

	return entry
end

-- ========================
-- HOOK ALL REMOTES
-- ========================
local function hookRemote(remote)
	if hookedRemotes[remote] then return end
	hookedRemotes[remote] = true

	if remote:IsA("RemoteEvent") then
		-- Hook FireServer by connecting to the remote's signal
		-- We can't directly hook FireServer in a normal LocalScript
		-- But we can monitor OnClientEvent
		if logOnClientEvent then
			remote.OnClientEvent:Connect(function(...)
				if not spyEnabled then return end
				addLog(remote.Name, "OnClientEvent", {...}, false)
			end)
		end
	end
end

-- ========================
-- MONITOR NEW REMOTES
-- ========================
local function scanAndHook()
	for _, desc in ipairs(ReplicatedStorage:GetDescendants()) do
		if desc:IsA("RemoteEvent") or desc:IsA("RemoteFunction") then
			hookRemote(desc)
		end
	end
end

ReplicatedStorage.DescendantAdded:Connect(function(desc)
	if desc:IsA("RemoteEvent") or desc:IsA("RemoteFunction") then
		hookRemote(desc)
	end
end)

-- ========================
-- NAMECALL HOOK (requires executor)
-- This is the main spy - intercepts ALL FireServer/InvokeServer calls
-- ========================
local function setupNamecallHook()
	if not hookmetamethod then return false end

	local oldNamecall
	oldNamecall = hookmetamethod(game, "__namecall", newcclosure(function(self, ...)
		local method = getnamecallmethod()
		local args = {...}

		if spyEnabled then
			if method == "FireServer" and self:IsA("RemoteEvent") then
				local remoteName = self.Name
				local wasBlocked = blockedRemotes[remoteName] == true

				if logFireServer then
					addLog(remoteName, "FireServer", args, wasBlocked)
				end

				if wasBlocked and blockEnabled then
					return -- block the call
				end
			end

			if method == "InvokeServer" and self:IsA("RemoteFunction") then
				local remoteName = self.Name
				local wasBlocked = blockedRemotes[remoteName] == true

				if logInvokeServer then
					addLog(remoteName, "InvokeServer", args, wasBlocked)
				end

				if wasBlocked and blockEnabled then
					return nil -- block the call
				end
			end
		end

		return oldNamecall(self, ...)
	end))

	return true
end

-- ========================
-- FIRE HOOK (alternative for executors without hookmetamethod)
-- ========================
local function setupFireHook()
	if not hookfunction then return false end

	-- Hook RemoteEvent.FireServer
	local oldFire = Instance.new("RemoteEvent").FireServer
	hookfunction(oldFire, newcclosure(function(self, ...)
		if spyEnabled and self:IsA("RemoteEvent") then
			local args = {...}
			local remoteName = self.Name
			local wasBlocked = blockedRemotes[remoteName] == true

			if logFireServer then
				addLog(remoteName, "FireServer", args, wasBlocked)
			end

			if wasBlocked and blockEnabled then
				return
			end
		end
		return oldFire(self, ...)
	end))

	return true
end

local namecallHooked = setupNamecallHook()
local fireHooked = false
if not namecallHooked then
	fireHooked = setupFireHook()
end

task.delay(1, scanAndHook)

-- ========================
-- GUI
-- ========================
local Gui = Instance.new("ScreenGui")
Gui.Name = "RemoteSpy"
Gui.ResetOnSpawn = false
Gui.ZIndexBehavior = Enum.ZIndexBehavior.Sibling
Gui.Parent = Player:WaitForChild("PlayerGui")

local Main = Instance.new("Frame")
Main.Size = UDim2.new(0, 500, 0, 550)
Main.Position = UDim2.new(0.5, -250, 0.5, -275)
Main.BackgroundColor3 = C.bg
Main.BorderSizePixel = 0
Main.Active = true
Main.Parent = Gui
Instance.new("UICorner", Main).CornerRadius = UDim.new(0, 10)
Instance.new("UIStroke", Main).Color = C.brd

-- BAR
local Bar = Instance.new("Frame")
Bar.Size = UDim2.new(1, 0, 0, 40)
Bar.BackgroundColor3 = C.bar
Bar.BorderSizePixel = 0
Bar.Parent = Main
Instance.new("UICorner", Bar).CornerRadius = UDim.new(0, 10)
local bf = Instance.new("Frame")
bf.Size = UDim2.new(1, 0, 0, 12)
bf.Position = UDim2.new(0, 0, 1, -12)
bf.BackgroundColor3 = C.bar
bf.BorderSizePixel = 0
bf.Parent = Bar
local al = Instance.new("Frame")
al.Size = UDim2.new(1, -20, 0, 2)
al.Position = UDim2.new(0, 10, 1, -1)
al.BackgroundColor3 = C.barAccent
al.BorderSizePixel = 0
al.Parent = Bar

local lg = Instance.new("TextLabel")
lg.Size = UDim2.new(0, 250, 1, 0)
lg.Position = UDim2.new(0, 14, 0, 0)
lg.BackgroundTransparency = 1
lg.Text = "🔍 REMOTE SPY - Anti-Cheat Tester"
lg.TextColor3 = C.txt
lg.TextSize = 14
lg.Font = Enum.Font.GothamBold
lg.TextXAlignment = Enum.TextXAlignment.Left
lg.Parent = Bar

local MinBtn = Instance.new("TextButton")
MinBtn.Size = UDim2.new(0, 28, 0, 28)
MinBtn.Position = UDim2.new(1, -38, 0, 6)
MinBtn.BackgroundColor3 = C.acc
MinBtn.Text = "—"
MinBtn.TextColor3 = C.txt
MinBtn.TextSize = 16
MinBtn.Font = Enum.Font.GothamBold
MinBtn.BorderSizePixel = 0
MinBtn.Parent = Bar
Instance.new("UICorner", MinBtn).CornerRadius = UDim.new(0, 6)

-- TABS
local TB = Instance.new("Frame")
TB.Size = UDim2.new(1, -20, 0, 28)
TB.Position = UDim2.new(0, 10, 0, 44)
TB.BackgroundTransparency = 1
TB.Parent = Main
local tbl = Instance.new("UIListLayout", TB)
tbl.FillDirection = Enum.FillDirection.Horizontal
tbl.Padding = UDim.new(0, 4)
tbl.SortOrder = Enum.SortOrder.LayoutOrder

local tabButtons = {}
local tabPages = {}
for i, info in ipairs({{"Spy", "🔍 Spy"}, {"Blocked", "🚫 Block"}, {"Settings", "⚙ Config"}, {"Info", "📊 Info"}}) do
	local b = Instance.new("TextButton")
	b.Size = UDim2.new(0, 112, 1, 0)
	b.BackgroundColor3 = i == 1 and C.tabA or C.tabI
	b.Text = info[2]
	b.TextColor3 = i == 1 and C.tabTA or C.tabTI
	b.TextSize = 10
	b.Font = Enum.Font.GothamBold
	b.BorderSizePixel = 0
	b.LayoutOrder = i
	b.Parent = TB
	Instance.new("UICorner", b).CornerRadius = UDim.new(0, 5)
	tabButtons[info[1]] = b
end

local CA = Instance.new("Frame")
CA.Size = UDim2.new(1, -20, 1, -82)
CA.Position = UDim2.new(0, 10, 0, 76)
CA.BackgroundTransparency = 1
CA.ClipsDescendants = true
CA.Parent = Main

-- HELPERS
local function mkP(n)
	local p = Instance.new("ScrollingFrame")
	p.Size = UDim2.new(1, 0, 1, 0)
	p.BackgroundTransparency = 1
	p.ScrollBarThickness = 3
	p.ScrollBarImageColor3 = C.acc
	p.AutomaticCanvasSize = Enum.AutomaticSize.Y
	p.CanvasSize = UDim2.new(0, 0, 0, 0)
	p.BorderSizePixel = 0
	p.Visible = (n == "Spy")
	p.Name = n
	p.Parent = CA
	local l = Instance.new("UIListLayout", p)
	l.Padding = UDim.new(0, 4)
	l.SortOrder = Enum.SortOrder.LayoutOrder
	tabPages[n] = p
	return p
end

local function mkSc(p, o)
	local f = Instance.new("Frame")
	f.Size = UDim2.new(1, 0, 0, 0)
	f.AutomaticSize = Enum.AutomaticSize.Y
	f.BackgroundColor3 = C.sec
	f.BorderSizePixel = 0
	f.LayoutOrder = o
	f.Parent = p
	Instance.new("UICorner", f).CornerRadius = UDim.new(0, 6)
	Instance.new("UIStroke", f).Color = C.brd
	local pd = Instance.new("UIPadding", f)
	pd.PaddingTop = UDim.new(0, 6)
	pd.PaddingBottom = UDim.new(0, 6)
	pd.PaddingLeft = UDim.new(0, 8)
	pd.PaddingRight = UDim.new(0, 8)
	local l = Instance.new("UIListLayout", f)
	l.Padding = UDim.new(0, 4)
	l.SortOrder = Enum.SortOrder.LayoutOrder
	return f
end

local function mkH(p, t, o)
	local l = Instance.new("TextLabel")
	l.Size = UDim2.new(1, 0, 0, 14)
	l.BackgroundTransparency = 1
	l.Text = t
	l.TextColor3 = C.acc
	l.TextSize = 10
	l.Font = Enum.Font.GothamBold
	l.TextXAlignment = Enum.TextXAlignment.Left
	l.LayoutOrder = o
	l.Parent = p
end

local function mkL(p, t, o)
	local l = Instance.new("TextLabel")
	l.Size = UDim2.new(1, 0, 0, 14)
	l.AutomaticSize = Enum.AutomaticSize.Y
	l.BackgroundTransparency = 1
	l.Text = t
	l.TextColor3 = C.dim
	l.TextSize = 11
	l.Font = Enum.Font.Gotham
	l.TextXAlignment = Enum.TextXAlignment.Left
	l.TextWrapped = true
	l.LayoutOrder = o
	l.Parent = p
	return l
end

local function mkT(p, n, o, lc, cb)
	local r = Instance.new("Frame")
	r.Size = UDim2.new(1, 0, 0, 26)
	r.BackgroundTransparency = 1
	r.LayoutOrder = o
	r.Parent = p
	local l = Instance.new("TextLabel")
	l.Size = UDim2.new(1, -52, 1, 0)
	l.BackgroundTransparency = 1
	l.Text = n
	l.TextColor3 = lc or C.txt
	l.TextSize = 12
	l.Font = Enum.Font.GothamMedium
	l.TextXAlignment = Enum.TextXAlignment.Left
	l.Parent = r
	local b = Instance.new("TextButton")
	b.Size = UDim2.new(0, 46, 0, 20)
	b.Position = UDim2.new(1, -46, 0.5, -10)
	b.BackgroundColor3 = C.off
	b.Text = "OFF"
	b.TextColor3 = Color3.new(1, 1, 1)
	b.TextSize = 10
	b.Font = Enum.Font.GothamBold
	b.BorderSizePixel = 0
	b.Parent = r
	Instance.new("UICorner", b).CornerRadius = UDim.new(0, 5)
	local on = false
	b.MouseButton1Click:Connect(function()
		on = not on
		b.BackgroundColor3 = on and C.on or C.off
		b.Text = on and "ON" or "OFF"
		cb(on)
	end)
	return b
end

local function mkB(p, n, o, c, cb)
	local b = Instance.new("TextButton")
	b.Size = UDim2.new(1, 0, 0, 26)
	b.BackgroundColor3 = c or C.acc
	b.Text = n
	b.TextColor3 = Color3.new(1, 1, 1)
	b.TextSize = 11
	b.Font = Enum.Font.GothamBold
	b.BorderSizePixel = 0
	b.LayoutOrder = o
	b.Parent = p
	Instance.new("UICorner", b).CornerRadius = UDim.new(0, 5)
	b.MouseButton1Click:Connect(function()
		if cb then cb() end
	end)
end

local function switchTab(tn)
	for n, pg in pairs(tabPages) do pg.Visible = (n == tn) end
	for n, bt in pairs(tabButtons) do
		bt.BackgroundColor3 = (n == tn) and C.tabA or C.tabI
		bt.TextColor3 = (n == tn) and C.tabTA or C.tabTI
	end
end
for n, bt in pairs(tabButtons) do
	bt.MouseButton1Click:Connect(function() switchTab(n) end)
end

-- ========================
-- PAGE 1: SPY (Live Log)
-- ========================
local p1 = mkP("Spy")

local spyControl = mkSc(p1, 1)
mkH(spyControl, "REMOTE SPY CONTROL", 0)
local spyToggleBtn = mkT(spyControl, "🔍 Enable Spy", 1, C.txt, function(v) spyEnabled = v end)
mkB(spyControl, "🗑 Clear Logs", 2, Color3.fromRGB(150, 50, 50), function()
	logs = {}
end)

-- Log display area
local logFrame = Instance.new("Frame")
logFrame.Size = UDim2.new(1, 0, 0, 350)
logFrame.BackgroundColor3 = C.logBg
logFrame.BorderSizePixel = 0
logFrame.LayoutOrder = 2
logFrame.Parent = p1
Instance.new("UICorner", logFrame).CornerRadius = UDim.new(0, 6)
Instance.new("UIStroke", logFrame).Color = C.brd

local logScroll = Instance.new("ScrollingFrame")
logScroll.Size = UDim2.new(1, -8, 1, -8)
logScroll.Position = UDim2.new(0, 4, 0, 4)
logScroll.BackgroundTransparency = 1
logScroll.ScrollBarThickness = 3
logScroll.ScrollBarImageColor3 = C.acc
logScroll.AutomaticCanvasSize = Enum.AutomaticSize.Y
logScroll.CanvasSize = UDim2.new(0, 0, 0, 0)
logScroll.BorderSizePixel = 0
logScroll.Parent = logFrame

local logLayout = Instance.new("UIListLayout", logScroll)
logLayout.Padding = UDim.new(0, 2)
logLayout.SortOrder = Enum.SortOrder.LayoutOrder

-- ========================
-- PAGE 2: BLOCKED REMOTES
-- ========================
local p2 = mkP("Blocked")

local blockControl = mkSc(p2, 1)
mkH(blockControl, "BLOCK REMOTES", 0)
mkT(blockControl, "🚫 Enable Blocking", 1, C.txt, function(v) blockEnabled = v end)
mkL(blockControl, "When ON, blocked remotes won't fire to server.", 2)

-- Block input
local blockInputSec = mkSc(p2, 2)
mkH(blockInputSec, "ADD REMOTE TO BLOCK LIST", 0)

local blockInput = Instance.new("TextBox")
blockInput.Size = UDim2.new(1, 0, 0, 28)
blockInput.BackgroundColor3 = C.drop
blockInput.Text = ""
blockInput.PlaceholderText = "Type remote name..."
blockInput.TextColor3 = C.txt
blockInput.PlaceholderColor3 = C.dim
blockInput.TextSize = 12
blockInput.Font = Enum.Font.Gotham
blockInput.BorderSizePixel = 0
blockInput.LayoutOrder = 1
blockInput.ClearTextOnFocus = false
blockInput.Parent = blockInputSec
Instance.new("UICorner", blockInput).CornerRadius = UDim.new(0, 5)
Instance.new("UIPadding", blockInput).PaddingLeft = UDim.new(0, 8)

mkB(blockInputSec, "➕ Add to Block List", 2, C.acc, function()
	local name = blockInput.Text
	if name ~= "" then
		blockedRemotes[name] = true
		blockInput.Text = ""
	end
end)

-- Blocked list display
local blockedListSec = mkSc(p2, 3)
mkH(blockedListSec, "BLOCKED LIST", 0)
local lblBlockedList = mkL(blockedListSec, "None", 1)

-- ========================
-- PAGE 3: SETTINGS
-- ========================
local p3 = mkP("Settings")

local filterSec = mkSc(p3, 1)
mkH(filterSec, "LOG FILTERS", 0)
mkT(filterSec, "📤 Log FireServer", 1, C.fire, function(v) logFireServer = v end)
mkT(filterSec, "📥 Log InvokeServer", 2, C.invoke, function(v) logInvokeServer = v end)
mkT(filterSec, "📩 Log OnClientEvent", 3, C.onclient, function(v) logOnClientEvent = v end)

local exportSec = mkSc(p3, 2)
mkH(exportSec, "EXPORT", 0)
mkB(exportSec, "📋 Copy Last Log to Clipboard", 1, C.accAlt, function()
	if #logs > 0 then
		local entry = logs[1]
		if setclipboard then
			setclipboard(entry.code)
		elseif toclipboard then
			toclipboard(entry.code)
		end
	end
end)

mkB(exportSec, "📋 Copy All Logs", 2, C.accAlt, function()
	local allCode = {}
	for _, entry in ipairs(logs) do
		table.insert(allCode, "-- [" .. entry.timestamp .. "] " .. entry.type .. " > " .. entry.name)
		table.insert(allCode, entry.code)
		table.insert(allCode, "")
	end
	local text = table.concat(allCode, "\n")
	if setclipboard then
		setclipboard(text)
	elseif toclipboard then
		toclipboard(text)
	end
end)

-- ========================
-- PAGE 4: INFO
-- ========================
local p4 = mkP("Info")

local infoSec = mkSc(p4, 1)
mkH(infoSec, "HOOK STATUS", 0)
local lblHookStatus = mkL(infoSec, "Checking...", 1)
local lblRemoteCount = mkL(infoSec, "Remotes: 0", 2)
local lblLogCount = mkL(infoSec, "Logs: 0", 3)
local lblSpyStatus = mkL(infoSec, "Spy: Off", 4)

local capSec = mkSc(p4, 2)
mkH(capSec, "CAPABILITIES", 0)
mkL(capSec, "hookmetamethod: " .. (hookmetamethod and "✅" or "❌"), 1)
mkL(capSec, "hookfunction: " .. (hookfunction and "✅" or "❌"), 2)
mkL(capSec, "newcclosure: " .. (newcclosure and "✅" or "❌"), 3)
mkL(capSec, "getnamecallmethod: " .. (getnamecallmethod and "✅" or "❌"), 4)
mkL(capSec, "setclipboard: " .. (setclipboard and "✅" or "❌"), 5)
mkL(capSec, "firetouchinterest: " .. (firetouchinterest and "✅" or "❌"), 6)
mkL(capSec, "getconnections: " .. (getconnections and "✅" or "❌"), 7)

if namecallHooked then
	lblHookStatus.Text = "Hook: ✅ __namecall hooked (full spy)"
	lblHookStatus.TextColor3 = C.on
elseif fireHooked then
	lblHookStatus.Text = "Hook: ⚠ FireServer hooked (partial)"
	lblHookStatus.TextColor3 = C.warn
else
	lblHookStatus.Text = "Hook: ❌ No hook available (OnClientEvent only)"
	lblHookStatus.TextColor3 = C.off
end

local tipsSec = mkSc(p4, 3)
mkH(tipsSec, "ANTI-CHEAT TESTING TIPS", 0)
mkL(tipsSec, "1. Enable spy and play your game normally", 1)
mkL(tipsSec, "2. Watch what remotes fire during actions", 2)
mkL(tipsSec, "3. Try blocking critical remotes to test validation", 3)
mkL(tipsSec, "4. Check if server validates args or trusts client", 4)
mkL(tipsSec, "5. Copy remote calls and replay with modified args", 5)
mkL(tipsSec, "6. Test if rate-limiting exists by spamming remotes", 6)

local infoSec2 = mkSc(p4, 4)
mkH(infoSec2, "INFO", 0)
mkL(infoSec2, "Minimize: RightCtrl", 1)
mkL(infoSec2, "🔍 Remote Spy v1.0", 2)
mkL(infoSec2, "For anti-cheat testing only", 3)

-- ========================
-- DRAG
-- ========================
do
	local dg, di, ds, sp = false, nil, nil, nil
	Bar.InputBegan:Connect(function(i)
		if i.UserInputType == Enum.UserInputType.MouseButton1 then
			dg = true; ds = i.Position; sp = Main.Position
			i.Changed:Connect(function()
				if i.UserInputState == Enum.UserInputState.End then dg = false end
			end)
		end
	end)
	Bar.InputChanged:Connect(function(i)
		if i.UserInputType == Enum.UserInputType.MouseMovement then di = i end
	end)
	UserInputService.InputChanged:Connect(function(i)
		if i == di and dg then
			local d = i.Position - ds
			Main.Position = UDim2.new(sp.X.Scale, sp.X.Offset + d.X, sp.Y.Scale, sp.Y.Offset + d.Y)
		end
	end)
end

-- MINIMIZE
local full = Main.Size
local function toggleMin()
	minimized = not minimized
	if minimized then
		CA.Visible = false; TB.Visible = false
		TweenService:Create(Main, TweenInfo.new(0.2), {Size = UDim2.new(0, 500, 0, 40)}):Play()
		MinBtn.Text = "+"
	else
		TweenService:Create(Main, TweenInfo.new(0.2), {Size = full}):Play()
		task.delay(0.2, function() CA.Visible = true; TB.Visible = true end)
		MinBtn.Text = "—"
	end
end
MinBtn.MouseButton1Click:Connect(toggleMin)
UserInputService.InputBegan:Connect(function(i, g)
	if not g and i.KeyCode == Enum.KeyCode.RightControl then toggleMin() end
end)

-- ========================
-- UPDATE LOOPS
-- ========================

-- Update log display
local lastLogCount = 0

task.spawn(function()
	while true do
		-- Update log display if new logs
		if #logs ~= lastLogCount then
			lastLogCount = #logs

			-- Clear old log entries
			for _, child in ipairs(logScroll:GetChildren()) do
				if child:IsA("TextButton") then child:Destroy() end
			end

			-- Show latest 50 logs
			local showCount = math.min(#logs, 50)
			for i = 1, showCount do
				local entry = logs[i]
				local color = C.fire
				if entry.type == "InvokeServer" then color = C.invoke end
				if entry.type == "OnClientEvent" then color = C.onclient end
				if entry.blocked then color = C.blocked end

				local logBtn = Instance.new("TextButton")
				logBtn.Size = UDim2.new(1, 0, 0, 0)
				logBtn.AutomaticSize = Enum.AutomaticSize.Y
				logBtn.BackgroundColor3 = C.sec
				logBtn.BorderSizePixel = 0
				logBtn.LayoutOrder = i
				logBtn.Parent = logScroll
				logBtn.TextXAlignment = Enum.TextXAlignment.Left
				logBtn.Font = Enum.Font.Code
				logBtn.TextSize = 10
				logBtn.TextWrapped = true
				logBtn.TextColor3 = color
				Instance.new("UICorner", logBtn).CornerRadius = UDim.new(0, 4)
				Instance.new("UIPadding", logBtn).PaddingLeft = UDim.new(0, 6)

				local prefix = entry.blocked and "🚫 " or ""
				local typeIcon = ""
				if entry.type == "FireServer" then typeIcon = "📤 " end
				if entry.type == "InvokeServer" then typeIcon = "📥 " end
				if entry.type == "OnClientEvent" then typeIcon = "📩 " end

				logBtn.Text = prefix .. typeIcon .. "[" .. entry.timestamp .. "] " .. entry.name .. "\n" .. entry.argsText

				-- Click to copy code
				logBtn.MouseButton1Click:Connect(function()
					if setclipboard then
						setclipboard(entry.code)
					elseif toclipboard then
						toclipboard(entry.code)
					end
				end)
			end
		end

		-- Update info labels
		local remoteCount = 0
		for _ in pairs(hookedRemotes) do remoteCount += 1 end
		lblRemoteCount.Text = "Remotes Tracked: " .. remoteCount
		lblLogCount.Text = "Logs: " .. #logs .. "/" .. maxLogs
		lblSpyStatus.Text = "Spy: " .. (spyEnabled and "✅ Active" or "❌ Off")

		-- Update blocked list
		local blockedNames = {}
		for name in pairs(blockedRemotes) do
			table.insert(blockedNames, "🚫 " .. name)
		end
		if #blockedNames == 0 then
			lblBlockedList.Text = "None"
		else
			lblBlockedList.Text = table.concat(blockedNames, "\n")
		end

		task.wait(0.5)
	end
end)
