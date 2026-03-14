-- LocalScript: Place inside StarterPlayerScripts or StarterGui

local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local UserInputService = game:GetService("UserInputService")
local TweenService = game:GetService("TweenService")
local TeleportService = game:GetService("TeleportService")
local HttpService = game:GetService("HttpService")

local Player = Players.LocalPlayer

local function waitChar()
	local c = Player.Character or Player.CharacterAdded:Wait()
	c:WaitForChild("HumanoidRootPart")
	return c
end

local Char = waitChar()
Player.CharacterAdded:Connect(function(c)
	Char = c
	c:WaitForChild("HumanoidRootPart")
end)

local autoMonsterOn = false
local autoPetOn = false
local autoRejoinOn = false
local minimized = false
local selectedLevel = nil
local farmSpeed = 0.5
local touchHits = 5

-- ========================
-- MONSTER MAP
-- ========================
local MONSTER_TO_LEVEL = {}
local LEVEL_MONSTERS = {}

local function reg(level, names)
	LEVEL_MONSTERS[level] = names
	for _, name in ipairs(names) do
		MONSTER_TO_LEVEL[name:lower()] = level
	end
end

reg(1, {"monster11","monster12","monster13","monster14","monster15","monster16","monster17","monster18","monster19","monster110"})
reg(2, {"monster212","monster213","monster214","monster215","monster216","monster217"})
reg(3, {"monster320","monster321","monster322","monster323","monster324","monster325","monster326","monster327","monster328"})
reg(4, {"monster430","monster431","monster432","monster433","monster435","monster436"})
reg(5, {"monster537","monster538","monster540","monster541","monster542","monster543"})
reg(6, {"monster644","monster645","monster646"})
reg(7, {"monster748"})
reg(8, {"monster857","monster858","monster859","monster860","monster861","monster862","monster863","monster864","monster865"})
reg(10, {"monster1074","monster1075","monster1076","monster1077","monster1078","monster1079","monster1080","monster1081","monster1082"})
reg(11, {"monster1183","monster1184","monster1185","monster1186","monster1187","monster1188","monster1189"})
reg(12, {"monster1290","monster1291","monster1292","monster1293","monster1294","monster1295"})
reg(13, {"monster13100","monster13101","monster1396","monster1397","monster1398","monster1399"})
reg(14, {"monster14102"})
reg(15, {"monster15146","monster15147","monster15148","monster15149","monster15150","monster15151","monster15152"})
reg(16, {"monster16103","monster16104","monster16105","monster16106","monster16107","monster16108","monster16109","monster16110","monster16111"})
reg(17, {"monster17112","monster17113","monster17114","monster17115","monster17116","monster17117","monster17118","monster17119","monster17120"})
reg(18, {"monster18121","monster18122","monster18123","monster18124","monster18125","monster18126","monster18127"})
reg(19, {"monster19128","monster19129","monster19130","monster19131","monster19132","monster19133","monster19134","monster19135","monster19136"})
reg(20, {"monster20137","monster20138","monster20139","monster20140","monster20141","monster20142","monster20143","monster20144"})
reg(21, {"monster21145"})
reg(22, {"monster22153","monster22154","monster22155","monster22156","monster22157","monster22158","monster22159","monster22160"})
reg(23, {"monster23161","monster23162","monster23163","monster23164","monster23165","monster23166","monster23167","monster23168"})
reg(24, {"monster24169","monster24170","monster24171","monster24172","monster24173","monster24174","monster24175"})
reg(25, {"monster25176","monster25177","monster25178","monster25179","monster25180","monster25181","monster25182","monster25183"})
reg(26, {"monster26184","monster26185","monster26186","monster26187","monster26188","monster26189","monster26190","monster26191"})
reg(27, {"monster27192","monster27193","monster27194","monster27195","monster27196","monster27197"})
reg(28, {"monster28198"})
reg(29, {"monster29199","monster29200","monster29201","monster29202","monster29203","monster29204","monster29205","monster29206","monster29207","monster29208","monster29209"})
reg(30, {"monster30210","monster30211","monster30212","monster30213","monster30214","monster30215","monster30216","monster30217","monster30218","monster30219","monster30220"})
reg(31, {"monster31221","monster31222","monster31223","monster31224","monster31225","monster31226","monster31227","monster31228","monster31229","monster31230","monster31231","monster31232","monster31233"})
reg(32, {"monster32234","monster32235","monster32236","monster32237","monster32238","monster32239","monster32240","monster32241","monster32242","monster32243"})
reg(33, {"monster33244","monster33245","monster33246","monster33247","monster33248","monster33249","monster33250","monster33251","monster33252","monster33253"})
reg(34, {"monster34254","monster34255","monster34256","monster34257","monster34258","monster34259","monster34260","monster34261"})
reg(35, {"monster35263"})
reg(36, {"monster36264","monster36265","monster36266","monster36267","monster36268","monster36269","monster36270","monster36271"})
reg(37, {"monster37272","monster37273","monster37274","monster37275","monster37276","monster37277","monster37278","monster37279"})
reg(38, {"monster38280","monster38281","monster38282","monster38283","monster38284","monster38285","monster38286","monster38287"})
reg(39, {"monster39288","monster39289","monster39290","monster39291","monster39292","monster39293","monster39294","monster39295"})
reg(40, {"monster40296","monster40297","monster40298","monster40299","monster40300","monster40301","monster40302","monster40303","monster40304"})
reg(41, {"monster41305","monster41306","monster41307","monster41308","monster41309","monster41310","monster41311","monster41312"})
reg(42, {"monster42313"})
reg(43, {"monster43314","monster43315","monster43316","monster43317","monster43318","monster43319","monster43320","monster43321"})
reg(44, {"monster44322","monster44323","monster44324","monster44325","monster44326","monster44327","monster44328","monster44329"})
reg(45, {"monster45330","monster45331","monster45332","monster45333","monster45334","monster45335","monster45336"})
reg(46, {"monster46337","monster46338","monster46339","monster46340","monster46341","monster46342","monster46343","monster46344"})
reg(47, {"monster47345","monster47346","monster47347","monster47348","monster47349","monster47350","monster47351"})
reg(48, {"monster48352","monster48353","monster48354","monster48355","monster48356","monster48357","monster48358"})
reg(49, {"monster49359"})
reg(50, {"monster50360","monster50361","monster50362","monster50363","monster50364","monster50365","monster50366"})
reg(51, {"monster51367","monster51368","monster51369","monster51370","monster51371","monster51372","monster51373","monster51374","monster51375","monster51376"})
reg(52, {"monster52377","monster52378","monster52379","monster52380","monster52381","monster52382"})
reg(53, {"monster53383","monster53384","monster53385","monster53386","monster53387","monster53388","monster53389","monster53390"})
reg(54, {"monster54391","monster54392","monster54393","monster54394","monster54395","monster54396","monster54397"})
reg(55, {"monster55398","monster55399","monster55400","monster55401","monster55402","monster55403","monster55404","monster55405"})
reg(56, {"monster56406"})
reg(57, {"monster57407","monster57408","monster57409","monster57410","monster57411","monster57412","monster57413"})
reg(58, {"monster58414","monster58415","monster58416","monster58417","monster58418","monster58419","monster58420"})
reg(59, {"monster59421","monster59422","monster59423","monster59424","monster59425","monster59426"})
reg(60, {"monster60427","monster60428","monster60429","monster60430","monster60431","monster60432"})
reg(61, {"monster61433","monster61434","monster61435","monster61436","monster61437","monster61438","monster61439"})
reg(62, {"monster62440","monster62441","monster62442","monster62443","monster62444","monster62445"})
reg(63, {"monster63446"})
reg(64, {"monster64447","monster64448","monster64449","monster64450","monster64451","monster64452"})
reg(65, {"monster65453","monster65454","monster65455","monster65456","monster65457","monster65458","monster65459","monster65460"})
reg(66, {"monster66461","monster66462","monster66463","monster66464","monster66465","monster66466","monster66467","monster66468"})
reg(67, {"monster67469","monster67470","monster67471","monster67472","monster67473","monster67474","monster67475"})
reg(68, {"monster68476","monster68477","monster68478","monster68479","monster68480","monster68481","monster68482","monster68483","monster68484"})
reg(69, {"monster69485","monster69486","monster69487","monster69488","monster69489","monster69490","monster69491","monster69492","monster69493"})
reg(70, {"monster70494"})

local function isMonsterForLevel(n, l) return MONSTER_TO_LEVEL[n:lower()] == l end

local function buildMonsterList(level)
	local folder = workspace:FindFirstChild("Monster")
	if not folder then return {} end
	local list = {}
	for _, c in ipairs(folder:GetChildren()) do
		if isMonsterForLevel(c.Name, level) then table.insert(list, c) end
	end
	table.sort(list, function(a, b) return a.Name < b.Name end)
	return list
end

local function countMonstersForLevel(level)
	local folder = workspace:FindFirstChild("Monster")
	if not folder then return 0 end
	local n = 0
	for _, c in ipairs(folder:GetChildren()) do
		if isMonsterForLevel(c.Name, level) then n += 1 end
	end
	return n
end

local function getAllLevels()
	local t = {}
	for lv in pairs(LEVEL_MONSTERS) do table.insert(t, lv) end
	table.sort(t)
	return t
end

-- ========================
-- REMOTES
-- ========================
local function findRemote(name)
	for _, c in ipairs(ReplicatedStorage:GetChildren()) do if c.Name == name then return c end end
	for _, d in ipairs(ReplicatedStorage:GetDescendants()) do if d.Name == name then return d end end
	local p = string.split(name, "/")
	if #p == 2 then
		local f = ReplicatedStorage:FindFirstChild(p[1])
		if f then local r = f:FindFirstChild(p[2]) if r then return r end end
	end
	return nil
end

local PetEggBuyRemote = findRemote("PetEgg/PetEggBuy")

local function firePetEggBuy()
	if PetEggBuyRemote then PetEggBuyRemote:FireServer(30)
	else
		pcall(function() ReplicatedStorage["PetEgg/PetEggBuy"]:FireServer(30) end)
	end
end

-- ========================
-- AUTO ATTACK REMOTE
-- Setting/ChangeSetting with "AutoAttack" true/false
-- The remote name literally has a slash in it
-- ========================
local function fireAutoAttack(enabled)
	-- Try all possible ways to find and fire this remote
	local fired = false

	-- Method 1: bracket notation (name has slash)
	pcall(function()
		ReplicatedStorage["Setting/ChangeSetting"]:FireServer("AutoAttack", enabled)
		fired = true
	end)

	if not fired then
		-- Method 2: folder path
		pcall(function()
			ReplicatedStorage.Setting.ChangeSetting:FireServer("AutoAttack", enabled)
			fired = true
		end)
	end

	if not fired then
		-- Method 3: search all descendants
		pcall(function()
			for _, desc in ipairs(ReplicatedStorage:GetDescendants()) do
				if desc.Name == "ChangeSetting" and (desc:IsA("RemoteEvent") or desc:IsA("RemoteFunction")) then
					desc:FireServer("AutoAttack", enabled)
					fired = true
					break
				end
			end
		end)
	end

	if not fired then
		-- Method 4: search by exact full name
		pcall(function()
			for _, child in ipairs(ReplicatedStorage:GetChildren()) do
				if child.Name == "Setting/ChangeSetting" then
					child:FireServer("AutoAttack", enabled)
					fired = true
					break
				end
			end
		end)
	end

	return fired
end

-- ========================
-- TELEPORT BEHIND MONSTER + FIRE TOUCH
-- Teleport to same Y as monster, NOT above
-- ========================
local function teleportAndAttack(monsterModel)
	if not monsterModel or not monsterModel.Parent then return false end
	if not Char or not Char.Parent then return false end

	local myRoot = Char:FindFirstChild("HumanoidRootPart")
	if not myRoot then return false end

	local monsterRoot = monsterModel:FindFirstChild("HumanoidRootPart")
	if not monsterRoot then return false end
	local attackPart = monsterRoot:FindFirstChild("AttackPart")
	if not attackPart then return false end
	local touchInterest = attackPart:FindFirstChild("TouchInterest")
	if not touchInterest then return false end

	-- Get monster position and facing
	local mPos = monsterRoot.Position
	local mLook = monsterRoot.CFrame.LookVector

	-- Behind monster: same Y, 4 studs behind where monster faces
	local behindPos = Vector3.new(
		mPos.X - mLook.X * 4,
		mPos.Y,
		mPos.Z - mLook.Z * 4
	)

	-- Face toward monster
	myRoot.CFrame = CFrame.new(behindPos, Vector3.new(mPos.X, behindPos.Y, mPos.Z))
	myRoot.AssemblyLinearVelocity = Vector3.zero
	myRoot.AssemblyAngularVelocity = Vector3.zero

	-- Fire touch
	if firetouchinterest then
		pcall(function()
			firetouchinterest(myRoot, attackPart, 0)
			task.wait()
			firetouchinterest(myRoot, attackPart, 1)
		end)
		return true
	end

	return false
end

-- ========================
-- SERVER HOP
-- ========================
local function serverHopLowest()
	local placeId = game.PlaceId
	local currentJobId = game.JobId
	local lowestPlayers = math.huge
	local lowestServerId = nil

	local success, result = pcall(function()
		local url = "https://games.roblox.com/v1/games/" .. placeId .. "/servers/Public?sortOrder=Asc&limit=100"
		return HttpService:JSONDecode(game:HttpGet(url))
	end)

	if success and result and result.data then
		for _, server in ipairs(result.data) do
			if server.playing and server.id ~= currentJobId then
				if server.playing < lowestPlayers then
					lowestPlayers = server.playing
					lowestServerId = server.id
				end
			end
		end
	end

	if lowestServerId then
		TeleportService:TeleportToPlaceInstance(placeId, lowestServerId, Player)
	else
		TeleportService:Teleport(placeId, Player)
	end
end

-- ========================
-- COLORS
-- ========================
local C = {
	bg = Color3.fromRGB(12, 12, 20),
	bar = Color3.fromRGB(18, 18, 30),
	barAccent = Color3.fromRGB(80, 50, 200),
	acc = Color3.fromRGB(80, 50, 200),
	on = Color3.fromRGB(30, 170, 70),
	off = Color3.fromRGB(170, 30, 30),
	txt = Color3.fromRGB(220, 220, 235),
	dim = Color3.fromRGB(100, 100, 125),
	sec = Color3.fromRGB(18, 18, 28),
	brd = Color3.fromRGB(35, 35, 52),
	drop = Color3.fromRGB(14, 14, 24),
	hover = Color3.fromRGB(30, 30, 45),
	tabActive = Color3.fromRGB(80, 50, 200),
	tabInactive = Color3.fromRGB(24, 24, 38),
	tabTxtActive = Color3.fromRGB(255, 255, 255),
	tabTxtInactive = Color3.fromRGB(90, 90, 115),
	warn = Color3.fromRGB(220, 160, 40),
	sliderTrack = Color3.fromRGB(30, 30, 45),
	sliderFill = Color3.fromRGB(60, 40, 160),
	sliderKnob = Color3.fromRGB(130, 100, 255),
}

-- ========================
-- GUI SETUP
-- ========================
local Gui = Instance.new("ScreenGui")
Gui.Name = "BusHub"
Gui.ResetOnSpawn = false
Gui.ZIndexBehavior = Enum.ZIndexBehavior.Sibling
Gui.Parent = Player:WaitForChild("PlayerGui")

local Main = Instance.new("Frame")
Main.Size = UDim2.new(0, 340, 0, 500)
Main.Position = UDim2.new(0.5, -170, 0.5, -250)
Main.BackgroundColor3 = C.bg
Main.BorderSizePixel = 0
Main.Active = true
Main.Parent = Gui
Instance.new("UICorner", Main).CornerRadius = UDim.new(0, 10)
Instance.new("UIStroke", Main).Color = C.brd

local shadow = Instance.new("ImageLabel")
shadow.Size = UDim2.new(1, 30, 1, 30)
shadow.Position = UDim2.new(0, -15, 0, -15)
shadow.BackgroundTransparency = 1
shadow.Image = "rbxassetid://6015897843"
shadow.ImageColor3 = Color3.new(0, 0, 0)
shadow.ImageTransparency = 0.4
shadow.ScaleType = Enum.ScaleType.Slice
shadow.SliceCenter = Rect.new(49, 49, 450, 450)
shadow.ZIndex = 0
shadow.Parent = Main

-- TITLE BAR
local Bar = Instance.new("Frame")
Bar.Size = UDim2.new(1, 0, 0, 40)
Bar.BackgroundColor3 = C.bar
Bar.BorderSizePixel = 0
Bar.Parent = Main
Instance.new("UICorner", Bar).CornerRadius = UDim.new(0, 10)
local barFix = Instance.new("Frame")
barFix.Size = UDim2.new(1, 0, 0, 12)
barFix.Position = UDim2.new(0, 0, 1, -12)
barFix.BackgroundColor3 = C.bar
barFix.BorderSizePixel = 0
barFix.Parent = Bar

local accentLine = Instance.new("Frame")
accentLine.Size = UDim2.new(1, -20, 0, 2)
accentLine.Position = UDim2.new(0, 10, 1, -1)
accentLine.BackgroundColor3 = C.barAccent
accentLine.BorderSizePixel = 0
accentLine.Parent = Bar

Instance.new("TextLabel", Bar).Size = UDim2.new(0, 130, 1, 0)
Bar:FindFirstChildOfClass("TextLabel").Position = UDim2.new(0, 14, 0, 0)
Bar:FindFirstChildOfClass("TextLabel").BackgroundTransparency = 1
Bar:FindFirstChildOfClass("TextLabel").Text = "🚌 BUS HUB"
Bar:FindFirstChildOfClass("TextLabel").TextColor3 = C.txt
Bar:FindFirstChildOfClass("TextLabel").TextSize = 16
Bar:FindFirstChildOfClass("TextLabel").Font = Enum.Font.GothamBold
Bar:FindFirstChildOfClass("TextLabel").TextXAlignment = Enum.TextXAlignment.Left

local VerLbl = Instance.new("TextLabel")
VerLbl.Size = UDim2.new(0, 36, 0, 16)
VerLbl.Position = UDim2.new(0, 132, 0.5, -8)
VerLbl.BackgroundColor3 = C.acc
VerLbl.Text = "v5.2"
VerLbl.TextColor3 = Color3.new(1, 1, 1)
VerLbl.TextSize = 9
VerLbl.Font = Enum.Font.GothamBold
VerLbl.Parent = Bar
Instance.new("UICorner", VerLbl).CornerRadius = UDim.new(0, 4)

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
local TabBar = Instance.new("Frame")
TabBar.Size = UDim2.new(1, -20, 0, 30)
TabBar.Position = UDim2.new(0, 10, 0, 44)
TabBar.BackgroundTransparency = 1
TabBar.Parent = Main
local tabLay = Instance.new("UIListLayout", TabBar)
tabLay.FillDirection = Enum.FillDirection.Horizontal
tabLay.Padding = UDim.new(0, 4)
tabLay.SortOrder = Enum.SortOrder.LayoutOrder

local tabDefs = {
	{name = "AutoFarm", display = "⚔ Monster"},
	{name = "AutoEgg", display = "🥚 Egg"},
	{name = "Settings", display = "⚙ Settings"},
}
local tabButtons = {}
local tabPages = {}

for i, def in ipairs(tabDefs) do
	local btn = Instance.new("TextButton")
	btn.Size = UDim2.new(0, 100, 1, 0)
	btn.BackgroundColor3 = (i == 1) and C.tabActive or C.tabInactive
	btn.Text = def.display
	btn.TextColor3 = (i == 1) and C.tabTxtActive or C.tabTxtInactive
	btn.TextSize = 11
	btn.Font = Enum.Font.GothamBold
	btn.BorderSizePixel = 0
	btn.LayoutOrder = i
	btn.Parent = TabBar
	Instance.new("UICorner", btn).CornerRadius = UDim.new(0, 6)
	tabButtons[def.name] = btn
end

local ContentArea = Instance.new("Frame")
ContentArea.Size = UDim2.new(1, -20, 1, -84)
ContentArea.Position = UDim2.new(0, 10, 0, 78)
ContentArea.BackgroundTransparency = 1
ContentArea.ClipsDescendants = true
ContentArea.Parent = Main

-- ========================
-- UI HELPERS
-- ========================
local function mkPage(name)
	local page = Instance.new("ScrollingFrame")
	page.Size = UDim2.new(1, 0, 1, 0)
	page.BackgroundTransparency = 1
	page.ScrollBarThickness = 3
	page.ScrollBarImageColor3 = C.acc
	page.AutomaticCanvasSize = Enum.AutomaticSize.Y
	page.CanvasSize = UDim2.new(0, 0, 0, 0)
	page.BorderSizePixel = 0
	page.Visible = (name == "AutoFarm")
	page.Name = name
	page.Parent = ContentArea
	Instance.new("UIListLayout", page).Padding = UDim.new(0, 8)
	page:FindFirstChildOfClass("UIListLayout").SortOrder = Enum.SortOrder.LayoutOrder
	tabPages[name] = page
	return page
end

local function mkSec(parent, order)
	local f = Instance.new("Frame")
	f.Size = UDim2.new(1, 0, 0, 0)
	f.AutomaticSize = Enum.AutomaticSize.Y
	f.BackgroundColor3 = C.sec
	f.BorderSizePixel = 0
	f.LayoutOrder = order
	f.Parent = parent
	Instance.new("UICorner", f).CornerRadius = UDim.new(0, 8)
	Instance.new("UIStroke", f).Color = C.brd
	local p = Instance.new("UIPadding", f)
	p.PaddingTop = UDim.new(0, 8)
	p.PaddingBottom = UDim.new(0, 8)
	p.PaddingLeft = UDim.new(0, 10)
	p.PaddingRight = UDim.new(0, 10)
	Instance.new("UIListLayout", f).Padding = UDim.new(0, 5)
	f:FindFirstChildOfClass("UIListLayout").SortOrder = Enum.SortOrder.LayoutOrder
	return f
end

local function mkHeader(par, txt, ord)
	local l = Instance.new("TextLabel")
	l.Size = UDim2.new(1, 0, 0, 16)
	l.BackgroundTransparency = 1
	l.Text = txt
	l.TextColor3 = C.acc
	l.TextSize = 11
	l.Font = Enum.Font.GothamBold
	l.TextXAlignment = Enum.TextXAlignment.Left
	l.LayoutOrder = ord
	l.Parent = par
end

local function mkLbl(par, txt, ord)
	local l = Instance.new("TextLabel")
	l.Size = UDim2.new(1, 0, 0, 16)
	l.AutomaticSize = Enum.AutomaticSize.Y
	l.BackgroundTransparency = 1
	l.Text = txt
	l.TextColor3 = C.dim
	l.TextSize = 12
	l.Font = Enum.Font.Gotham
	l.TextXAlignment = Enum.TextXAlignment.Left
	l.TextWrapped = true
	l.LayoutOrder = ord
	l.Parent = par
	return l
end

local function mkToggle(par, name, ord, labelColor, cb)
	local row = Instance.new("Frame")
	row.Size = UDim2.new(1, 0, 0, 30)
	row.BackgroundTransparency = 1
	row.LayoutOrder = ord
	row.Parent = par
	local lbl = Instance.new("TextLabel")
	lbl.Size = UDim2.new(1, -58, 1, 0)
	lbl.BackgroundTransparency = 1
	lbl.Text = name
	lbl.TextColor3 = labelColor or C.txt
	lbl.TextSize = 13
	lbl.Font = Enum.Font.GothamMedium
	lbl.TextXAlignment = Enum.TextXAlignment.Left
	lbl.Parent = row
	local btn = Instance.new("TextButton")
	btn.Size = UDim2.new(0, 52, 0, 24)
	btn.Position = UDim2.new(1, -52, 0.5, -12)
	btn.BackgroundColor3 = C.off
	btn.Text = "OFF"
	btn.TextColor3 = Color3.new(1, 1, 1)
	btn.TextSize = 11
	btn.Font = Enum.Font.GothamBold
	btn.BorderSizePixel = 0
	btn.Parent = row
	Instance.new("UICorner", btn).CornerRadius = UDim.new(0, 6)
	local on = false
	btn.MouseButton1Click:Connect(function()
		on = not on
		btn.BackgroundColor3 = on and C.on or C.off
		btn.Text = on and "ON" or "OFF"
		cb(on)
	end)
end

local function mkButton(par, name, ord, color, cb)
	local btn = Instance.new("TextButton")
	btn.Size = UDim2.new(1, 0, 0, 30)
	btn.BackgroundColor3 = color or C.acc
	btn.Text = name
	btn.TextColor3 = Color3.new(1, 1, 1)
	btn.TextSize = 12
	btn.Font = Enum.Font.GothamBold
	btn.BorderSizePixel = 0
	btn.LayoutOrder = ord
	btn.Parent = par
	Instance.new("UICorner", btn).CornerRadius = UDim.new(0, 6)
	btn.MouseButton1Click:Connect(function() if cb then cb() end end)
end

-- ========================
-- FIXED SLIDER - one dragging state per slider, no conflicts
-- ========================
local function mkSlider(par, name, ord, minVal, maxVal, defaultVal, isInt, suffix, cb)
	local container = Instance.new("Frame")
	container.Size = UDim2.new(1, 0, 0, 46)
	container.BackgroundTransparency = 1
	container.LayoutOrder = ord
	container.Parent = par

	local nameLbl = Instance.new("TextLabel")
	nameLbl.Size = UDim2.new(0.65, 0, 0, 16)
	nameLbl.BackgroundTransparency = 1
	nameLbl.Text = name
	nameLbl.TextColor3 = C.txt
	nameLbl.TextSize = 12
	nameLbl.Font = Enum.Font.GothamMedium
	nameLbl.TextXAlignment = Enum.TextXAlignment.Left
	nameLbl.Parent = container

	local function fmtVal(v)
		if isInt then return tostring(math.floor(v + 0.5)) .. suffix
		else return string.format("%.1f", v) .. suffix end
	end

	local valLbl = Instance.new("TextLabel")
	valLbl.Size = UDim2.new(0.35, 0, 0, 16)
	valLbl.Position = UDim2.new(0.65, 0, 0, 0)
	valLbl.BackgroundTransparency = 1
	valLbl.Text = fmtVal(defaultVal)
	valLbl.TextColor3 = C.sliderKnob
	valLbl.TextSize = 12
	valLbl.Font = Enum.Font.GothamBold
	valLbl.TextXAlignment = Enum.TextXAlignment.Right
	valLbl.Parent = container

	local track = Instance.new("TextButton") -- TextButton so it captures input
	track.Size = UDim2.new(1, 0, 0, 14)
	track.Position = UDim2.new(0, 0, 0, 22)
	track.BackgroundColor3 = C.sliderTrack
	track.BorderSizePixel = 0
	track.Text = ""
	track.AutoButtonColor = false
	track.Parent = container
	Instance.new("UICorner", track).CornerRadius = UDim.new(1, 0)

	local startPct = math.clamp((defaultVal - minVal) / (maxVal - minVal), 0, 1)

	local fill = Instance.new("Frame")
	fill.Size = UDim2.new(startPct, 0, 1, 0)
	fill.BackgroundColor3 = C.sliderFill
	fill.BorderSizePixel = 0
	fill.Parent = track
	Instance.new("UICorner", fill).CornerRadius = UDim.new(1, 0)

	local knob = Instance.new("Frame")
	knob.Size = UDim2.new(0, 16, 0, 16)
	knob.Position = UDim2.new(startPct, -8, 0.5, -8)
	knob.BackgroundColor3 = C.sliderKnob
	knob.BorderSizePixel = 0
	knob.ZIndex = 5
	knob.Parent = track
	Instance.new("UICorner", knob).CornerRadius = UDim.new(1, 0)

	local thisSliderDragging = false

	local function doUpdate(inputX)
		local tPos = track.AbsolutePosition.X
		local tSize = track.AbsoluteSize.X
		if tSize == 0 then return end
		local rel = math.clamp((inputX - tPos) / tSize, 0, 1)

		fill.Size = UDim2.new(rel, 0, 1, 0)
		knob.Position = UDim2.new(rel, -8, 0.5, -8)

		local val = minVal + (maxVal - minVal) * rel
		if isInt then val = math.floor(val + 0.5) end
		if not isInt then val = math.floor(val * 10) / 10 end
		val = math.clamp(val, minVal, maxVal)

		valLbl.Text = fmtVal(val)
		if cb then cb(val) end
	end

	track.MouseButton1Down:Connect(function(x, y)
		thisSliderDragging = true
		doUpdate(x)
	end)

	UserInputService.InputChanged:Connect(function(input)
		if thisSliderDragging then
			if input.UserInputType == Enum.UserInputType.MouseMovement then
				doUpdate(input.Position.X)
			end
		end
	end)

	UserInputService.InputEnded:Connect(function(input)
		if input.UserInputType == Enum.UserInputType.MouseButton1 then
			thisSliderDragging = false
		end
	end)
end

-- TAB SWITCHING
local function switchTab(tabName)
	for name, page in pairs(tabPages) do page.Visible = (name == tabName) end
	for name, btn in pairs(tabButtons) do
		btn.BackgroundColor3 = (name == tabName) and C.tabActive or C.tabInactive
		btn.TextColor3 = (name == tabName) and C.tabTxtActive or C.tabTxtInactive
	end
end
for name, btn in pairs(tabButtons) do
	btn.MouseButton1Click:Connect(function() switchTab(name) end)
end

-- ========================
-- PAGE 1: AUTO MONSTER
-- ========================
local pageFarm = mkPage("AutoFarm")

local farmToggles = mkSec(pageFarm, 1)
mkHeader(farmToggles, "AUTO MONSTER", 0)
mkToggle(farmToggles, "⚔ Auto Monster", 1, C.txt, function(v)
	autoMonsterOn = v
	-- Turn on/off auto attack on server
	fireAutoAttack(v)
end)
mkLbl(farmToggles, "Teleports behind monsters, fires touch attack, auto attack on.", 2)

local speedSec = mkSec(pageFarm, 2)
mkHeader(speedSec, "ADJUSTMENTS", 0)
mkSlider(speedSec, "⏱ Teleport Speed", 1, 0.1, 3.0, 0.5, false, "s", function(v) farmSpeed = v end)
mkSlider(speedSec, "🗡 Touch Hits", 2, 1, 20, 5, true, "x", function(v) touchHits = v end)

local farmSelect = mkSec(pageFarm, 3)
mkHeader(farmSelect, "SELECT MONSTER LEVEL", 0)

local dropBtn = Instance.new("TextButton")
dropBtn.Size = UDim2.new(1, 0, 0, 30)
dropBtn.BackgroundColor3 = C.drop
dropBtn.Text = "▼  Select Level..."
dropBtn.TextColor3 = C.txt
dropBtn.TextSize = 12
dropBtn.Font = Enum.Font.GothamMedium
dropBtn.TextXAlignment = Enum.TextXAlignment.Left
dropBtn.BorderSizePixel = 0
dropBtn.LayoutOrder = 1
dropBtn.Parent = farmSelect
Instance.new("UICorner", dropBtn).CornerRadius = UDim.new(0, 6)
Instance.new("UIStroke", dropBtn).Color = C.brd
Instance.new("UIPadding", dropBtn).PaddingLeft = UDim.new(0, 12)

local dropList = Instance.new("Frame")
dropList.Size = UDim2.new(1, 0, 0, 0)
dropList.AutomaticSize = Enum.AutomaticSize.Y
dropList.BackgroundColor3 = C.drop
dropList.BorderSizePixel = 0
dropList.LayoutOrder = 2
dropList.Visible = false
dropList.ClipsDescendants = true
dropList.Parent = farmSelect
Instance.new("UICorner", dropList).CornerRadius = UDim.new(0, 6)
Instance.new("UIStroke", dropList).Color = C.brd

local dropScroll = Instance.new("ScrollingFrame")
dropScroll.Size = UDim2.new(1, 0, 0, 160)
dropScroll.BackgroundTransparency = 1
dropScroll.ScrollBarThickness = 3
dropScroll.ScrollBarImageColor3 = C.acc
dropScroll.AutomaticCanvasSize = Enum.AutomaticSize.Y
dropScroll.CanvasSize = UDim2.new(0, 0, 0, 0)
dropScroll.BorderSizePixel = 0
dropScroll.Parent = dropList
Instance.new("UIListLayout", dropScroll).Padding = UDim.new(0, 1)
dropScroll:FindFirstChildOfClass("UIListLayout").SortOrder = Enum.SortOrder.LayoutOrder

local dropOpen = false
dropBtn.MouseButton1Click:Connect(function()
	dropOpen = not dropOpen
	dropList.Visible = dropOpen
end)

local function populateDropdown()
	for _, child in ipairs(dropScroll:GetChildren()) do
		if child:IsA("TextButton") then child:Destroy() end
	end
	local levels = getAllLevels()
	for i, lv in ipairs(levels) do
		local count = countMonstersForLevel(lv)
		local total = LEVEL_MONSTERS[lv] and #LEVEL_MONSTERS[lv] or 0
		local item = Instance.new("TextButton")
		item.Size = UDim2.new(1, 0, 0, 26)
		item.BackgroundColor3 = (selectedLevel == lv) and C.acc or C.drop
		item.Text = "    Lv." .. lv .. "    •    " .. count .. "/" .. total
		item.TextColor3 = (selectedLevel == lv) and C.txt or C.dim
		item.TextSize = 12
		item.Font = Enum.Font.Gotham
		item.TextXAlignment = Enum.TextXAlignment.Left
		item.BorderSizePixel = 0
		item.LayoutOrder = i
		item.Parent = dropScroll
		item.MouseEnter:Connect(function() item.BackgroundColor3 = C.hover; item.TextColor3 = C.txt end)
		item.MouseLeave:Connect(function()
			item.BackgroundColor3 = (selectedLevel == lv) and C.acc or C.drop
			item.TextColor3 = (selectedLevel == lv) and C.txt or C.dim
		end)
		item.MouseButton1Click:Connect(function()
			selectedLevel = lv
			dropBtn.Text = "▼  Level " .. lv .. "  •  " .. count .. " monsters"
			dropOpen = false; dropList.Visible = false
			for _, b in ipairs(dropScroll:GetChildren()) do
				if b:IsA("TextButton") then b.BackgroundColor3 = C.drop; b.TextColor3 = C.dim end
			end
			item.BackgroundColor3 = C.acc; item.TextColor3 = C.txt
		end)
	end
end
mkButton(farmSelect, "🔄 Refresh List", 3, C.acc, populateDropdown)
task.delay(1, populateDropdown)

local farmStatus = mkSec(pageFarm, 4)
mkHeader(farmStatus, "STATUS", 0)
local lblLevel = mkLbl(farmStatus, "Level: ---", 1)
local lblTarget = mkLbl(farmStatus, "Target: None", 2)
local lblFarm = mkLbl(farmStatus, "Auto Monster: Off", 3)
local lblCount = mkLbl(farmStatus, "Monsters: 0", 4)
local lblIndex = mkLbl(farmStatus, "Queue: 0/0", 5)
local lblHits = mkLbl(farmStatus, "Hits: 0", 6)
local lblSpeed = mkLbl(farmStatus, "Speed: 0.5s | Touch: 5x", 7)

-- ========================
-- PAGE 2: AUTO EGG
-- ========================
local pageEgg = mkPage("AutoEgg")
local eggToggles = mkSec(pageEgg, 1)
mkHeader(eggToggles, "PET EGG", 0)
mkToggle(eggToggles, "🥚 Auto Best Pet", 1, C.warn, function(v) autoPetOn = v end)
mkLbl(eggToggles, "Buys best pet egg every 2 seconds", 2)
local eggStatus = mkSec(pageEgg, 2)
mkHeader(eggStatus, "STATUS", 0)
local lblPet = mkLbl(eggStatus, "🐾 Pet: Off", 1)
local lblPetCount = mkLbl(eggStatus, "Eggs Bought: 0", 2)

-- ========================
-- PAGE 3: SETTINGS
-- ========================
local pageSettings = mkPage("Settings")
local serverSec = mkSec(pageSettings, 1)
mkHeader(serverSec, "SERVER", 0)
mkButton(serverSec, "🔄 Rejoin This Server", 1, C.acc, function()
	TeleportService:TeleportToPlaceInstance(game.PlaceId, game.JobId, Player)
end)
mkButton(serverSec, "🌐 Join Lowest Population Server", 2, Color3.fromRGB(40, 140, 200), function()
	serverHopLowest()
end)

local rejoinSec = mkSec(pageSettings, 2)
mkHeader(rejoinSec, "AUTO REJOIN", 0)
mkToggle(rejoinSec, "🔁 Auto Rejoin on Kick", 1, C.txt, function(v) autoRejoinOn = v end)
mkLbl(rejoinSec, "Rejoins automatically if disconnected", 2)
local lblRejoin = mkLbl(rejoinSec, "Status: Off", 3)

local infoSec = mkSec(pageSettings, 3)
mkHeader(infoSec, "INFO", 0)
mkLbl(infoSec, "Minimize: RightCtrl", 1)
mkLbl(infoSec, "🚌 BUS HUB v5.2", 2)

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

local full = Main.Size
local function toggleMin()
	minimized = not minimized
	if minimized then
		ContentArea.Visible = false; TabBar.Visible = false
		TweenService:Create(Main, TweenInfo.new(0.2), {Size = UDim2.new(0, 340, 0, 40)}):Play()
		MinBtn.Text = "+"
	else
		TweenService:Create(Main, TweenInfo.new(0.2), {Size = full}):Play()
		task.delay(0.2, function() ContentArea.Visible = true; TabBar.Visible = true end)
		MinBtn.Text = "—"
	end
end
MinBtn.MouseButton1Click:Connect(toggleMin)
UserInputService.InputBegan:Connect(function(i, g)
	if not g and i.KeyCode == Enum.KeyCode.RightControl then toggleMin() end
end)

-- ========================
-- AUTO PET LOOP
-- ========================
local eggsCount = 0
task.spawn(function()
	while true do
		if autoPetOn then
			firePetEggBuy()
			eggsCount += 1
			lblPet.Text = "🐾 Pet: Buying..."
			lblPetCount.Text = "Eggs Bought: " .. eggsCount
		else lblPet.Text = "🐾 Pet: Off" end
		task.wait(2)
	end
end)

-- ========================
-- AUTO REJOIN
-- ========================
game:GetService("GuiService").ErrorMessageChanged:Connect(function()
	if autoRejoinOn then task.wait(3); TeleportService:Teleport(game.PlaceId, Player) end
end)
pcall(function()
	local ef = game:GetService("CoreGui"):WaitForChild("RobloxPromptGui", 5)
	if ef then ef.DescendantAdded:Connect(function()
		if autoRejoinOn then task.wait(3); TeleportService:Teleport(game.PlaceId, Player) end
	end) end
end)
task.spawn(function()
	while true do
		lblRejoin.Text = autoRejoinOn and "Status: ✅ Watching" or "Status: Off"
		task.wait(1)
	end
end)

-- ========================
-- AUTO MONSTER LOOP
-- ========================
local function getLevel()
	local ls = Player:FindFirstChild("leaderstats")
	if ls then local lv = ls:FindFirstChild("Level") if lv then return lv.Value end end
	return 1
end

local totalHits = 0

task.spawn(function()
	local monsterList = {}
	local currentIndex = 0
	local lastLevel = -1

	while true do
		if not Char or not Char.Parent then Char = waitChar() end

		local playerLevel = getLevel()
		lblLevel.Text = "Level: " .. tostring(playerLevel)
		lblSpeed.Text = "Speed: " .. string.format("%.1f", farmSpeed) .. "s | Touch: " .. touchHits .. "x"

		if autoMonsterOn then
			local farmLevel = selectedLevel or playerLevel

			if farmLevel ~= lastLevel or #monsterList == 0 then
				monsterList = buildMonsterList(farmLevel)
				currentIndex = 0
				lastLevel = farmLevel
			end

			lblCount.Text = "Monsters: " .. #monsterList .. " (Lv." .. farmLevel .. ")"

			if #monsterList == 0 then
				lblFarm.Text = "Auto Monster: No monsters"
				lblTarget.Text = "Target: None"
				lblIndex.Text = "Queue: 0/0"
				task.wait(1)
				continue
			end

			currentIndex += 1
			if currentIndex > #monsterList then
				monsterList = buildMonsterList(farmLevel)
				currentIndex = 1
				if #monsterList == 0 then task.wait(1) continue end
			end

			local target = monsterList[currentIndex]
			if not target or not target.Parent then
				monsterList = buildMonsterList(farmLevel)
				currentIndex = 1
				if #monsterList == 0 then task.wait(1) continue end
				target = monsterList[currentIndex]
			end

			lblTarget.Text = "Target: " .. target.Name
			lblIndex.Text = "Queue: " .. currentIndex .. "/" .. #monsterList
			lblFarm.Text = "Auto Monster: Hitting"

			-- Fire touch (touchHits) times
			for i = 1, touchHits do
				if not autoMonsterOn then break end
				if not target or not target.Parent then break end

				local success = teleportAndAttack(target)
				if success then
					totalHits += 1
					lblHits.Text = "Hits: " .. totalHits
				end

				task.wait(0.05)
			end

			-- Wait user speed before next monster
			task.wait(farmSpeed)
		else
			monsterList = {}
			currentIndex = 0
			lastLevel = -1
			lblFarm.Text = "Auto Monster: Off"
			lblTarget.Text = "Target: None"
			lblCount.Text = "Monsters: 0"
			lblIndex.Text = "Queue: 0/0"
			task.wait(0.5)
		end
	end
end)
