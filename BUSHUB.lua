-- LocalScript: Place inside StarterPlayerScripts or StarterGui
-- BUS HUB v7.0

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
local farmSpeed = 1.0
local autoAttackFired = false

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

reg(1,{"monster11","monster12","monster13","monster14","monster15","monster16","monster17","monster18","monster19","monster110"})
reg(2,{"monster212","monster213","monster214","monster215","monster216","monster217"})
reg(3,{"monster320","monster321","monster322","monster323","monster324","monster325","monster326","monster327","monster328"})
reg(4,{"monster430","monster431","monster432","monster433","monster435","monster436"})
reg(5,{"monster537","monster538","monster540","monster541","monster542","monster543"})
reg(6,{"monster644","monster645","monster646"})
reg(7,{"monster748"})
reg(8,{"monster857","monster858","monster859","monster860","monster861","monster862","monster863","monster864","monster865"})
reg(10,{"monster1074","monster1075","monster1076","monster1077","monster1078","monster1079","monster1080","monster1081","monster1082"})
reg(11,{"monster1183","monster1184","monster1185","monster1186","monster1187","monster1188","monster1189"})
reg(12,{"monster1290","monster1291","monster1292","monster1293","monster1294","monster1295"})
reg(13,{"monster13100","monster13101","monster1396","monster1397","monster1398","monster1399"})
reg(14,{"monster14102"})
reg(15,{"monster15146","monster15147","monster15148","monster15149","monster15150","monster15151","monster15152"})
reg(16,{"monster16103","monster16104","monster16105","monster16106","monster16107","monster16108","monster16109","monster16110","monster16111"})
reg(17,{"monster17112","monster17113","monster17114","monster17115","monster17116","monster17117","monster17118","monster17119","monster17120"})
reg(18,{"monster18121","monster18122","monster18123","monster18124","monster18125","monster18126","monster18127"})
reg(19,{"monster19128","monster19129","monster19130","monster19131","monster19132","monster19133","monster19134","monster19135","monster19136"})
reg(20,{"monster20137","monster20138","monster20139","monster20140","monster20141","monster20142","monster20143","monster20144"})
reg(21,{"monster21145"})
reg(22,{"monster22153","monster22154","monster22155","monster22156","monster22157","monster22158","monster22159","monster22160"})
reg(23,{"monster23161","monster23162","monster23163","monster23164","monster23165","monster23166","monster23167","monster23168"})
reg(24,{"monster24169","monster24170","monster24171","monster24172","monster24173","monster24174","monster24175"})
reg(25,{"monster25176","monster25177","monster25178","monster25179","monster25180","monster25181","monster25182","monster25183"})
reg(26,{"monster26184","monster26185","monster26186","monster26187","monster26188","monster26189","monster26190","monster26191"})
reg(27,{"monster27192","monster27193","monster27194","monster27195","monster27196","monster27197"})
reg(28,{"monster28198"})
reg(29,{"monster29199","monster29200","monster29201","monster29202","monster29203","monster29204","monster29205","monster29206","monster29207","monster29208","monster29209"})
reg(30,{"monster30210","monster30211","monster30212","monster30213","monster30214","monster30215","monster30216","monster30217","monster30218","monster30219","monster30220"})
reg(31,{"monster31221","monster31222","monster31223","monster31224","monster31225","monster31226","monster31227","monster31228","monster31229","monster31230","monster31231","monster31232","monster31233"})
reg(32,{"monster32234","monster32235","monster32236","monster32237","monster32238","monster32239","monster32240","monster32241","monster32242","monster32243"})
reg(33,{"monster33244","monster33245","monster33246","monster33247","monster33248","monster33249","monster33250","monster33251","monster33252","monster33253"})
reg(34,{"monster34254","monster34255","monster34256","monster34257","monster34258","monster34259","monster34260","monster34261"})
reg(35,{"monster35263"})
reg(36,{"monster36264","monster36265","monster36266","monster36267","monster36268","monster36269","monster36270","monster36271"})
reg(37,{"monster37272","monster37273","monster37274","monster37275","monster37276","monster37277","monster37278","monster37279"})
reg(38,{"monster38280","monster38281","monster38282","monster38283","monster38284","monster38285","monster38286","monster38287"})
reg(39,{"monster39288","monster39289","monster39290","monster39291","monster39292","monster39293","monster39294","monster39295"})
reg(40,{"monster40296","monster40297","monster40298","monster40299","monster40300","monster40301","monster40302","monster40303","monster40304"})
reg(41,{"monster41305","monster41306","monster41307","monster41308","monster41309","monster41310","monster41311","monster41312"})
reg(42,{"monster42313"})
reg(43,{"monster43314","monster43315","monster43316","monster43317","monster43318","monster43319","monster43320","monster43321"})
reg(44,{"monster44322","monster44323","monster44324","monster44325","monster44326","monster44327","monster44328","monster44329"})
reg(45,{"monster45330","monster45331","monster45332","monster45333","monster45334","monster45335","monster45336"})
reg(46,{"monster46337","monster46338","monster46339","monster46340","monster46341","monster46342","monster46343","monster46344"})
reg(47,{"monster47345","monster47346","monster47347","monster47348","monster47349","monster47350","monster47351"})
reg(48,{"monster48352","monster48353","monster48354","monster48355","monster48356","monster48357","monster48358"})
reg(49,{"monster49359"})
reg(50,{"monster50360","monster50361","monster50362","monster50363","monster50364","monster50365","monster50366"})
reg(51,{"monster51367","monster51368","monster51369","monster51370","monster51371","monster51372","monster51373","monster51374","monster51375","monster51376"})
reg(52,{"monster52377","monster52378","monster52379","monster52380","monster52381","monster52382"})
reg(53,{"monster53383","monster53384","monster53385","monster53386","monster53387","monster53388","monster53389","monster53390"})
reg(54,{"monster54391","monster54392","monster54393","monster54394","monster54395","monster54396","monster54397"})
reg(55,{"monster55398","monster55399","monster55400","monster55401","monster55402","monster55403","monster55404","monster55405"})
reg(56,{"monster56406"})
reg(57,{"monster57407","monster57408","monster57409","monster57410","monster57411","monster57412","monster57413"})
reg(58,{"monster58414","monster58415","monster58416","monster58417","monster58418","monster58419","monster58420"})
reg(59,{"monster59421","monster59422","monster59423","monster59424","monster59425","monster59426"})
reg(60,{"monster60427","monster60428","monster60429","monster60430","monster60431","monster60432"})
reg(61,{"monster61433","monster61434","monster61435","monster61436","monster61437","monster61438","monster61439"})
reg(62,{"monster62440","monster62441","monster62442","monster62443","monster62444","monster62445"})
reg(63,{"monster63446"})
reg(64,{"monster64447","monster64448","monster64449","monster64450","monster64451","monster64452"})
reg(65,{"monster65453","monster65454","monster65455","monster65456","monster65457","monster65458","monster65459","monster65460"})
reg(66,{"monster66461","monster66462","monster66463","monster66464","monster66465","monster66466","monster66467","monster66468"})
reg(67,{"monster67469","monster67470","monster67471","monster67472","monster67473","monster67474","monster67475"})
reg(68,{"monster68476","monster68477","monster68478","monster68479","monster68480","monster68481","monster68482","monster68483","monster68484"})
reg(69,{"monster69485","monster69486","monster69487","monster69488","monster69489","monster69490","monster69491","monster69492","monster69493"})
reg(70,{"monster70494"})

local function buildMonsterList(level)
	local folder = workspace:FindFirstChild("Monster")
	if not folder then return {} end
	local list = {}
	for _, c in ipairs(folder:GetChildren()) do
		if MONSTER_TO_LEVEL[c.Name:lower()] == level then table.insert(list, c) end
	end
	table.sort(list, function(a, b) return a.Name < b.Name end)
	return list
end

local function countMonstersForLevel(level)
	local folder = workspace:FindFirstChild("Monster")
	if not folder then return 0 end
	local n = 0
	for _, c in ipairs(folder:GetChildren()) do
		if MONSTER_TO_LEVEL[c.Name:lower()] == level then n += 1 end
	end
	return n
end

local function getAllLevels()
	local t = {}
	for lv in pairs(LEVEL_MONSTERS) do table.insert(t, lv) end
	table.sort(t)
	return t
end

local function getLevel()
	local ls = Player:FindFirstChild("leaderstats")
	if ls then local lv = ls:FindFirstChild("Level") if lv then return lv.Value end end
	return 1
end

-- ========================
-- AUTO ATTACK REMOTE
-- ========================
local function fireAutoAttackOn()
	local args = {[1] = "AutoAttack", [2] = true}
	local remote = ReplicatedStorage:FindFirstChild("Setting/ChangeSetting")
	if remote then remote:FireServer(unpack(args)) return end
	pcall(function() ReplicatedStorage["Setting/ChangeSetting"]:FireServer(unpack(args)) end)
	pcall(function() ReplicatedStorage.Setting.ChangeSetting:FireServer(unpack(args)) end)
end

local function fireAutoAttackOff()
	local args = {[1] = "AutoAttack", [2] = false}
	local remote = ReplicatedStorage:FindFirstChild("Setting/ChangeSetting")
	if remote then remote:FireServer(unpack(args)) return end
	pcall(function() ReplicatedStorage["Setting/ChangeSetting"]:FireServer(unpack(args)) end)
	pcall(function() ReplicatedStorage.Setting.ChangeSetting:FireServer(unpack(args)) end)
end

-- ========================
-- PET EGG
-- ========================
local function firePetEggBuy()
	local args = {[1] = 30}
	local remote = ReplicatedStorage:FindFirstChild("PetEgg/PetEggBuy")
	if remote then remote:FireServer(unpack(args)) return end
	pcall(function() ReplicatedStorage["PetEgg/PetEggBuy"]:FireServer(unpack(args)) end)
end

-- ========================
-- TELEPORT ABOVE MONSTER FACING DOWN
-- Player goes above monster and looks straight down at it
-- ========================
local function teleportToMonster(monsterModel)
	if not monsterModel or not monsterModel.Parent then return false end
	if not Char or not Char.Parent then return false end
	local myRoot = Char:FindFirstChild("HumanoidRootPart")
	if not myRoot then return false end

	local monsterPos = monsterModel:GetPivot().Position

	-- Position: directly above monster, 5 studs up
	local abovePos = Vector3.new(monsterPos.X, monsterPos.Y + 5, monsterPos.Z)

	-- Face straight down: LookVector pointing down (0, -1, 0)
	-- CFrame.new(position, lookAt) where lookAt is below us
	local belowPos = Vector3.new(monsterPos.X, monsterPos.Y - 10, monsterPos.Z)
	myRoot.CFrame = CFrame.new(abovePos, belowPos)

	myRoot.AssemblyLinearVelocity = Vector3.zero
	myRoot.AssemblyAngularVelocity = Vector3.zero

	return true
end

-- ========================
-- SERVER HOP
-- ========================
local function serverHopLowest()
	local pid = game.PlaceId
	local cjid = game.JobId
	local low = math.huge
	local sid = nil
	pcall(function()
		local d = HttpService:JSONDecode(game:HttpGet("https://games.roblox.com/v1/games/"..pid.."/servers/Public?sortOrder=Asc&limit=100"))
		if d and d.data then for _, s in ipairs(d.data) do
			if s.playing and s.id ~= cjid and s.playing < low then low = s.playing; sid = s.id end
		end end
	end)
	if sid then TeleportService:TeleportToPlaceInstance(pid, sid, Player)
	else TeleportService:Teleport(pid, Player) end
end

-- ========================
-- COLORS
-- ========================
local C = {
	bg=Color3.fromRGB(12,12,20), bar=Color3.fromRGB(18,18,30),
	barAccent=Color3.fromRGB(80,50,200), acc=Color3.fromRGB(80,50,200),
	on=Color3.fromRGB(30,170,70), off=Color3.fromRGB(170,30,30),
	txt=Color3.fromRGB(220,220,235), dim=Color3.fromRGB(100,100,125),
	sec=Color3.fromRGB(18,18,28), brd=Color3.fromRGB(35,35,52),
	drop=Color3.fromRGB(14,14,24), hover=Color3.fromRGB(30,30,45),
	tabA=Color3.fromRGB(80,50,200), tabI=Color3.fromRGB(24,24,38),
	tabTA=Color3.fromRGB(255,255,255), tabTI=Color3.fromRGB(90,90,115),
	warn=Color3.fromRGB(220,160,40),
	sT=Color3.fromRGB(30,30,45), sF=Color3.fromRGB(60,40,160), sK=Color3.fromRGB(130,100,255),
}

-- ========================
-- GUI
-- ========================
local Gui = Instance.new("ScreenGui")
Gui.Name="BusHub"; Gui.ResetOnSpawn=false; Gui.ZIndexBehavior=Enum.ZIndexBehavior.Sibling
Gui.Parent=Player:WaitForChild("PlayerGui")

local Main = Instance.new("Frame")
Main.Size=UDim2.new(0,340,0,480); Main.Position=UDim2.new(0.5,-170,0.5,-240)
Main.BackgroundColor3=C.bg; Main.BorderSizePixel=0; Main.Active=true; Main.Parent=Gui
Instance.new("UICorner",Main).CornerRadius=UDim.new(0,10)
Instance.new("UIStroke",Main).Color=C.brd

local Bar = Instance.new("Frame")
Bar.Size=UDim2.new(1,0,0,40); Bar.BackgroundColor3=C.bar; Bar.BorderSizePixel=0; Bar.Parent=Main
Instance.new("UICorner",Bar).CornerRadius=UDim.new(0,10)
local bf=Instance.new("Frame"); bf.Size=UDim2.new(1,0,0,12); bf.Position=UDim2.new(0,0,1,-12); bf.BackgroundColor3=C.bar; bf.BorderSizePixel=0; bf.Parent=Bar
local al=Instance.new("Frame"); al.Size=UDim2.new(1,-20,0,2); al.Position=UDim2.new(0,10,1,-1); al.BackgroundColor3=C.barAccent; al.BorderSizePixel=0; al.Parent=Bar
local lg=Instance.new("TextLabel"); lg.Size=UDim2.new(0,160,1,0); lg.Position=UDim2.new(0,14,0,0); lg.BackgroundTransparency=1; lg.Text="🚌 BUS HUB v7.0"; lg.TextColor3=C.txt; lg.TextSize=15; lg.Font=Enum.Font.GothamBold; lg.TextXAlignment=Enum.TextXAlignment.Left; lg.Parent=Bar
local MinBtn=Instance.new("TextButton"); MinBtn.Size=UDim2.new(0,28,0,28); MinBtn.Position=UDim2.new(1,-38,0,6); MinBtn.BackgroundColor3=C.acc; MinBtn.Text="—"; MinBtn.TextColor3=C.txt; MinBtn.TextSize=16; MinBtn.Font=Enum.Font.GothamBold; MinBtn.BorderSizePixel=0; MinBtn.Parent=Bar; Instance.new("UICorner",MinBtn).CornerRadius=UDim.new(0,6)

local TB=Instance.new("Frame"); TB.Size=UDim2.new(1,-20,0,30); TB.Position=UDim2.new(0,10,0,44); TB.BackgroundTransparency=1; TB.Parent=Main
local tbl=Instance.new("UIListLayout",TB); tbl.FillDirection=Enum.FillDirection.Horizontal; tbl.Padding=UDim.new(0,4); tbl.SortOrder=Enum.SortOrder.LayoutOrder
local tabButtons={}; local tabPages={}
for i,info in ipairs({{"AutoFarm","⚔ Monster"},{"AutoEgg","🥚 Egg"},{"Settings","⚙ Settings"}}) do
	local b=Instance.new("TextButton"); b.Size=UDim2.new(0,100,1,0); b.BackgroundColor3=i==1 and C.tabA or C.tabI; b.Text=info[2]; b.TextColor3=i==1 and C.tabTA or C.tabTI; b.TextSize=11; b.Font=Enum.Font.GothamBold; b.BorderSizePixel=0; b.LayoutOrder=i; b.Parent=TB; Instance.new("UICorner",b).CornerRadius=UDim.new(0,6); tabButtons[info[1]]=b
end

local CA=Instance.new("Frame"); CA.Size=UDim2.new(1,-20,1,-84); CA.Position=UDim2.new(0,10,0,78); CA.BackgroundTransparency=1; CA.ClipsDescendants=true; CA.Parent=Main

-- HELPERS
local function mkP(n) local p=Instance.new("ScrollingFrame"); p.Size=UDim2.new(1,0,1,0); p.BackgroundTransparency=1; p.ScrollBarThickness=3; p.ScrollBarImageColor3=C.acc; p.AutomaticCanvasSize=Enum.AutomaticSize.Y; p.CanvasSize=UDim2.new(0,0,0,0); p.BorderSizePixel=0; p.Visible=(n=="AutoFarm"); p.Name=n; p.Parent=CA; local l=Instance.new("UIListLayout",p); l.Padding=UDim.new(0,8); l.SortOrder=Enum.SortOrder.LayoutOrder; tabPages[n]=p; return p end
local function mkSc(p,o) local f=Instance.new("Frame"); f.Size=UDim2.new(1,0,0,0); f.AutomaticSize=Enum.AutomaticSize.Y; f.BackgroundColor3=C.sec; f.BorderSizePixel=0; f.LayoutOrder=o; f.Parent=p; Instance.new("UICorner",f).CornerRadius=UDim.new(0,8); Instance.new("UIStroke",f).Color=C.brd; local pd=Instance.new("UIPadding",f); pd.PaddingTop=UDim.new(0,8); pd.PaddingBottom=UDim.new(0,8); pd.PaddingLeft=UDim.new(0,10); pd.PaddingRight=UDim.new(0,10); local l=Instance.new("UIListLayout",f); l.Padding=UDim.new(0,5); l.SortOrder=Enum.SortOrder.LayoutOrder; return f end
local function mkH(p,t,o) local l=Instance.new("TextLabel"); l.Size=UDim2.new(1,0,0,16); l.BackgroundTransparency=1; l.Text=t; l.TextColor3=C.acc; l.TextSize=11; l.Font=Enum.Font.GothamBold; l.TextXAlignment=Enum.TextXAlignment.Left; l.LayoutOrder=o; l.Parent=p end
local function mkL(p,t,o) local l=Instance.new("TextLabel"); l.Size=UDim2.new(1,0,0,16); l.AutomaticSize=Enum.AutomaticSize.Y; l.BackgroundTransparency=1; l.Text=t; l.TextColor3=C.dim; l.TextSize=12; l.Font=Enum.Font.Gotham; l.TextXAlignment=Enum.TextXAlignment.Left; l.TextWrapped=true; l.LayoutOrder=o; l.Parent=p; return l end
local function mkT(p,n,o,lc,cb) local r=Instance.new("Frame"); r.Size=UDim2.new(1,0,0,30); r.BackgroundTransparency=1; r.LayoutOrder=o; r.Parent=p; local l=Instance.new("TextLabel"); l.Size=UDim2.new(1,-58,1,0); l.BackgroundTransparency=1; l.Text=n; l.TextColor3=lc or C.txt; l.TextSize=13; l.Font=Enum.Font.GothamMedium; l.TextXAlignment=Enum.TextXAlignment.Left; l.Parent=r; local b=Instance.new("TextButton"); b.Size=UDim2.new(0,52,0,24); b.Position=UDim2.new(1,-52,0.5,-12); b.BackgroundColor3=C.off; b.Text="OFF"; b.TextColor3=Color3.new(1,1,1); b.TextSize=11; b.Font=Enum.Font.GothamBold; b.BorderSizePixel=0; b.Parent=r; Instance.new("UICorner",b).CornerRadius=UDim.new(0,6); local on=false; b.MouseButton1Click:Connect(function() on=not on; b.BackgroundColor3=on and C.on or C.off; b.Text=on and "ON" or "OFF"; cb(on) end) end
local function mkB(p,n,o,c,cb) local b=Instance.new("TextButton"); b.Size=UDim2.new(1,0,0,30); b.BackgroundColor3=c or C.acc; b.Text=n; b.TextColor3=Color3.new(1,1,1); b.TextSize=12; b.Font=Enum.Font.GothamBold; b.BorderSizePixel=0; b.LayoutOrder=o; b.Parent=p; Instance.new("UICorner",b).CornerRadius=UDim.new(0,6); b.MouseButton1Click:Connect(function() if cb then cb() end end) end

local function mkS(p,n,o,mn,mx,df,isI,sf,cb)
	local ct=Instance.new("Frame"); ct.Size=UDim2.new(1,0,0,46); ct.BackgroundTransparency=1; ct.LayoutOrder=o; ct.Parent=p
	local nl=Instance.new("TextLabel"); nl.Size=UDim2.new(0.65,0,0,16); nl.BackgroundTransparency=1; nl.Text=n; nl.TextColor3=C.txt; nl.TextSize=12; nl.Font=Enum.Font.GothamMedium; nl.TextXAlignment=Enum.TextXAlignment.Left; nl.Parent=ct
	local function fmt(v) if isI then return tostring(math.floor(v+0.5))..sf else return string.format("%.1f",v)..sf end end
	local vl=Instance.new("TextLabel"); vl.Size=UDim2.new(0.35,0,0,16); vl.Position=UDim2.new(0.65,0,0,0); vl.BackgroundTransparency=1; vl.Text=fmt(df); vl.TextColor3=C.sK; vl.TextSize=12; vl.Font=Enum.Font.GothamBold; vl.TextXAlignment=Enum.TextXAlignment.Right; vl.Parent=ct
	local tk=Instance.new("TextButton"); tk.Size=UDim2.new(1,0,0,14); tk.Position=UDim2.new(0,0,0,22); tk.BackgroundColor3=C.sT; tk.BorderSizePixel=0; tk.Text=""; tk.AutoButtonColor=false; tk.Parent=ct; Instance.new("UICorner",tk).CornerRadius=UDim.new(1,0)
	local sp=math.clamp((df-mn)/(mx-mn),0,1)
	local fl=Instance.new("Frame"); fl.Size=UDim2.new(sp,0,1,0); fl.BackgroundColor3=C.sF; fl.BorderSizePixel=0; fl.Parent=tk; Instance.new("UICorner",fl).CornerRadius=UDim.new(1,0)
	local kb=Instance.new("Frame"); kb.Size=UDim2.new(0,16,0,16); kb.Position=UDim2.new(sp,-8,0.5,-8); kb.BackgroundColor3=C.sK; kb.BorderSizePixel=0; kb.ZIndex=5; kb.Parent=tk; Instance.new("UICorner",kb).CornerRadius=UDim.new(1,0)
	local dr=false
	local function upd(ix) local tp=tk.AbsolutePosition.X; local ts=tk.AbsoluteSize.X; if ts==0 then return end; local rl=math.clamp((ix-tp)/ts,0,1); fl.Size=UDim2.new(rl,0,1,0); kb.Position=UDim2.new(rl,-8,0.5,-8); local v=mn+(mx-mn)*rl; if isI then v=math.floor(v+0.5) else v=math.floor(v*10)/10 end; v=math.clamp(v,mn,mx); vl.Text=fmt(v); if cb then cb(v) end end
	tk.MouseButton1Down:Connect(function(x) dr=true; upd(x) end)
	UserInputService.InputChanged:Connect(function(i) if dr and i.UserInputType==Enum.UserInputType.MouseMovement then upd(i.Position.X) end end)
	UserInputService.InputEnded:Connect(function(i) if i.UserInputType==Enum.UserInputType.MouseButton1 then dr=false end end)
end

local function switchTab(tn) for n,pg in pairs(tabPages) do pg.Visible=(n==tn) end; for n,bt in pairs(tabButtons) do bt.BackgroundColor3=(n==tn) and C.tabA or C.tabI; bt.TextColor3=(n==tn) and C.tabTA or C.tabTI end end
for n,bt in pairs(tabButtons) do bt.MouseButton1Click:Connect(function() switchTab(n) end) end

-- ========================
-- PAGE 1: AUTO MONSTER
-- ========================
local p1=mkP("AutoFarm")
local s1=mkSc(p1,1); mkH(s1,"AUTO MONSTER",0)
mkT(s1,"⚔ Auto Monster",1,C.txt,function(v) autoMonsterOn=v end)
mkL(s1,"Teleports above each monster facing down. Auto attack handles damage.",2)

local s2=mkSc(p1,2); mkH(s2,"TELEPORT SPEED",0)
mkS(s2,"⏱ Speed (per monster)",1, 0.1, 10.0, 1.0, false,"s",function(v) farmSpeed=v end)
mkL(s2,"How long to stay at each monster before moving to next.",2)

local s3=mkSc(p1,3); mkH(s3,"SELECT MONSTER LEVEL",0)
local dropBtn=Instance.new("TextButton"); dropBtn.Size=UDim2.new(1,0,0,30); dropBtn.BackgroundColor3=C.drop; dropBtn.Text="▼  Select Level..."; dropBtn.TextColor3=C.txt; dropBtn.TextSize=12; dropBtn.Font=Enum.Font.GothamMedium; dropBtn.TextXAlignment=Enum.TextXAlignment.Left; dropBtn.BorderSizePixel=0; dropBtn.LayoutOrder=1; dropBtn.Parent=s3; Instance.new("UICorner",dropBtn).CornerRadius=UDim.new(0,6); Instance.new("UIStroke",dropBtn).Color=C.brd; Instance.new("UIPadding",dropBtn).PaddingLeft=UDim.new(0,12)
local dropList=Instance.new("Frame"); dropList.Size=UDim2.new(1,0,0,0); dropList.AutomaticSize=Enum.AutomaticSize.Y; dropList.BackgroundColor3=C.drop; dropList.BorderSizePixel=0; dropList.LayoutOrder=2; dropList.Visible=false; dropList.ClipsDescendants=true; dropList.Parent=s3; Instance.new("UICorner",dropList).CornerRadius=UDim.new(0,6); Instance.new("UIStroke",dropList).Color=C.brd
local dropScroll=Instance.new("ScrollingFrame"); dropScroll.Size=UDim2.new(1,0,0,160); dropScroll.BackgroundTransparency=1; dropScroll.ScrollBarThickness=3; dropScroll.ScrollBarImageColor3=C.acc; dropScroll.AutomaticCanvasSize=Enum.AutomaticSize.Y; dropScroll.CanvasSize=UDim2.new(0,0,0,0); dropScroll.BorderSizePixel=0; dropScroll.Parent=dropList; local dll=Instance.new("UIListLayout",dropScroll); dll.Padding=UDim.new(0,1); dll.SortOrder=Enum.SortOrder.LayoutOrder
local dropOpen=false; dropBtn.MouseButton1Click:Connect(function() dropOpen=not dropOpen; dropList.Visible=dropOpen end)

local function popDrop()
	for _,ch in ipairs(dropScroll:GetChildren()) do if ch:IsA("TextButton") then ch:Destroy() end end
	for i,lv in ipairs(getAllLevels()) do
		local cnt=countMonstersForLevel(lv); local tot=LEVEL_MONSTERS[lv] and #LEVEL_MONSTERS[lv] or 0
		local it=Instance.new("TextButton"); it.Size=UDim2.new(1,0,0,26); it.BackgroundColor3=(selectedLevel==lv) and C.acc or C.drop; it.Text="    Lv."..lv.."  •  "..cnt.."/"..tot; it.TextColor3=(selectedLevel==lv) and C.txt or C.dim; it.TextSize=12; it.Font=Enum.Font.Gotham; it.TextXAlignment=Enum.TextXAlignment.Left; it.BorderSizePixel=0; it.LayoutOrder=i; it.Parent=dropScroll
		it.MouseEnter:Connect(function() it.BackgroundColor3=C.hover; it.TextColor3=C.txt end)
		it.MouseLeave:Connect(function() it.BackgroundColor3=(selectedLevel==lv) and C.acc or C.drop; it.TextColor3=(selectedLevel==lv) and C.txt or C.dim end)
		it.MouseButton1Click:Connect(function() selectedLevel=lv; dropBtn.Text="▼  Level "..lv.."  •  "..cnt.." monsters"; dropOpen=false; dropList.Visible=false; for _,bb in ipairs(dropScroll:GetChildren()) do if bb:IsA("TextButton") then bb.BackgroundColor3=C.drop; bb.TextColor3=C.dim end end; it.BackgroundColor3=C.acc; it.TextColor3=C.txt end)
	end
end
mkB(s3,"🔄 Refresh List",3,C.acc,popDrop); task.delay(1,popDrop)

local s4=mkSc(p1,4); mkH(s4,"STATUS",0)
local lblLevel=mkL(s4,"Level: ---",1)
local lblTarget=mkL(s4,"Target: None",2)
local lblFarm=mkL(s4,"Auto Monster: Off",3)
local lblCount=mkL(s4,"Monsters: 0",4)
local lblIndex=mkL(s4,"Queue: 0/0",5)
local lblSpeed=mkL(s4,"Speed: 1.0s",6)

-- PAGE 2
local p2=mkP("AutoEgg")
local es1=mkSc(p2,1); mkH(es1,"PET EGG",0); mkT(es1,"🥚 Auto Best Pet",1,C.warn,function(v) autoPetOn=v end)
local es2=mkSc(p2,2); mkH(es2,"STATUS",0); local lblPet=mkL(es2,"🐾 Pet: Off",1); local lblPetCount=mkL(es2,"Eggs Bought: 0",2)

-- PAGE 3
local p3=mkP("Settings")
local ss1=mkSc(p3,1); mkH(ss1,"SERVER",0)
mkB(ss1,"🔄 Rejoin This Server",1,C.acc,function() TeleportService:TeleportToPlaceInstance(game.PlaceId,game.JobId,Player) end)
mkB(ss1,"🌐 Join Lowest Server",2,Color3.fromRGB(40,140,200),function() serverHopLowest() end)
local ss2=mkSc(p3,2); mkH(ss2,"AUTO REJOIN",0); mkT(ss2,"🔁 Auto Rejoin on Kick",1,C.txt,function(v) autoRejoinOn=v end); local lblRejoin=mkL(ss2,"Status: Off",2)
local ss3=mkSc(p3,3); mkH(ss3,"INFO",0); mkL(ss3,"Minimize: RightCtrl",1); mkL(ss3,"🚌 BUS HUB v7.0",2)

-- DRAG
do local dg,di,ds,sp=false,nil,nil,nil
	Bar.InputBegan:Connect(function(i) if i.UserInputType==Enum.UserInputType.MouseButton1 then dg=true;ds=i.Position;sp=Main.Position;i.Changed:Connect(function() if i.UserInputState==Enum.UserInputState.End then dg=false end end) end end)
	Bar.InputChanged:Connect(function(i) if i.UserInputType==Enum.UserInputType.MouseMovement then di=i end end)
	UserInputService.InputChanged:Connect(function(i) if i==di and dg then local d=i.Position-ds;Main.Position=UDim2.new(sp.X.Scale,sp.X.Offset+d.X,sp.Y.Scale,sp.Y.Offset+d.Y) end end)
end

local full=Main.Size
local function toggleMin() minimized=not minimized;if minimized then CA.Visible=false;TB.Visible=false;TweenService:Create(Main,TweenInfo.new(0.2),{Size=UDim2.new(0,340,0,40)}):Play();MinBtn.Text="+" else TweenService:Create(Main,TweenInfo.new(0.2),{Size=full}):Play();task.delay(0.2,function() CA.Visible=true;TB.Visible=true end);MinBtn.Text="—" end end
MinBtn.MouseButton1Click:Connect(toggleMin)
UserInputService.InputBegan:Connect(function(i,g) if not g and i.KeyCode==Enum.KeyCode.RightControl then toggleMin() end end)

-- ========================
-- AUTO ATTACK LOOP - keeps firing every 2 sec
-- ========================
task.spawn(function()
	while true do
		if autoMonsterOn then
			if not autoAttackFired then fireAutoAttackOn(); autoAttackFired=true end
			fireAutoAttackOn()
		else
			if autoAttackFired then fireAutoAttackOff(); autoAttackFired=false end
		end
		task.wait(2)
	end
end)

-- PET LOOP
local eggsCount=0
task.spawn(function() while true do if autoPetOn then firePetEggBuy();eggsCount+=1;lblPet.Text="🐾 Pet: Buying...";lblPetCount.Text="Eggs Bought: "..eggsCount else lblPet.Text="🐾 Pet: Off" end;task.wait(2) end end)

-- REJOIN
game:GetService("GuiService").ErrorMessageChanged:Connect(function() if autoRejoinOn then task.wait(3);TeleportService:Teleport(game.PlaceId,Player) end end)
pcall(function() local ef=game:GetService("CoreGui"):WaitForChild("RobloxPromptGui",5);if ef then ef.DescendantAdded:Connect(function() if autoRejoinOn then task.wait(3);TeleportService:Teleport(game.PlaceId,Player) end end) end end)
task.spawn(function() while true do lblRejoin.Text=autoRejoinOn and "Status: ✅ Watching" or "Status: Off";task.wait(1) end end)

-- ========================
-- AUTO MONSTER LOOP
-- Teleport above monster facing down, auto attack does the damage
-- ========================

task.spawn(function()
	local monsterList={}
	local currentIndex=0
	local lastLevel=-1

	while true do
		if not Char or not Char.Parent then Char=waitChar() end
		local playerLevel=getLevel()
		lblLevel.Text="Level: "..tostring(playerLevel)
		lblSpeed.Text="Speed: "..string.format("%.1f",farmSpeed).."s"

		if autoMonsterOn then
			local farmLevel=selectedLevel or playerLevel

			if farmLevel~=lastLevel or #monsterList==0 then
				monsterList=buildMonsterList(farmLevel)
				currentIndex=0
				lastLevel=farmLevel
			end

			lblCount.Text="Monsters: "..#monsterList.." (Lv."..farmLevel..")"

			if #monsterList==0 then
				lblFarm.Text="Auto Monster: No monsters"
				lblTarget.Text="Target: None"
				lblIndex.Text="Queue: 0/0"
				task.wait(1)
				continue
			end

			currentIndex+=1
			if currentIndex>#monsterList then
				monsterList=buildMonsterList(farmLevel)
				currentIndex=1
				if #monsterList==0 then task.wait(1) continue end
			end

			local target=monsterList[currentIndex]
			if not target or not target.Parent then
				monsterList=buildMonsterList(farmLevel)
				currentIndex=1
				if #monsterList==0 then task.wait(1) continue end
				target=monsterList[currentIndex]
			end

			lblTarget.Text="Target: "..target.Name
			lblIndex.Text="Queue: "..currentIndex.."/"..#monsterList
			lblFarm.Text="Auto Monster: Teleporting"

			-- Teleport above monster facing down
			-- Keep re-teleporting during the wait time so player stays in position
			local timer = 0
			while timer < farmSpeed and autoMonsterOn do
				if not target or not target.Parent then break end
				teleportToMonster(target)
				task.wait(0.1)
				timer += 0.1
			end

		else
			monsterList={};currentIndex=0;lastLevel=-1
			lblFarm.Text="Auto Monster: Off"
			lblTarget.Text="Target: None"
			lblCount.Text="Monsters: 0"
			lblIndex.Text="Queue: 0/0"
			task.wait(0.5)
		end
	end
end)
