-- Made this with ChatGPT and configured some things.
-- Combined script with Copy Log GUI functionality

--// Services
local VirtualInputManager = game:GetService("VirtualInputManager")
local TweenService = game:GetService("TweenService")
local Players = game:GetService("Players")
local UserInputService = game:GetService("UserInputService")
local LogService = game:GetService("LogService")
local player = Players.LocalPlayer

--// Variables
local previousMessages = {}
local tester = "User"
local currentTime = os.date("%Y-%m-%d %H:%M:%S")
local running = true
local sunc = true

--// Print Banner
print([[




                                    $$\ $$\               $$\   $$\ $$$$$$$$\ $$$$$$$$\ 
                                    $$ |\__|              $$$\  $$ |$$  _____|\__$$  __|
     $$\    $$\  $$$$$$\  $$\   $$\ $$ |$$\  $$$$$$$\     $$$$\ $$ |$$ |         $$ |   
     \$$\  $$  |$$  __$$\ \$$\ $$  |$$ |$$ |$$  _____|    $$ $$\$$ |$$$$$\       $$ |   
      \$$\$$  / $$ /  $$ | \$$$$  / $$ |$$ |\$$$$$$\      $$ \$$$$ |$$  __|      $$ |   
       \$$$  /  $$ |  $$ | $$  $$<  $$ |$$ | \____$$\     $$ |\$$$ |$$ |         $$ |   
        \$  /   \$$$$$$  |$$  /\$$\ $$ |$$ |$$$$$$$  |$$\ $$ | \$$ |$$$$$$$$\    $$ |   
         \_/     \______/ \__/  \__|\__|\__|\_______/ \__|\__|  \__|\________|   \__|   v1.0
   
            Z - Runs sUNC | X - Runs UNC | C - Saves Console Output to workspace                                                        
                                                                                   
                                                                                   
]])

--// Create Main ScreenGui
local screenGui = Instance.new("ScreenGui")
screenGui.Name = "KeyPressGui"
screenGui.ResetOnSpawn = false
screenGui.ZIndexBehavior = Enum.ZIndexBehavior.Sibling
screenGui.Parent = player:WaitForChild("PlayerGui")

--// Create Shadow behind main frame
local shadowFrame = Instance.new("Frame")
shadowFrame.Name = "Shadow"
shadowFrame.Parent = screenGui
shadowFrame.BackgroundColor3 = Color3.fromRGB(0, 0, 0)
shadowFrame.BackgroundTransparency = 0.7
shadowFrame.BorderSizePixel = 0
shadowFrame.Position = UDim2.new(0.5, -122, 0.5, -108)
shadowFrame.Size = UDim2.new(0, 260, 0, 230)

local shadowCorner = Instance.new("UICorner")
shadowCorner.CornerRadius = UDim.new(0, 14)
shadowCorner.Parent = shadowFrame

--// Create the main frame
local mainFrame = Instance.new("Frame")
mainFrame.Name = "MainFrame"
mainFrame.Parent = screenGui
mainFrame.BackgroundColor3 = Color3.fromRGB(25, 25, 30)
mainFrame.BorderSizePixel = 0
mainFrame.Position = UDim2.new(0.5, -125, 0.5, -110)
mainFrame.Size = UDim2.new(0, 260, 0, 230)
mainFrame.Active = true
mainFrame.Draggable = true

local frameCorner = Instance.new("UICorner")
frameCorner.CornerRadius = UDim.new(0, 12)
frameCorner.Parent = mainFrame

-- Make shadow follow main frame
mainFrame:GetPropertyChangedSignal("Position"):Connect(function()
    shadowFrame.Position = UDim2.new(
        mainFrame.Position.X.Scale,
        mainFrame.Position.X.Offset + 3,
        mainFrame.Position.Y.Scale,
        mainFrame.Position.Y.Offset + 3
    )
end)

--// Top Bar
local topBar = Instance.new("Frame")
topBar.Name = "TopBar"
topBar.Parent = mainFrame
topBar.BackgroundColor3 = Color3.fromRGB(35, 35, 45)
topBar.BorderSizePixel = 0
topBar.Position = UDim2.new(0, 0, 0, 0)
topBar.Size = UDim2.new(1, 0, 0, 35)

local topBarCorner = Instance.new("UICorner")
topBarCorner.CornerRadius = UDim.new(0, 12)
topBarCorner.Parent = topBar

-- Bottom cover for top bar corners
local topBarCover = Instance.new("Frame")
topBarCover.Name = "TopBarCover"
topBarCover.Parent = topBar
topBarCover.BackgroundColor3 = Color3.fromRGB(35, 35, 45)
topBarCover.BorderSizePixel = 0
topBarCover.Position = UDim2.new(0, 0, 1, -10)
topBarCover.Size = UDim2.new(1, 0, 0, 10)

--// Title Icon (circle dot)
local titleDot = Instance.new("Frame")
titleDot.Name = "TitleDot"
titleDot.Parent = topBar
titleDot.BackgroundColor3 = Color3.fromRGB(80, 160, 255)
titleDot.BorderSizePixel = 0
titleDot.Position = UDim2.new(0, 10, 0.5, -5)
titleDot.Size = UDim2.new(0, 10, 0, 10)

local titleDotCorner = Instance.new("UICorner")
titleDotCorner.CornerRadius = UDim.new(1, 0)
titleDotCorner.Parent = titleDot

--// Title Label
local titleLabel = Instance.new("TextLabel")
titleLabel.Name = "TitleLabel"
titleLabel.Parent = topBar
titleLabel.BackgroundTransparency = 1
titleLabel.Position = UDim2.new(0, 26, 0, 0)
titleLabel.Size = UDim2.new(0, 140, 1, 0)
titleLabel.Text = "UNC/sUNC Tester"
titleLabel.TextColor3 = Color3.fromRGB(220, 220, 230)
titleLabel.TextSize = 13
titleLabel.Font = Enum.Font.GothamBold
titleLabel.TextXAlignment = Enum.TextXAlignment.Left

--// Collapse Button
local collapseButton = Instance.new("TextButton")
collapseButton.Name = "CollapseButton"
collapseButton.Parent = topBar
collapseButton.BackgroundColor3 = Color3.fromRGB(60, 60, 75)
collapseButton.Position = UDim2.new(1, -65, 0.5, -12)
collapseButton.Size = UDim2.new(0, 25, 0, 25)
collapseButton.Text = "−"
collapseButton.TextColor3 = Color3.fromRGB(200, 200, 200)
collapseButton.Font = Enum.Font.GothamBold
collapseButton.TextSize = 16
collapseButton.AutoButtonColor = false

local collapseCorner = Instance.new("UICorner")
collapseCorner.CornerRadius = UDim.new(0, 8)
collapseCorner.Parent = collapseButton

collapseButton.MouseEnter:Connect(function()
    TweenService:Create(collapseButton, TweenInfo.new(0.2), {BackgroundColor3 = Color3.fromRGB(80, 80, 100)}):Play()
end)
collapseButton.MouseLeave:Connect(function()
    TweenService:Create(collapseButton, TweenInfo.new(0.2), {BackgroundColor3 = Color3.fromRGB(60, 60, 75)}):Play()
end)

--// Close Button
local closeButton = Instance.new("TextButton")
closeButton.Name = "CloseButton"
closeButton.Parent = topBar
closeButton.BackgroundColor3 = Color3.fromRGB(220, 60, 60)
closeButton.Position = UDim2.new(1, -33, 0.5, -12)
closeButton.Size = UDim2.new(0, 25, 0, 25)
closeButton.Text = "✕"
closeButton.TextColor3 = Color3.fromRGB(255, 255, 255)
closeButton.Font = Enum.Font.GothamBold
closeButton.TextSize = 12
closeButton.AutoButtonColor = false

local closeCorner = Instance.new("UICorner")
closeCorner.CornerRadius = UDim.new(0, 8)
closeCorner.Parent = closeButton

closeButton.MouseEnter:Connect(function()
    TweenService:Create(closeButton, TweenInfo.new(0.2), {BackgroundColor3 = Color3.fromRGB(255, 80, 80)}):Play()
end)
closeButton.MouseLeave:Connect(function()
    TweenService:Create(closeButton, TweenInfo.new(0.2), {BackgroundColor3 = Color3.fromRGB(220, 60, 60)}):Play()
end)

closeButton.MouseButton1Click:Connect(function()
    running = false
    -- Fade out animation
    TweenService:Create(mainFrame, TweenInfo.new(0.3), {BackgroundTransparency = 1}):Play()
    TweenService:Create(shadowFrame, TweenInfo.new(0.3), {BackgroundTransparency = 1}):Play()
    task.wait(0.35)
    screenGui:Destroy()
end)

--// Content Frame (holds all buttons)
local contentFrame = Instance.new("Frame")
contentFrame.Name = "ContentFrame"
contentFrame.Parent = mainFrame
contentFrame.BackgroundTransparency = 1
contentFrame.Position = UDim2.new(0, 0, 0, 38)
contentFrame.Size = UDim2.new(1, 0, 1, -38)

--// Section Label - Key Buttons
local keyLabel = Instance.new("TextLabel")
keyLabel.Name = "KeyLabel"
keyLabel.Parent = contentFrame
keyLabel.BackgroundTransparency = 1
keyLabel.Position = UDim2.new(0, 15, 0, 5)
keyLabel.Size = UDim2.new(1, -30, 0, 18)
keyLabel.Text = "⌨️  KEY BUTTONS"
keyLabel.TextColor3 = Color3.fromRGB(120, 120, 140)
keyLabel.TextSize = 10
keyLabel.Font = Enum.Font.GothamBold
keyLabel.TextXAlignment = Enum.TextXAlignment.Left

--// Function to create a key button
local function createKeyButton(letter, position, tooltipText)
    local btn = Instance.new("TextButton")
    btn.Name = letter .. "Button"
    btn.Parent = contentFrame
    btn.BackgroundColor3 = Color3.fromRGB(45, 45, 55)
    btn.Position = position
    btn.Size = UDim2.new(0, 65, 0, 55)
    btn.Text = ""
    btn.AutoButtonColor = false

    local btnCorner = Instance.new("UICorner")
    btnCorner.CornerRadius = UDim.new(0, 10)
    btnCorner.Parent = btn

    -- Stroke
    local btnStroke = Instance.new("UIStroke")
    btnStroke.Color = Color3.fromRGB(65, 65, 80)
    btnStroke.Thickness = 1.5
    btnStroke.Parent = btn

    -- Key letter
    local keyText = Instance.new("TextLabel")
    keyText.Name = "KeyText"
    keyText.Parent = btn
    keyText.BackgroundTransparency = 1
    keyText.Position = UDim2.new(0, 0, 0, 2)
    keyText.Size = UDim2.new(1, 0, 0, 30)
    keyText.Text = letter:upper()
    keyText.TextColor3 = Color3.fromRGB(255, 255, 255)
    keyText.Font = Enum.Font.GothamBold
    keyText.TextSize = 22

    -- Description text
    local descText = Instance.new("TextLabel")
    descText.Name = "DescText"
    descText.Parent = btn
    descText.BackgroundTransparency = 1
    descText.Position = UDim2.new(0, 0, 0, 30)
    descText.Size = UDim2.new(1, 0, 0, 20)
    descText.Text = tooltipText
    descText.TextColor3 = Color3.fromRGB(140, 140, 160)
    descText.Font = Enum.Font.Gotham
    descText.TextSize = 9

    -- Hover effects
    btn.MouseEnter:Connect(function()
        TweenService:Create(btn, TweenInfo.new(0.2), {BackgroundColor3 = Color3.fromRGB(60, 60, 75)}):Play()
        TweenService:Create(btnStroke, TweenInfo.new(0.2), {Color = Color3.fromRGB(80, 160, 255)}):Play()
    end)
    btn.MouseLeave:Connect(function()
        TweenService:Create(btn, TweenInfo.new(0.2), {BackgroundColor3 = Color3.fromRGB(45, 45, 55)}):Play()
        TweenService:Create(btnStroke, TweenInfo.new(0.2), {Color = Color3.fromRGB(65, 65, 80)}):Play()
    end)

    -- Click effect
    btn.MouseButton1Down:Connect(function()
        TweenService:Create(btn, TweenInfo.new(0.1), {BackgroundColor3 = Color3.fromRGB(80, 160, 255)}):Play()
    end)
    btn.MouseButton1Up:Connect(function()
        TweenService:Create(btn, TweenInfo.new(0.1), {BackgroundColor3 = Color3.fromRGB(60, 60, 75)}):Play()
    end)

    btn.MouseButton1Click:Connect(function()
        local keyCode = Enum.KeyCode[letter:upper()]
        VirtualInputManager:SendKeyEvent(true, keyCode, false, nil)
        task.wait(0.1)
        VirtualInputManager:SendKeyEvent(false, keyCode, false, nil)
    end)

    return btn
end

--// Create key buttons
createKeyButton("z", UDim2.new(0, 15, 0, 25), "sUNC")
createKeyButton("x", UDim2.new(0, 90, 0, 25), "UNC")
createKeyButton("c", UDim2.new(0, 165, 0, 25), "Save")

--// Divider Line
local divider = Instance.new("Frame")
divider.Name = "Divider"
divider.Parent = contentFrame
divider.BackgroundColor3 = Color3.fromRGB(50, 50, 65)
divider.BorderSizePixel = 0
divider.Position = UDim2.new(0, 15, 0, 90)
divider.Size = UDim2.new(1, -30, 0, 1)

--// Section Label - Actions
local actionLabel = Instance.new("TextLabel")
actionLabel.Name = "ActionLabel"
actionLabel.Parent = contentFrame
actionLabel.BackgroundTransparency = 1
actionLabel.Position = UDim2.new(0, 15, 0, 96)
actionLabel.Size = UDim2.new(1, -30, 0, 18)
actionLabel.Text = "📋  ACTIONS"
actionLabel.TextColor3 = Color3.fromRGB(120, 120, 140)
actionLabel.TextSize = 10
actionLabel.Font = Enum.Font.GothamBold
actionLabel.TextXAlignment = Enum.TextXAlignment.Left

--// Function to get console log as string
local function getConsoleLog()
    local logHistory = LogService:GetLogHistory()
    local allMessages = ""

    for _, logEntry in ipairs(logHistory) do
        local message = ""

        if logEntry.messageType == Enum.MessageType.MessageError then
            message = "[ERROR] " .. logEntry.message
        elseif logEntry.messageType == Enum.MessageType.MessageWarning then
            message = "[WARN] " .. logEntry.message
        else
            message = logEntry.message
        end

        if not table.find(previousMessages, message) then
            table.insert(previousMessages, message)
        end

        allMessages = allMessages .. message .. "\n"
    end

    return allMessages
end

--// Function to save the console log
local function saveConsole()
    local allMessages = getConsoleLog()
    writefile(identifyexecutor() .. ".txt", allMessages)
    print("Console saved to file.")
end

--// Function to copy the console log to clipboard
local function copyConsole()
    local allMessages = getConsoleLog()
    if setclipboard then
        setclipboard(allMessages)
        print("Console log copied to clipboard!")
    elseif toclipboard then
        toclipboard(allMessages)
        print("Console log copied to clipboard!")
    else
        warn("Clipboard function not supported by your executor.")
    end
end

--// Copy Log Button
local copyLogBtn = Instance.new("TextButton")
copyLogBtn.Name = "CopyLogButton"
copyLogBtn.Parent = contentFrame
copyLogBtn.BackgroundColor3 = Color3.fromRGB(50, 120, 220)
copyLogBtn.Position = UDim2.new(0, 15, 0, 118)
copyLogBtn.Size = UDim2.new(0, 110, 0, 38)
copyLogBtn.Text = "📋 Copy Log"
copyLogBtn.TextColor3 = Color3.new(1, 1, 1)
copyLogBtn.Font = Enum.Font.GothamBold
copyLogBtn.TextSize = 12
copyLogBtn.AutoButtonColor = false

local copyLogCorner = Instance.new("UICorner")
copyLogCorner.CornerRadius = UDim.new(0, 10)
copyLogCorner.Parent = copyLogBtn

local copyLogStroke = Instance.new("UIStroke")
copyLogStroke.Color = Color3.fromRGB(70, 140, 240)
copyLogStroke.Thickness = 1.5
copyLogStroke.Parent = copyLogBtn

-- Hover effects
copyLogBtn.MouseEnter:Connect(function()
    TweenService:Create(copyLogBtn, TweenInfo.new(0.2), {BackgroundColor3 = Color3.fromRGB(70, 145, 245)}):Play()
end)
copyLogBtn.MouseLeave:Connect(function()
    TweenService:Create(copyLogBtn, TweenInfo.new(0.2), {BackgroundColor3 = Color3.fromRGB(50, 120, 220)}):Play()
end)

copyLogBtn.MouseButton1Click:Connect(function()
    copyConsole()
    -- Visual feedback
    local originalText = copyLogBtn.Text
    copyLogBtn.Text = "✅ Copied!"
    TweenService:Create(copyLogBtn, TweenInfo.new(0.15), {BackgroundColor3 = Color3.fromRGB(50, 190, 80)}):Play()
    TweenService:Create(copyLogStroke, TweenInfo.new(0.15), {Color = Color3.fromRGB(60, 210, 90)}):Play()
    task.wait(1.5)
    copyLogBtn.Text = originalText
    TweenService:Create(copyLogBtn, TweenInfo.new(0.2), {BackgroundColor3 = Color3.fromRGB(50, 120, 220)}):Play()
    TweenService:Create(copyLogStroke, TweenInfo.new(0.2), {Color = Color3.fromRGB(70, 140, 240)}):Play()
end)

--// Save Log Button
local saveLogBtn = Instance.new("TextButton")
saveLogBtn.Name = "SaveLogButton"
saveLogBtn.Parent = contentFrame
saveLogBtn.BackgroundColor3 = Color3.fromRGB(55, 55, 70)
saveLogBtn.Position = UDim2.new(0, 135, 0, 118)
saveLogBtn.Size = UDim2.new(0, 110, 0, 38)
saveLogBtn.Text = "💾 Save Log"
saveLogBtn.TextColor3 = Color3.new(1, 1, 1)
saveLogBtn.Font = Enum.Font.GothamBold
saveLogBtn.TextSize = 12
saveLogBtn.AutoButtonColor = false

local saveLogCorner = Instance.new("UICorner")
saveLogCorner.CornerRadius = UDim.new(0, 10)
saveLogCorner.Parent = saveLogBtn

local saveLogStroke = Instance.new("UIStroke")
saveLogStroke.Color = Color3.fromRGB(75, 75, 95)
saveLogStroke.Thickness = 1.5
saveLogStroke.Parent = saveLogBtn

-- Hover effects
saveLogBtn.MouseEnter:Connect(function()
    TweenService:Create(saveLogBtn, TweenInfo.new(0.2), {BackgroundColor3 = Color3.fromRGB(70, 70, 90)}):Play()
end)
saveLogBtn.MouseLeave:Connect(function()
    TweenService:Create(saveLogBtn, TweenInfo.new(0.2), {BackgroundColor3 = Color3.fromRGB(55, 55, 70)}):Play()
end)

saveLogBtn.MouseButton1Click:Connect(function()
    saveConsole()
    -- Visual feedback
    local originalText = saveLogBtn.Text
    saveLogBtn.Text = "✅ Saved!"
    TweenService:Create(saveLogBtn, TweenInfo.new(0.15), {BackgroundColor3 = Color3.fromRGB(50, 190, 80)}):Play()
    TweenService:Create(saveLogStroke, TweenInfo.new(0.15), {Color = Color3.fromRGB(60, 210, 90)}):Play()
    task.wait(1.5)
    saveLogBtn.Text = originalText
    TweenService:Create(saveLogBtn, TweenInfo.new(0.2), {BackgroundColor3 = Color3.fromRGB(55, 55, 70)}):Play()
    TweenService:Create(saveLogStroke, TweenInfo.new(0.2), {Color = Color3.fromRGB(75, 75, 95)}):Play()
end)

--// Status Bar at bottom
local statusBar = Instance.new("Frame")
statusBar.Name = "StatusBar"
statusBar.Parent = contentFrame
statusBar.BackgroundColor3 = Color3.fromRGB(20, 20, 25)
statusBar.BorderSizePixel = 0
statusBar.Position = UDim2.new(0, 0, 1, -22)
statusBar.Size = UDim2.new(1, 0, 0, 22)

local statusBarCorner = Instance.new("UICorner")
statusBarCorner.CornerRadius = UDim.new(0, 12)
statusBarCorner.Parent = statusBar

-- Cover top corners of status bar
local statusBarCover = Instance.new("Frame")
statusBarCover.Parent = statusBar
statusBarCover.BackgroundColor3 = Color3.fromRGB(20, 20, 25)
statusBarCover.BorderSizePixel = 0
statusBarCover.Position = UDim2.new(0, 0, 0, 0)
statusBarCover.Size = UDim2.new(1, 0, 0, 10)

local statusLabel = Instance.new("TextLabel")
statusLabel.Name = "StatusLabel"
statusLabel.Parent = statusBar
statusLabel.BackgroundTransparency = 1
statusLabel.Position = UDim2.new(0, 10, 0, 0)
statusLabel.Size = UDim2.new(1, -20, 1, 0)
statusLabel.Text = "🟢 Ready | v1.0 | voxlis.NET"
statusLabel.TextColor3 = Color3.fromRGB(100, 100, 120)
statusLabel.TextSize = 9
statusLabel.Font = Enum.Font.Gotham
statusLabel.TextXAlignment = Enum.TextXAlignment.Left

--// Collapse/Expand functionality
local collapsed = false
local originalSize = mainFrame.Size
local originalShadowSize = shadowFrame.Size

collapseButton.MouseButton1Click:Connect(function()
    collapsed = not collapsed
    if collapsed then
        contentFrame.Visible = false
        mainFrame:TweenSize(UDim2.new(0, 260, 0, 35), Enum.EasingDirection.Out, Enum.EasingStyle.Quart, 0.4, true)
        shadowFrame:TweenSize(UDim2.new(0, 260, 0, 35), Enum.EasingDirection.Out, Enum.EasingStyle.Quart, 0.4, true)
        collapseButton.Text = "+"
    else
        contentFrame.Visible = true
        mainFrame:TweenSize(originalSize, Enum.EasingDirection.Out, Enum.EasingStyle.Quart, 0.3, true)
        shadowFrame:TweenSize(originalShadowSize, Enum.EasingDirection.Out, Enum.EasingStyle.Quart, 0.3, true)
        collapseButton.Text = "−"
    end
end)

--// Info Notification GUI
local infoGui = Instance.new("ScreenGui")
infoGui.Name = "InfoGui"
infoGui.ResetOnSpawn = false
infoGui.Parent = player:WaitForChild("PlayerGui")

-- Notification container
local notifFrame = Instance.new("Frame")
notifFrame.Name = "NotifFrame"
notifFrame.Parent = infoGui
notifFrame.BackgroundColor3 = Color3.fromRGB(25, 25, 35)
notifFrame.BorderSizePixel = 0
notifFrame.Position = UDim2.new(0.5, -200, 0, -80)
notifFrame.Size = UDim2.new(0, 400, 0, 70)

local notifCorner = Instance.new("UICorner")
notifCorner.CornerRadius = UDim.new(0, 12)
notifCorner.Parent = notifFrame

local notifStroke = Instance.new("UIStroke")
notifStroke.Color = Color3.fromRGB(80, 160, 255)
notifStroke.Thickness = 1.5
notifStroke.Transparency = 0.5
notifStroke.Parent = notifFrame

-- Accent bar on left
local accentBar = Instance.new("Frame")
accentBar.Parent = notifFrame
accentBar.BackgroundColor3 = Color3.fromRGB(80, 160, 255)
accentBar.BorderSizePixel = 0
accentBar.Position = UDim2.new(0, 0, 0, 8)
accentBar.Size = UDim2.new(0, 3, 1, -16)

local notifTitle = Instance.new("TextLabel")
notifTitle.Parent = notifFrame
notifTitle.BackgroundTransparency = 1
notifTitle.Position = UDim2.new(0, 15, 0, 8)
notifTitle.Size = UDim2.new(1, -30, 0, 18)
notifTitle.Text = "ℹ️  UNC/sUNC Tester Loaded"
notifTitle.TextColor3 = Color3.fromRGB(80, 160, 255)
notifTitle.TextSize = 13
notifTitle.Font = Enum.Font.GothamBold
notifTitle.TextXAlignment = Enum.TextXAlignment.Left

local notifText = Instance.new("TextLabel")
notifText.Parent = notifFrame
notifText.BackgroundTransparency = 1
notifText.Position = UDim2.new(0, 15, 0, 26)
notifText.Size = UDim2.new(1, -30, 0, 38)
notifText.Text = "Press Z for sUNC, X for UNC, C to save results. Open console with /console in chat to view results."
notifText.TextColor3 = Color3.fromRGB(180, 180, 200)
notifText.TextSize = 11
notifText.Font = Enum.Font.Gotham
notifText.TextXAlignment = Enum.TextXAlignment.Left
notifText.TextWrapped = true

-- Tween notification in
local tweenIn = TweenService:Create(notifFrame, TweenInfo.new(0.8, Enum.EasingStyle.Back, Enum.EasingDirection.Out), {
    Position = UDim2.new(0.5, -200, 0, 20)
})
tweenIn:Play()

-- Wait then tween out
task.spawn(function()
    tweenIn.Completed:Wait()
    task.wait(5)

    local tweenOut = TweenService:Create(notifFrame, TweenInfo.new(0.6, Enum.EasingStyle.Back, Enum.EasingDirection.In), {
        Position = UDim2.new(0.5, -200, 0, -80)
    })
    tweenOut:Play()
    tweenOut.Completed:Connect(function()
        infoGui:Destroy()
    end)
end)

--// Function to update status
local function updateStatus(text, color)
    statusLabel.Text = text
    if color then
        local dot = Instance.new("Frame")
    end
end

--// Function to execute sUNC
local function executeSUNC()
    sunc = true
    statusLabel.Text = "🔄 Running sUNC test..."
    print([[

░██████╗██╗░░░██╗███╗░░██╗░█████╗░
██╔═════╝██║░░░██║████╗░██║██╔══██╗
╚█████╗░██║░░░██║██╔██╗██║██║░░╚══╝
░╚═══██╗██║░░░██║██║╚████║██║░░██╗
██████╔═╝╚██████╔═╝██║░╚███║╚█████╔═╝
╚═════╝░░╚═════╝░╚══╝░░╚══╝░╚════╝░

    Script: https://voxlis.net/assets/unc/lua/dumper.lua
]])
    print("\n")
    print("Testing Date and Time: " .. currentTime)
    print(identifyexecutor() .. " tested by " .. tester .. " for voxlis.NET")
    print("\n")
    loadstring(game:HttpGet("https://gitlab.com/sens3/nebunu/-/raw/main/HummingBird8's_sUNC_yes_i_moved_to_gitlab_because_my_github_acc_got_brickedd/sUNCm0m3n7.lua"))()
    statusLabel.Text = "✅ sUNC test complete | v1.0"
end

--// Function to execute UNC
local function executeUNC()
    sunc = false
    statusLabel.Text = "🔄 Running UNC test..."
    print([[

██╗░░░██╗███╗░░██╗░█████╗░░
██║░░░██║████╗░██║██╔══██╗ 
██║░░░██║██╔██╗██║██║░░╚══╝ 
██║░░░██║██║╚████║██║░░██╗ 
╚██████╔═╝██║░╚███║╚█████╔═╝ 
░╚═════╝░╚══╝░░╚══╝░╚════╝░

    Script: https://voxlis.net/assets/unc/lua/dumper.lua
]])
    print("\n")
    print("Testing Date and Time: " .. currentTime)
    print(identifyexecutor() .. " tested by " .. tester .. " for voxlis.NET")
    print("\n")
    loadstring(game:HttpGet("https://raw.githubusercontent.com/unified-naming-convention/NamingStandard/refs/heads/main/UNCCheckEnv.lua"))()
    statusLabel.Text = "✅ UNC test complete | v1.0"
end

--// Function to handle key inputs
local function onKeyPressed(input, gameProcessedEvent)
    if gameProcessedEvent then return end

    if input.KeyCode == Enum.KeyCode.Z then
        executeSUNC()
    elseif input.KeyCode == Enum.KeyCode.X then
        executeUNC()
    elseif input.KeyCode == Enum.KeyCode.C then
        saveConsole()
        statusLabel.Text = "💾 Console saved! | v1.0"
    end
end

--// Connect key press event
UserInputService.InputBegan:Connect(onKeyPressed)

--// Wait until the user stops the script
while running do
    task.wait(1)
end

print("Script execution finished.")
