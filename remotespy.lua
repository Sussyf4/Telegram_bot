-- Remote Spy Pro - Anti-Cheat Development Tool
-- Execute with Script Executor (Synapse/Fluxus/etc)
-- For testing YOUR OWN game's security

local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local UserInputService = game:GetService("UserInputService")
local TweenService = game:GetService("TweenService")

local Player = Players.LocalPlayer

-- ========================
-- STATE
-- ========================
local spyEnabled = false
local blockEnabled = false
local minimized = false
local logs = {}
local maxLogs = 500
local blockedRemotes = {}
local ignoredRemotes = {}
local spamFilter = {}
local spamThreshold = 10 -- calls per second to flag as spam
local autoBlockSpam = false
local selectedLog = nil
local totalCalls = 0
local blockedCalls = 0

-- ========================
-- CHECK EXECUTOR CAPABILITIES
-- ========================
local hasHookMeta = type(hookmetamethod) == "function"
local hasHookFunc = type(hookfunction) == "function"
local hasNewCC = type(newcclosure) == "function"
local hasGetNM = type(getnamecallmethod) == "function"
local hasClipboard = type(setclipboard) == "function" or type(toclipboard) == "function"
local hasGetInfo = type(debug.getinfo) == "function" or type(getinfo) == "function"
local hasGetUpvals = type(debug.getupvalues) == "function" or type(getupvalues) == "function"
local hasGetConsts = type(debug.getconstants) == "function" or type(getconstants) == "function"
local hasGetGC = type(getgc) == "function"
local hasGetConnections = type(getconnections) == "function"
local hasGetProtos = type(getprotos) == "function"
local hasGetScriptClosure = type(getscriptclosure) == "function"
local hasCheckcaller = type(checkcaller) == "function"

local function toClip(text)
	if setclipboard then setclipboard(text)
	elseif toclipboard then toclipboard(text) end
end

-- ========================
-- SERIALIZE
-- ========================
local function serializeValue(v, depth)
	depth = depth or 0
	if depth > 4 then return "..." end
	local t = typeof(v)
	if t == "string" then
		if #v > 100 then return '"' .. v:sub(1, 100) .. '..."' end
		return '"' .. v:gsub('"', '\\"'):gsub("\n", "\\n") .. '"'
	elseif t == "number" then
		if v == math.floor(v) then return tostring(v) end
		return string.format("%.6f", v)
	elseif t == "boolean" then return tostring(v)
	elseif t == "nil" then return "nil"
	elseif t == "Instance" then return v:GetFullName()
	elseif t == "Vector3" then return string.format("Vector3.new(%.4f, %.4f, %.4f)", v.X, v.Y, v.Z)
	elseif t == "Vector2" then return string.format("Vector2.new(%.4f, %.4f)", v.X, v.Y)
	elseif t == "CFrame" then
		local p = v.Position
		local rx, ry, rz = v:ToEulerAnglesXYZ()
		return string.format("CFrame.new(%.4f, %.4f, %.4f) * CFrame.Angles(%.4f, %.4f, %.4f)", p.X, p.Y, p.Z, rx, ry, rz)
	elseif t == "Color3" then return string.format("Color3.new(%.4f, %.4f, %.4f)", v.R, v.G, v.B)
	elseif t == "BrickColor" then return 'BrickColor.new("' .. tostring(v) .. '")'
	elseif t == "UDim2" then return string.format("UDim2.new(%.4f, %d, %.4f, %d)", v.X.Scale, v.X.Offset, v.Y.Scale, v.Y.Offset)
	elseif t == "UDim" then return string.format("UDim.new(%.4f, %d)", v.Scale, v.Offset)
	elseif t == "Rect" then return string.format("Rect.new(%.1f, %.1f, %.1f, %.1f)", v.Min.X, v.Min.Y, v.Max.X, v.Max.Y)
	elseif t == "Ray" then return string.format("Ray.new(%s, %s)", serializeValue(v.Origin, depth+1), serializeValue(v.Direction, depth+1))
	elseif t == "NumberSequence" then return "NumberSequence.new(...)"
	elseif t == "ColorSequence" then return "ColorSequence.new(...)"
	elseif t == "NumberRange" then return string.format("NumberRange.new(%.4f, %.4f)", v.Min, v.Max)
	elseif t == "EnumItem" then return tostring(v)
	elseif t == "Enum" then return tostring(v)
	elseif t == "table" then
		local parts = {}
		local isArray = true
		local count = 0
		for k, _ in pairs(v) do
			count += 1
			if type(k) ~= "number" or k ~= count then isArray = false end
			if count > 20 then break end
		end
		count = 0
		for k, val in pairs(v) do
			count += 1
			if count > 20 then table.insert(parts, "... +" .. (select(2, next(v, k)) and "more" or "0")) break end
			if isArray then
				table.insert(parts, serializeValue(val, depth + 1))
			else
				local key
				if type(k) == "string" then
					if k:match("^[%a_][%w_]*$") then key = k
					else key = '["' .. k .. '"]' end
				else
					key = "[" .. serializeValue(k, depth + 1) .. "]"
				end
				table.insert(parts, key .. " = " .. serializeValue(val, depth + 1))
			end
		end
		return "{" .. table.concat(parts, ", ") .. "}"
	elseif t == "function" then
		return "function(...)"
	elseif t == "userdata" then
		return "userdata(" .. tostring(v) .. ")"
	else
		return t .. "(" .. tostring(v) .. ")"
	end
end

local function serializeArgs(args)
	if #args == 0 then return "(none)" end
	local parts = {}
	for i, v in ipairs(args) do
		parts[i] = "[" .. i .. "] = " .. serializeValue(v)
	end
	return table.concat(parts, "\n")
end

-- ========================
-- CODE GENERATOR
-- ========================
local function generateCode(entry)
	local lines = {}
	table.insert(lines, "-- " .. entry.type .. " > " .. entry.remotePath)
	table.insert(lines, "-- Time: " .. entry.timestamp)
	if entry.traceback then
		table.insert(lines, "-- Traceback: " .. entry.traceback)
	end
	table.insert(lines, "")

	local argCode = {}
	if #entry.args == 0 then
		table.insert(argCode, "local args = {}")
	else
		table.insert(argCode, "local args = {")
		for i, v in ipairs(entry.args) do
			local comma = i < #entry.args and "," or ""
			table.insert(argCode, "    [" .. i .. "] = " .. serializeValue(v) .. comma)
		end
		table.insert(argCode, "}")
	end

	for _, line in ipairs(argCode) do
		table.insert(lines, line)
	end

	local remotePath = entry.remotePath
	if entry.type == "FireServer" then
		table.insert(lines, 'game:GetService("ReplicatedStorage").' .. remotePath .. ":FireServer(unpack(args))")
	elseif entry.type == "InvokeServer" then
		table.insert(lines, 'game:GetService("ReplicatedStorage").' .. remotePath .. ":InvokeServer(unpack(args))")
	elseif entry.type == "Fire" then
		table.insert(lines, 'game:GetService("ReplicatedStorage").' .. remotePath .. ":Fire(unpack(args))")
	elseif entry.type == "Invoke" then
		table.insert(lines, 'game:GetService("ReplicatedStorage").' .. remotePath .. ":Invoke(unpack(args))")
	end

	return table.concat(lines, "\n")
end

-- ========================
-- TRACEBACK
-- ========================
local function getTraceback()
	if not hasGetInfo then return nil end

	local trace = {}
	local level = 4 -- skip our hook frames

	for i = level, level + 5 do
		local success, info
		if debug.getinfo then
			success, info = pcall(debug.getinfo, i)
		elseif getinfo then
			success, info = pcall(getinfo, i)
		end

		if not success or not info then break end

		local src = info.source or info.short_src or "?"
		local line = info.currentline or info.linedefined or "?"
		local name = info.name or "anonymous"

		table.insert(trace, src .. ":" .. line .. " (" .. name .. ")")
	end

	if #trace == 0 then return nil end
	return table.concat(trace, " → ")
end

-- ========================
-- GET REMOTE PATH
-- ========================
local function getRemotePath(remote)
	local path = {}
	local current = remote
	while current and current ~= game do
		table.insert(path, 1, current.Name)
		current = current.Parent
	end
	-- Remove "ReplicatedStorage" from start if present
	if path[1] == "ReplicatedStorage" then table.remove(path, 1) end
	return table.concat(path, ".")
end

-- ========================
-- SPAM DETECTION
-- ========================
local function checkSpam(remoteName)
	local now = os.clock()
	if not spamFilter[remoteName] then
		spamFilter[remoteName] = {count = 0, lastReset = now, flagged = false}
	end

	local data = spamFilter[remoteName]

	if now - data.lastReset > 1 then
		data.count = 0
		data.lastReset = now
		data.flagged = false
	end

	data.count += 1

	if data.count >= spamThreshold and not data.flagged then
		data.flagged = true
		if autoBlockSpam then
			ignoredRemotes[remoteName] = true
		end
		return true
	end

	return data.flagged
end

-- ========================
-- ADD LOG
-- ========================
local function addLog(remote, callType, args, wasBlocked)
	local remoteName = remote.Name
	local remotePath = getRemotePath(remote)
	local isSpam = checkSpam(remoteName)

	if ignoredRemotes[remoteName] then return end

	totalCalls += 1
	if wasBlocked then blockedCalls += 1 end

	local entry = {
		id = totalCalls,
		time = os.clock(),
		timestamp = os.date("%H:%M:%S"),
		name = remoteName,
		remotePath = remotePath,
		remoteClass = remote.ClassName,
		type = callType,
		args = args,
		argsText = serializeArgs(args),
		argCount = #args,
		blocked = wasBlocked,
		spam = isSpam,
		traceback = getTraceback(),
	}

	entry.code = generateCode(entry)

	table.insert(logs, 1, entry)
	if #logs > maxLogs then table.remove(logs, #logs) end

	return entry
end

-- ========================
-- HOOK SYSTEM
-- ========================
local hookActive = false

local function setupHooks()
	if hookActive then return end

	-- METHOD 1: hookmetamethod __namecall (best)
	if hasHookMeta and hasGetNM and hasNewCC then
		local oldNamecall
		oldNamecall = hookmetamethod(game, "__namecall", newcclosure(function(self, ...)
			if checkcaller and checkcaller() then
				return oldNamecall(self, ...)
			end

			local method = getnamecallmethod()
			local args = {...}

			if spyEnabled then
				-- RemoteEvent:FireServer
				if method == "FireServer" and self:IsA("RemoteEvent") then
					local wasBlocked = blockedRemotes[self.Name] == true and blockEnabled
					addLog(self, "FireServer", args, wasBlocked)
					if wasBlocked then return end
				end

				-- RemoteFunction:InvokeServer
				if method == "InvokeServer" and self:IsA("RemoteFunction") then
					local wasBlocked = blockedRemotes[self.Name] == true and blockEnabled
					addLog(self, "InvokeServer", args, wasBlocked)
					if wasBlocked then return nil end
				end

				-- BindableEvent:Fire
				if method == "Fire" and self:IsA("BindableEvent") then
					local wasBlocked = blockedRemotes[self.Name] == true and blockEnabled
					addLog(self, "Fire", args, wasBlocked)
					if wasBlocked then return end
				end

				-- BindableFunction:Invoke
				if method == "Invoke" and self:IsA("BindableFunction") then
					local wasBlocked = blockedRemotes[self.Name] == true and blockEnabled
					addLog(self, "Invoke", args, wasBlocked)
					if wasBlocked then return nil end
				end
			end

			return oldNamecall(self, ...)
		end))

		hookActive = true
		return "namecall"
	end

	-- METHOD 2: hookfunction (partial)
	if hasHookFunc and hasNewCC then
		-- Hook FireServer
		pcall(function()
			local ref = Instance.new("RemoteEvent")
			local oldFire = ref.FireServer
			hookfunction(oldFire, newcclosure(function(self, ...)
				if checkcaller and checkcaller() then
					return oldFire(self, ...)
				end
				if spyEnabled and self:IsA("RemoteEvent") then
					local args = {...}
					local wasBlocked = blockedRemotes[self.Name] == true and blockEnabled
					addLog(self, "FireServer", args, wasBlocked)
					if wasBlocked then return end
				end
				return oldFire(self, ...)
			end))
			ref:Destroy()
		end)

		-- Hook InvokeServer
		pcall(function()
			local ref = Instance.new("RemoteFunction")
			local oldInvoke = ref.InvokeServer
			hookfunction(oldInvoke, newcclosure(function(self, ...)
				if checkcaller and checkcaller() then
					return oldInvoke(self, ...)
				end
				if spyEnabled and self:IsA("RemoteFunction") then
					local args = {...}
					local wasBlocked = blockedRemotes[self.Name] == true and blockEnabled
					addLog(self, "InvokeServer", args, wasBlocked)
					if wasBlocked then return nil end
				end
				return oldInvoke(self, ...)
			end))
			ref:Destroy()
		end)

		hookActive = true
		return "hookfunction"
	end

	-- METHOD 3: OnClientEvent only (no executor needed)
	for _, desc in ipairs(game:GetDescendants()) do
		if desc:IsA("RemoteEvent") then
			pcall(function()
				desc.OnClientEvent:Connect(function(...)
					if spyEnabled then
						addLog(desc, "OnClientEvent", {...}, false)
					end
				end)
			end)
		end
	end

	game.DescendantAdded:Connect(function(desc)
		if desc:IsA("RemoteEvent") then
			pcall(function()
				desc.OnClientEvent:Connect(function(...)
					if spyEnabled then
						addLog(desc, "OnClientEvent", {...}, false)
					end
				end)
			end)
		end
	end)

	hookActive = true
	return "listener"
end

local hookMethod = setupHooks()

-- ========================
-- COLORS
-- ========================
local C = {
	bg = Color3.fromRGB(8, 8, 14),
	bar = Color3.fromRGB(14, 14, 24),
	barAccent = Color3.fromRGB(200, 40, 40),
	acc = Color3.fromRGB(200, 40, 40),
	accAlt = Color3.fromRGB(40, 130, 200),
	on = Color3.fromRGB(30, 170, 70),
	off = Color3.fromRGB(170, 30, 30),
	txt = Color3.fromRGB(215, 215, 230),
	dim = Color3.fromRGB(80, 80, 100),
	sec = Color3.fromRGB(12, 12, 22),
	brd = Color3.fromRGB(30, 30, 46),
	logBg = Color3.fromRGB(6, 6, 12),
	hover = Color3.fromRGB(24, 24, 38),
	fire = Color3.fromRGB(255, 130, 50),
	invoke = Color3.fromRGB(80, 180, 255),
	onclient = Color3.fromRGB(80, 255, 120),
	bindable = Color3.fromRGB(200, 150, 255),
	blocked = Color3.fromRGB(255, 40, 40),
	spam = Color3.fromRGB(255, 200, 40),
	tabA = Color3.fromRGB(200, 40, 40),
	tabI = Color3.fromRGB(18, 18, 30),
	tabTA = Color3.fromRGB(255, 255, 255),
	tabTI = Color3.fromRGB(70, 70, 90),
}

-- ========================
-- GUI
-- ========================
local Gui = Instance.new("ScreenGui")
Gui.Name = "RemoteSpyPro"
Gui.ResetOnSpawn = false
Gui.ZIndexBehavior = Enum.ZIndexBehavior.Sibling
Gui.Parent = Player:WaitForChild("PlayerGui")

local Main = Instance.new("Frame")
Main.Size = UDim2.new(0, 560, 0, 600)
Main.Position = UDim2.new(0.5, -280, 0.5, -300)
Main.BackgroundColor3 = C.bg
Main.BorderSizePixel = 0
Main.Active = true
Main.Parent = Gui
Instance.new("UICorner", Main).CornerRadius = UDim.new(0, 8)
Instance.new("UIStroke", Main).Color = C.brd

local Bar = Instance.new("Frame")
Bar.Size = UDim2.new(1, 0, 0, 36)
Bar.BackgroundColor3 = C.bar
Bar.BorderSizePixel = 0
Bar.Parent = Main
Instance.new("UICorner", Bar).CornerRadius = UDim.new(0, 8)
local bf = Instance.new("Frame"); bf.Size = UDim2.new(1, 0, 0, 10); bf.Position = UDim2.new(0, 0, 1, -10); bf.BackgroundColor3 = C.bar; bf.BorderSizePixel = 0; bf.Parent = Bar
local al = Instance.new("Frame"); al.Size = UDim2.new(1, -16, 0, 2); al.Position = UDim2.new(0, 8, 1, -1); al.BackgroundColor3 = C.barAccent; al.BorderSizePixel = 0; al.Parent = Bar

local lg = Instance.new("TextLabel")
lg.Size = UDim2.new(0, 300, 1, 0); lg.Position = UDim2.new(0, 12, 0, 0)
lg.BackgroundTransparency = 1; lg.Text = "🔍 Remote Spy Pro"
lg.TextColor3 = C.txt; lg.TextSize = 14; lg.Font = Enum.Font.GothamBold
lg.TextXAlignment = Enum.TextXAlignment.Left; lg.Parent = Bar

local MinBtn = Instance.new("TextButton")
MinBtn.Size = UDim2.new(0, 24, 0, 24); MinBtn.Position = UDim2.new(1, -34, 0, 6)
MinBtn.BackgroundColor3 = C.acc; MinBtn.Text = "—"; MinBtn.TextColor3 = C.txt
MinBtn.TextSize = 14; MinBtn.Font = Enum.Font.GothamBold; MinBtn.BorderSizePixel = 0; MinBtn.Parent = Bar
Instance.new("UICorner", MinBtn).CornerRadius = UDim.new(0, 5)

-- TABS
local TB = Instance.new("Frame")
TB.Size = UDim2.new(1, -16, 0, 26); TB.Position = UDim2.new(0, 8, 0, 40)
TB.BackgroundTransparency = 1; TB.Parent = Main
local tbl = Instance.new("UIListLayout", TB)
tbl.FillDirection = Enum.FillDirection.Horizontal; tbl.Padding = UDim.new(0, 3); tbl.SortOrder = Enum.SortOrder.LayoutOrder

local tabButtons = {}; local tabPages = {}
for i, info in ipairs({{"Spy","🔍 Live Spy"},{"Detail","📋 Detail"},{"Block","🚫 Block"},{"Config","⚙ Config"},{"Info","📊 Info"}}) do
	local b = Instance.new("TextButton")
	b.Size = UDim2.new(0, 104, 1, 0)
	b.BackgroundColor3 = i == 1 and C.tabA or C.tabI
	b.Text = info[2]; b.TextColor3 = i == 1 and C.tabTA or C.tabTI
	b.TextSize = 10; b.Font = Enum.Font.GothamBold; b.BorderSizePixel = 0
	b.LayoutOrder = i; b.Parent = TB
	Instance.new("UICorner", b).CornerRadius = UDim.new(0, 4)
	tabButtons[info[1]] = b
end

local CA = Instance.new("Frame")
CA.Size = UDim2.new(1, -16, 1, -74); CA.Position = UDim2.new(0, 8, 0, 70)
CA.BackgroundTransparency = 1; CA.ClipsDescendants = true; CA.Parent = Main

-- HELPERS
local function mkP(n)
	local p = Instance.new("ScrollingFrame"); p.Size = UDim2.new(1, 0, 1, 0)
	p.BackgroundTransparency = 1; p.ScrollBarThickness = 3; p.ScrollBarImageColor3 = C.acc
	p.AutomaticCanvasSize = Enum.AutomaticSize.Y; p.CanvasSize = UDim2.new(0, 0, 0, 0)
	p.BorderSizePixel = 0; p.Visible = (n == "Spy"); p.Name = n; p.Parent = CA
	local l = Instance.new("UIListLayout", p); l.Padding = UDim.new(0, 4); l.SortOrder = Enum.SortOrder.LayoutOrder
	tabPages[n] = p; return p
end

local function mkSc(p, o)
	local f = Instance.new("Frame"); f.Size = UDim2.new(1, 0, 0, 0); f.AutomaticSize = Enum.AutomaticSize.Y
	f.BackgroundColor3 = C.sec; f.BorderSizePixel = 0; f.LayoutOrder = o; f.Parent = p
	Instance.new("UICorner", f).CornerRadius = UDim.new(0, 6); Instance.new("UIStroke", f).Color = C.brd
	local pd = Instance.new("UIPadding", f); pd.PaddingTop = UDim.new(0, 6); pd.PaddingBottom = UDim.new(0, 6); pd.PaddingLeft = UDim.new(0, 8); pd.PaddingRight = UDim.new(0, 8)
	local l = Instance.new("UIListLayout", f); l.Padding = UDim.new(0, 3); l.SortOrder = Enum.SortOrder.LayoutOrder
	return f
end

local function mkH(p, t, o)
	local l = Instance.new("TextLabel"); l.Size = UDim2.new(1, 0, 0, 14); l.BackgroundTransparency = 1
	l.Text = t; l.TextColor3 = C.acc; l.TextSize = 10; l.Font = Enum.Font.GothamBold
	l.TextXAlignment = Enum.TextXAlignment.Left; l.LayoutOrder = o; l.Parent = p
end

local function mkL(p, t, o)
	local l = Instance.new("TextLabel"); l.Size = UDim2.new(1, 0, 0, 14); l.AutomaticSize = Enum.AutomaticSize.Y
	l.BackgroundTransparency = 1; l.Text = t; l.TextColor3 = C.dim; l.TextSize = 10
	l.Font = Enum.Font.Gotham; l.TextXAlignment = Enum.TextXAlignment.Left; l.TextWrapped = true
	l.LayoutOrder = o; l.Parent = p; return l
end

local function mkT(p, n, o, defaultOn, lc, cb)
	local r = Instance.new("Frame"); r.Size = UDim2.new(1, 0, 0, 24); r.BackgroundTransparency = 1; r.LayoutOrder = o; r.Parent = p
	local l = Instance.new("TextLabel"); l.Size = UDim2.new(1, -50, 1, 0); l.BackgroundTransparency = 1
	l.Text = n; l.TextColor3 = lc or C.txt; l.TextSize = 11; l.Font = Enum.Font.GothamMedium
	l.TextXAlignment = Enum.TextXAlignment.Left; l.Parent = r
	local b = Instance.new("TextButton"); b.Size = UDim2.new(0, 42, 0, 18); b.Position = UDim2.new(1, -42, 0.5, -9)
	b.BackgroundColor3 = defaultOn and C.on or C.off; b.Text = defaultOn and "ON" or "OFF"
	b.TextColor3 = Color3.new(1, 1, 1); b.TextSize = 9; b.Font = Enum.Font.GothamBold
	b.BorderSizePixel = 0; b.Parent = r; Instance.new("UICorner", b).CornerRadius = UDim.new(0, 4)
	local on = defaultOn or false
	b.MouseButton1Click:Connect(function() on = not on; b.BackgroundColor3 = on and C.on or C.off; b.Text = on and "ON" or "OFF"; cb(on) end)
end

local function mkB(p, n, o, c, cb)
	local b = Instance.new("TextButton"); b.Size = UDim2.new(1, 0, 0, 24); b.BackgroundColor3 = c or C.acc
	b.Text = n; b.TextColor3 = Color3.new(1, 1, 1); b.TextSize = 10; b.Font = Enum.Font.GothamBold
	b.BorderSizePixel = 0; b.LayoutOrder = o; b.Parent = p; Instance.new("UICorner", b).CornerRadius = UDim.new(0, 4)
	b.MouseButton1Click:Connect(function() if cb then cb() end end)
end

local function switchTab(tn)
	for n, pg in pairs(tabPages) do pg.Visible = (n == tn) end
	for n, bt in pairs(tabButtons) do bt.BackgroundColor3 = (n == tn) and C.tabA or C.tabI; bt.TextColor3 = (n == tn) and C.tabTA or C.tabTI end
end
for n, bt in pairs(tabButtons) do bt.MouseButton1Click:Connect(function() switchTab(n) end) end

-- ========================
-- PAGE 1: LIVE SPY
-- ========================
local p1 = mkP("Spy")

local spyCtrl = mkSc(p1, 1)
mkH(spyCtrl, "REMOTE SPY", 0)
mkT(spyCtrl, "🔍 Enable Spy", 1, false, C.txt, function(v) spyEnabled = v end)

local spyBtns = Instance.new("Frame"); spyBtns.Size = UDim2.new(1, 0, 0, 24); spyBtns.BackgroundTransparency = 1; spyBtns.LayoutOrder = 2; spyBtns.Parent = spyCtrl
local clearBtn = Instance.new("TextButton"); clearBtn.Size = UDim2.new(0.48, 0, 1, 0); clearBtn.BackgroundColor3 = Color3.fromRGB(150, 40, 40)
clearBtn.Text = "🗑 Clear"; clearBtn.TextColor3 = C.txt; clearBtn.TextSize = 10; clearBtn.Font = Enum.Font.GothamBold; clearBtn.BorderSizePixel = 0; clearBtn.Parent = spyBtns
Instance.new("UICorner", clearBtn).CornerRadius = UDim.new(0, 4)
clearBtn.MouseButton1Click:Connect(function() logs = {}; totalCalls = 0; blockedCalls = 0 end)

local copyAllBtn = Instance.new("TextButton"); copyAllBtn.Size = UDim2.new(0.48, 0, 1, 0); copyAllBtn.Position = UDim2.new(0.52, 0, 0, 0)
copyAllBtn.BackgroundColor3 = C.accAlt; copyAllBtn.Text = "📋 Copy All"; copyAllBtn.TextColor3 = C.txt
copyAllBtn.TextSize = 10; copyAllBtn.Font = Enum.Font.GothamBold; copyAllBtn.BorderSizePixel = 0; copyAllBtn.Parent = spyBtns
Instance.new("UICorner", copyAllBtn).CornerRadius = UDim.new(0, 4)
copyAllBtn.MouseButton1Click:Connect(function()
	local all = {}
	for _, e in ipairs(logs) do table.insert(all, e.code); table.insert(all, "") end
	toClip(table.concat(all, "\n"))
end)

local lblStats = mkL(spyCtrl, "Calls: 0 | Blocked: 0", 3)

-- Log display
local logFrame = Instance.new("Frame")
logFrame.Size = UDim2.new(1, 0, 0, 400); logFrame.BackgroundColor3 = C.logBg; logFrame.BorderSizePixel = 0
logFrame.LayoutOrder = 2; logFrame.Parent = p1; Instance.new("UICorner", logFrame).CornerRadius = UDim.new(0, 5)
Instance.new("UIStroke", logFrame).Color = C.brd

local logScroll = Instance.new("ScrollingFrame")
logScroll.Size = UDim2.new(1, -6, 1, -6); logScroll.Position = UDim2.new(0, 3, 0, 3)
logScroll.BackgroundTransparency = 1; logScroll.ScrollBarThickness = 3; logScroll.ScrollBarImageColor3 = C.acc
logScroll.AutomaticCanvasSize = Enum.AutomaticSize.Y; logScroll.CanvasSize = UDim2.new(0, 0, 0, 0)
logScroll.BorderSizePixel = 0; logScroll.Parent = logFrame
local logLayout = Instance.new("UIListLayout", logScroll); logLayout.Padding = UDim.new(0, 2); logLayout.SortOrder = Enum.SortOrder.LayoutOrder

-- ========================
-- PAGE 2: DETAIL VIEW
-- ========================
local p2 = mkP("Detail")
local detailSec = mkSc(p2, 1)
mkH(detailSec, "SELECTED LOG DETAIL", 0)
local lblDetailName = mkL(detailSec, "Name: (click a log entry)", 1)
local lblDetailType = mkL(detailSec, "Type: ---", 2)
local lblDetailPath = mkL(detailSec, "Path: ---", 3)
local lblDetailClass = mkL(detailSec, "Class: ---", 4)
local lblDetailTime = mkL(detailSec, "Time: ---", 5)
local lblDetailArgCount = mkL(detailSec, "Arg Count: ---", 6)
local lblDetailBlocked = mkL(detailSec, "Blocked: ---", 7)
local lblDetailSpam = mkL(detailSec, "Spam: ---", 8)
local lblDetailTrace = mkL(detailSec, "Traceback: ---", 9)

local argsSec = mkSc(p2, 2)
mkH(argsSec, "ARGUMENTS", 0)
local lblDetailArgs = mkL(argsSec, "(none)", 1)

local codeSec = mkSc(p2, 3)
mkH(codeSec, "GENERATED CODE", 0)
local lblDetailCode = mkL(codeSec, "(none)", 1)
lblDetailCode.Font = Enum.Font.Code; lblDetailCode.TextSize = 9

mkB(codeSec, "📋 Copy Code", 2, C.accAlt, function()
	if selectedLog then toClip(selectedLog.code) end
end)

mkB(codeSec, "🚫 Block This Remote", 3, C.acc, function()
	if selectedLog then
		blockedRemotes[selectedLog.name] = true
	end
end)

mkB(codeSec, "👁 Ignore This Remote", 4, Color3.fromRGB(150, 100, 40), function()
	if selectedLog then
		ignoredRemotes[selectedLog.name] = true
	end
end)

-- ========================
-- PAGE 3: BLOCK LIST
-- ========================
local p3 = mkP("Block")

local blockCtrl = mkSc(p3, 1)
mkH(blockCtrl, "BLOCKING", 0)
mkT(blockCtrl, "🚫 Enable Blocking", 1, false, C.txt, function(v) blockEnabled = v end)
mkT(blockCtrl, "⚡ Auto-Block Spam", 2, false, C.spam, function(v) autoBlockSpam = v end)
mkL(blockCtrl, "Spam threshold: " .. spamThreshold .. " calls/sec", 3)

local blockInputSec = mkSc(p3, 2)
mkH(blockInputSec, "ADD TO BLOCK LIST", 0)
local blockInput = Instance.new("TextBox")
blockInput.Size = UDim2.new(1, 0, 0, 24); blockInput.BackgroundColor3 = C.logBg
blockInput.Text = ""; blockInput.PlaceholderText = "Remote name..."
blockInput.TextColor3 = C.txt; blockInput.PlaceholderColor3 = C.dim
blockInput.TextSize = 11; blockInput.Font = Enum.Font.Gotham; blockInput.BorderSizePixel = 0
blockInput.LayoutOrder = 1; blockInput.ClearTextOnFocus = false; blockInput.Parent = blockInputSec
Instance.new("UICorner", blockInput).CornerRadius = UDim.new(0, 4)
Instance.new("UIPadding", blockInput).PaddingLeft = UDim.new(0, 6)
mkB(blockInputSec, "➕ Block", 2, C.acc, function()
	if blockInput.Text ~= "" then blockedRemotes[blockInput.Text] = true; blockInput.Text = "" end
end)
mkB(blockInputSec, "🔇 Ignore (hide from log)", 3, Color3.fromRGB(150, 100, 40), function()
	if blockInput.Text ~= "" then ignoredRemotes[blockInput.Text] = true; blockInput.Text = "" end
end)

local blockedListSec = mkSc(p3, 3)
mkH(blockedListSec, "BLOCKED REMOTES", 0)
local lblBlockList = mkL(blockedListSec, "None", 1)

local ignoredListSec = mkSc(p3, 4)
mkH(ignoredListSec, "IGNORED REMOTES (hidden from log)", 0)
local lblIgnoreList = mkL(ignoredListSec, "None", 1)

mkB(p3, "🗑 Clear All Blocks", 5, Color3.fromRGB(150, 40, 40), function() blockedRemotes = {} end)
mkB(p3, "🗑 Clear All Ignores", 6, Color3.fromRGB(150, 100, 40), function() ignoredRemotes = {} end)

-- ========================
-- PAGE 4: CONFIG
-- ========================
local p4 = mkP("Config")

local filterSec = mkSc(p4, 1)
mkH(filterSec, "LOG FILTERS", 0)
mkT(filterSec, "📤 FireServer", 1, true, C.fire, function(v)
	-- handled in hook
end)
mkT(filterSec, "📥 InvokeServer", 2, true, C.invoke, function(v) end)
mkT(filterSec, "📩 OnClientEvent", 3, true, C.onclient, function(v) end)
mkT(filterSec, "🔗 BindableEvent/Function", 4, true, C.bindable, function(v) end)

local perfSec = mkSc(p4, 2)
mkH(perfSec, "PERFORMANCE", 0)
mkL(perfSec, "Max logs stored: " .. maxLogs, 1)
mkL(perfSec, "Log refresh rate: 0.3s", 2)
mkL(perfSec, "Spam threshold: " .. spamThreshold .. " calls/sec", 3)

-- ========================
-- PAGE 5: INFO
-- ========================
local p5 = mkP("Info")

local hookSec = mkSc(p5, 1)
mkH(hookSec, "HOOK STATUS", 0)
local hookStatusText = "❌ No hooks"
if hookMethod == "namecall" then hookStatusText = "✅ __namecall hooked (full capture)"
elseif hookMethod == "hookfunction" then hookStatusText = "⚠ hookfunction (partial capture)"
elseif hookMethod == "listener" then hookStatusText = "📩 OnClientEvent only (no executor)" end
mkL(hookSec, hookStatusText, 1)

local capSec = mkSc(p5, 2)
mkH(capSec, "EXECUTOR CAPABILITIES", 0)
local caps = {
	{"hookmetamethod", hasHookMeta},
	{"hookfunction", hasHookFunc},
	{"newcclosure", hasNewCC},
	{"getnamecallmethod", hasGetNM},
	{"checkcaller", hasCheckcaller},
	{"setclipboard", hasClipboard},
	{"debug.getinfo", hasGetInfo},
	{"debug.getupvalues", hasGetUpvals},
	{"debug.getconstants", hasGetConsts},
	{"getgc", hasGetGC},
	{"getconnections", hasGetConnections},
	{"getprotos", hasGetProtos},
	{"getscriptclosure", hasGetScriptClosure},
}
for i, cap in ipairs(caps) do
	mkL(capSec, (cap[2] and "✅ " or "❌ ") .. cap[1], i)
end

local whatSec = mkSc(p5, 3)
mkH(whatSec, "WHAT EACH CAPTURES", 0)
mkL(whatSec, "📤 FireServer - Client → Server remote events", 1)
mkL(whatSec, "📥 InvokeServer - Client → Server remote functions", 2)
mkL(whatSec, "📩 OnClientEvent - Server → Client events", 3)
mkL(whatSec, "🔗 Fire/Invoke - Bindable events/functions", 4)
mkL(whatSec, "🚫 Block - Prevents call from reaching server", 5)
mkL(whatSec, "🔇 Ignore - Hides from log (still fires)", 6)
mkL(whatSec, "⚡ Spam - Flags remotes firing 10+/sec", 7)

local tipSec = mkSc(p5, 4)
mkH(tipSec, "ANTI-CHEAT TEST CHECKLIST", 0)
mkL(tipSec, "□ Does server validate all remote arguments?", 1)
mkL(tipSec, "□ Can you fire remotes with wrong types?", 2)
mkL(tipSec, "□ Is there rate limiting on critical remotes?", 3)
mkL(tipSec, "□ What happens if you block heartbeat remotes?", 4)
mkL(tipSec, "□ Can you replay purchase/damage remotes?", 5)
mkL(tipSec, "□ Are magnitude/distance checks server-side?", 6)
mkL(tipSec, "□ Does blocking movement remotes get detected?", 7)
mkL(tipSec, "□ Can you send negative values (negative damage)?", 8)

-- ========================
-- DRAG
-- ========================
do
	local dg, di, ds, sp = false, nil, nil, nil
	Bar.InputBegan:Connect(function(i)
		if i.UserInputType == Enum.UserInputType.MouseButton1 then
			dg = true; ds = i.Position; sp = Main.Position
			i.Changed:Connect(function() if i.UserInputState == Enum.UserInputState.End then dg = false end end)
		end
	end)
	Bar.InputChanged:Connect(function(i) if i.UserInputType == Enum.UserInputType.MouseMovement then di = i end end)
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
		TweenService:Create(Main, TweenInfo.new(0.2), {Size = UDim2.new(0, 560, 0, 36)}):Play()
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
-- UPDATE LOOP
-- ========================
local lastLogCount = 0

task.spawn(function()
	while true do
		lblStats.Text = "Calls: " .. totalCalls .. " | Blocked: " .. blockedCalls .. " | Logs: " .. #logs

		-- Update log display
		if #logs ~= lastLogCount then
			lastLogCount = #logs

			for _, child in ipairs(logScroll:GetChildren()) do
				if child:IsA("TextButton") then child:Destroy() end
			end

			local showCount = math.min(#logs, 60)
			for i = 1, showCount do
				local entry = logs[i]
				local color = C.fire
				if entry.type == "InvokeServer" then color = C.invoke end
				if entry.type == "OnClientEvent" then color = C.onclient end
				if entry.type == "Fire" or entry.type == "Invoke" then color = C.bindable end
				if entry.blocked then color = C.blocked end
				if entry.spam then color = C.spam end

				local logBtn = Instance.new("TextButton")
				logBtn.Size = UDim2.new(1, 0, 0, 0)
				logBtn.AutomaticSize = Enum.AutomaticSize.Y
				logBtn.BackgroundColor3 = C.sec
				logBtn.BorderSizePixel = 0
				logBtn.LayoutOrder = i
				logBtn.Parent = logScroll
				logBtn.TextXAlignment = Enum.TextXAlignment.Left
				logBtn.Font = Enum.Font.Code
				logBtn.TextSize = 9
				logBtn.TextWrapped = true
				logBtn.TextColor3 = color
				Instance.new("UICorner", logBtn).CornerRadius = UDim.new(0, 3)
				local lp = Instance.new("UIPadding", logBtn)
				lp.PaddingLeft = UDim.new(0, 4); lp.PaddingTop = UDim.new(0, 2); lp.PaddingBottom = UDim.new(0, 2)

				local icon = ""
				if entry.type == "FireServer" then icon = "📤" end
				if entry.type == "InvokeServer" then icon = "📥" end
				if entry.type == "OnClientEvent" then icon = "📩" end
				if entry.type == "Fire" then icon = "🔗" end
				if entry.type == "Invoke" then icon = "🔗" end
				local prefix = entry.blocked and "🚫" or (entry.spam and "⚡" or icon)

				logBtn.Text = prefix .. " [" .. entry.timestamp .. "] " .. entry.type .. " > " .. entry.name .. " (" .. entry.argCount .. " args)"

				-- Click to view detail
				local capturedEntry = entry
				logBtn.MouseButton1Click:Connect(function()
					selectedLog = capturedEntry
					switchTab("Detail")

					lblDetailName.Text = "Name: " .. capturedEntry.name
					lblDetailType.Text = "Type: " .. capturedEntry.type
					lblDetailPath.Text = "Path: " .. capturedEntry.remotePath
					lblDetailClass.Text = "Class: " .. (capturedEntry.remoteClass or "?")
					lblDetailTime.Text = "Time: " .. capturedEntry.timestamp .. " (" .. string.format("%.3f", capturedEntry.time) .. ")"
					lblDetailArgCount.Text = "Arg Count: " .. capturedEntry.argCount
					lblDetailBlocked.Text = "Blocked: " .. (capturedEntry.blocked and "YES" or "No")
					lblDetailSpam.Text = "Spam: " .. (capturedEntry.spam and "YES ⚡" or "No")
					lblDetailTrace.Text = "Traceback: " .. (capturedEntry.traceback or "N/A")
					lblDetailArgs.Text = capturedEntry.argsText
					lblDetailCode.Text = capturedEntry.code
				end)
			end
		end

		-- Update block/ignore lists
		local bNames = {}
		for name in pairs(blockedRemotes) do table.insert(bNames, "🚫 " .. name) end
		lblBlockList.Text = #bNames > 0 and table.concat(bNames, "\n") or "None"

		local iNames = {}
		for name in pairs(ignoredRemotes) do table.insert(iNames, "🔇 " .. name) end
		lblIgnoreList.Text = #iNames > 0 and table.concat(iNames, "\n") or "None"

		task.wait(0.3)
	end
end)
