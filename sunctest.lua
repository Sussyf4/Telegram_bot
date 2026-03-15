-- Made this with ChatGPT and configured some things.
-- Combined script with copy log functionality

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
screenGui.Parent = player:WaitForChild("PlayerGui")

--// Create the main frame (draggable and with rounded corners)
local mainFrame = Instance.new("Frame")
mainFrame.Name = "MainFrame"
mainFrame.Parent = screenGui
mainFrame.BackgroundColor3 = Color3.fromRGB(30, 30, 30)
mainFrame.BorderSizePixel = 0
mainFrame.Position = UDim2.new(0.5, -125, 0.5, -75)
mainFrame.Size = UDim2.new(0, 250, 0, 150)
mainFrame.Active = true
mainFrame.Draggable = true

local frameCorner = Instance.new("UICorner")
frameCorner.CornerRadius = UDim.new(0, 10)
frameCorner.Parent = mainFrame

--// Title Label
local titleLabel = Instance.new("TextLabel")
titleLabel.Name = "TitleLabel"
titleLabel.Parent = mainFrame
titleLabel.BackgroundTransparency = 1
titleLabel.Position = UDim2.new(0, 10, 0, 0)
titleLabel.Size = UDim2.new(0, 120, 0, 30)
titleLabel.Text = "UNC/sUNC Tester"
titleLabel.TextColor3 = Color3.fromRGB(200, 200, 200)
titleLabel.TextSize = 12
titleLabel.Font = Enum.Font.GothamBold
titleLabel.TextXAlignment = Enum.TextXAlignment.Left

--// Create a collapse button in the top-right corner of the main frame
local collapseButton = Instance.new("TextButton")
collapseButton.Name = "CollapseButton"
collapseButton.Parent = mainFrame
collapseButton.BackgroundColor3 = Color3.fromRGB(50, 50, 50)
collapseButton.Position = UDim2.new(1, -60, 0, 0)
collapseButton.Size = UDim2.new(0, 30, 0, 30)
collapseButton.Text = "-"
collapseButton.TextColor3 = Color3.new(1, 1, 1)
collapseButton.Font = Enum.Font.GothamBold
collapseButton.TextSize = 18

local collapseCorner = Instance.new("UICorner")
collapseCorner.CornerRadius = UDim.new(0, 10)
collapseCorner.Parent = collapseButton

--// Close Button
local CloseButton = Instance.new("TextButton")
CloseButton.Name = "CloseButton"
CloseButton.Size = UDim2.new(0, 30, 0, 30)
CloseButton.Position = UDim2.new(1, -30, 0, 0)
CloseButton.BackgroundColor3 = Color3.fromRGB(255, 70, 70)
CloseButton.BorderSizePixel = 0
CloseButton.Font = Enum.Font.GothamBold
CloseButton.Text = "X"
CloseButton.TextColor3 = Color3.fromRGB(255, 255, 255)
CloseButton.TextSize = 14
CloseButton.AutoButtonColor = false
CloseButton.Parent = mainFrame

local CloseCorner = Instance.new("UICorner")
CloseCorner.CornerRadius = UDim.new(0, 10)
CloseCorner.Parent = CloseButton

CloseButton.MouseButton1Click:Connect(function()
    running = false
    screenGui:Destroy()
end)

--// Create a container frame for the key buttons
local keysFrame = Instance.new("Frame")
keysFrame.Name = "KeysFrame"
keysFrame.Parent = mainFrame
keysFrame.BackgroundTransparency = 1
keysFrame.Position = UDim2.new(0, 0, 0, 30)
keysFrame.Size = UDim2.new(1, 0, 1, -30)

--// Function to get console log as string
local function getConsoleLog()
    local logHistory = LogService:GetLogHistory()
    local allMessages = ""

    for _, logEntry in ipairs(logHistory) do
        local message = ""

        if logEntry.messageType == Enum.MessageType.MessageError then
            message = "- " .. logEntry.message
        elseif logEntry.messageType == Enum.MessageType.MessageWarning then
            message = "+ " .. logEntry.message
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

--// Function to create a key button that simulates a key press
local function createKeyButton(letter, position, size)
    local btn = Instance.new("TextButton")
    btn.Name = letter .. "Button"
    btn.Parent = keysFrame
    btn.BackgroundColor3 = Color3.fromRGB(70, 70, 70)
    btn.Position = position
    btn.Size = size or UDim2.new(0, 50, 0, 50)
    btn.Text = letter:upper()
    btn.TextColor3 = Color3.new(1, 1, 1)
    btn.Font = Enum.Font.GothamBold
    btn.TextSize = 18

    local btnCorner = Instance.new("UICorner")
    btnCorner.CornerRadius = UDim.new(0, 10)
    btnCorner.Parent = btn

    -- Hover effects
    btn.MouseEnter:Connect(function()
        TweenService:Create(btn, TweenInfo.new(0.2), {BackgroundColor3 = Color3.fromRGB(100, 100, 100)}):Play()
    end)
    btn.MouseLeave:Connect(function()
        TweenService:Create(btn, TweenInfo.new(0.2), {BackgroundColor3 = Color3.fromRGB(70, 70, 70)}):Play()
    end)

    btn.MouseButton1Click:Connect(function()
        local keyCode = Enum.KeyCode[letter:upper()]
        VirtualInputManager:SendKeyEvent(true, keyCode, false, nil)
        task.wait(0.1)
        VirtualInputManager:SendKeyEvent(false, keyCode, false, nil)
    end)

    return btn
end

--// Create the three key buttons
createKeyButton("z", UDim2.new(0, 10, 0, 10))
createKeyButton("x", UDim2.new(0, 70, 0, 10))
createKeyButton("c", UDim2.new(0, 130, 0, 10))

--// Create Copy Log Button
local copyLogBtn = Instance.new("TextButton")
copyLogBtn.Name = "CopyLogButton"
copyLogBtn.Parent = keysFrame
copyLogBtn.BackgroundColor3 = Color3.fromRGB(50, 120, 200)
copyLogBtn.Position = UDim2.new(0, 10, 0, 70)
copyLogBtn.Size = UDim2.new(0, 230, 0, 35)
copyLogBtn.Text = "📋 Copy Log to Clipboard"
copyLogBtn.TextColor3 = Color3.new(1, 1, 1)
copyLogBtn.Font = Enum.Font.GothamBold
copyLogBtn.TextSize = 14

local copyLogCorner = Instance.new("UICorner")
copyLogCorner.CornerRadius = UDim.new(0, 10)
copyLogCorner.Parent = copyLogBtn

-- Hover effects for copy log button
copyLogBtn.MouseEnter:Connect(function()
    TweenService:Create(copyLogBtn, TweenInfo.new(0.2), {BackgroundColor3 = Color3.fromRGB(70, 150, 230)}):Play()
end)
copyLogBtn.MouseLeave:Connect(function()
    TweenService:Create(copyLogBtn, TweenInfo.new(0.2), {BackgroundColor3 = Color3.fromRGB(50, 120, 200)}):Play()
end)

copyLogBtn.MouseButton1Click:Connect(function()
    copyConsole()
    -- Visual feedback
    local originalText = copyLogBtn.Text
    copyLogBtn.Text = "✅ Copied!"
    TweenService:Create(copyLogBtn, TweenInfo.new(0.2), {BackgroundColor3 = Color3.fromRGB(50, 180, 80)}):Play()
    task.wait(1.5)
    copyLogBtn.Text = originalText
    TweenService:Create(copyLogBtn, TweenInfo.new(0.2), {BackgroundColor3 = Color3.fromRGB(50, 120, 200)}):Play()
end)

--// Update main frame size to accommodate copy log button
mainFrame.Size = UDim2.new(0, 250, 0, 150)
local originalSize = mainFrame.Size

--// Collapse/Expand functionality
local collapsed = false
collapseButton.MouseButton1Click:Connect(function()
    collapsed = not collapsed
    if collapsed then
        keysFrame.Visible = false
        mainFrame:TweenSize(UDim2.new(0, 250, 0, 30), Enum.EasingDirection.Out, Enum.EasingStyle.Quart, 0.5, true)
        collapseButton.Text = "+"
    else
        keysFrame.Visible = true
        mainFrame:TweenSize(originalSize, Enum.EasingDirection.Out, Enum.EasingStyle.Quart, 0.1, true)
        collapseButton.Text = "-"
    end
end)

--// Create Info Text ScreenGui (notification)
local infoGui = Instance.new("ScreenGui")
infoGui.Name = "InfoGui"
infoGui.ResetOnSpawn = false
infoGui.Parent = player:WaitForChild("PlayerGui")

local textLabel = Instance.new("TextLabel")
textLabel.Size = UDim2.new(0.5, 0, 0.2, 0)
textLabel.Position = UDim2.new(0.25, 0, -0.2, 0)
textLabel.BackgroundTransparency = 1
textLabel.TextScaled = true
textLabel.TextColor3 = Color3.new(1, 1, 1)
textLabel.Font = Enum.Font.GothamBold
textLabel.Parent = infoGui
textLabel.Text = "UNC/sUNC Tester Loaded, Press Z to test the sUNC, X for UNC, and C to save the results to your workspace folder. Check console for results by typing /console into chat."
textLabel.TextTransparency = 1

-- Tween in
local tweenIn = TweenService:Create(textLabel, TweenInfo.new(2, Enum.EasingStyle.Quad, Enum.EasingDirection.Out), {
    Position = UDim2.new(0.25, 0, 0.4, 0),
    TextTransparency = 0
})
tweenIn:Play()
tweenIn.Completed:Wait()
task.wait(5)

-- Tween out
local tweenOut = TweenService:Create(textLabel, TweenInfo.new(1.5, Enum.EasingStyle.Quad, Enum.EasingDirection.In), {
    Position = UDim2.new(0.25, 0, -0.2, 0),
    TextTransparency = 1
})
tweenOut:Play()
tweenOut.Completed:Connect(function()
    infoGui:Destroy()
end)

--// Function to execute sUNC
local function executeSUNC()
    sunc = true
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
end

--// Function to execute UNC
local function executeUNC()
    sunc = false
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
        running = false
    end
end

--// Connect key press event
UserInputService.InputBegan:Connect(onKeyPressed)

--// Wait until the user stops the script
while running do
    task.wait(1)
end

print("Script execution finished.")
