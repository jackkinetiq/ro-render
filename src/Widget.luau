--!strict

local AssetService = game:GetService("AssetService")
local Selection = game:GetService("Selection")
local UserInputService = game:GetService("UserInputService")

local Bridge = require(script.Parent.Bridge)
local CameraRig = require(script.Parent.CameraRig)
local PresetStore = require(script.Parent.PresetStore)
local SceneExport = require(script.Parent.SceneExport)
local SubjectUtils = require(script.Parent.SubjectUtils)

local Widget = {}

local COLORS = {
	bg = Color3.fromRGB(46, 46, 46),
	panel = Color3.fromRGB(56, 56, 56),
	text = Color3.fromRGB(230, 230, 230),
	muted = Color3.fromRGB(170, 170, 170),
	accent = Color3.fromRGB(0, 162, 255),
	border = Color3.fromRGB(35, 35, 35),
}

export type WidgetHandle = {
	destroy: () -> (),
}

local function padding(parent: GuiObject, amount: number)
	local pad = Instance.new("UIPadding")
	pad.PaddingTop = UDim.new(0, amount)
	pad.PaddingBottom = UDim.new(0, amount)
	pad.PaddingLeft = UDim.new(0, amount)
	pad.PaddingRight = UDim.new(0, amount)
	pad.Parent = parent
end

local function label(parent: Instance, text: string, size: number, bold: boolean?): TextLabel
	local item = Instance.new("TextLabel")
	item.BackgroundTransparency = 1
	item.TextColor3 = COLORS.text
	item.Font = if bold then Enum.Font.GothamBold else Enum.Font.Gotham
	item.TextSize = size
	item.TextXAlignment = Enum.TextXAlignment.Left
	item.Text = text
	item.Size = UDim2.new(1, 0, 0, size + 6)
	item.Parent = parent
	return item
end

local function textBox(parent: Instance, placeholder: string, height: number): TextBox
	local box = Instance.new("TextBox")
	box.BackgroundColor3 = COLORS.panel
	box.BorderColor3 = COLORS.border
	box.TextColor3 = COLORS.text
	box.PlaceholderColor3 = COLORS.muted
	box.Font = Enum.Font.Gotham
	box.TextSize = 14
	box.ClearTextOnFocus = false
	box.PlaceholderText = placeholder
	box.Size = UDim2.new(1, 0, 0, height)
	box.Parent = parent
	return box
end

local function button(parent: Instance, text: string, height: number, primary: boolean?): TextButton
	local item = Instance.new("TextButton")
	item.BackgroundColor3 = if primary then COLORS.accent else COLORS.panel
	item.BorderColor3 = COLORS.border
	item.TextColor3 = Color3.new(1, 1, 1)
	item.Font = Enum.Font.GothamBold
	item.TextSize = 14
	item.Text = text
	item.AutoButtonColor = true
	item.Size = UDim2.new(1, 0, 0, height)
	item.Parent = parent
	return item
end

local function rgbToHex(color: { number }): string
	local function byte(channel: number): string
		return string.format("%02X", math.clamp(math.floor(channel * 255 + 0.5), 0, 255))
	end
	return "#" .. byte(color[1]) .. byte(color[2]) .. byte(color[3])
end

local function hexToRgb(text: string): { number }?
	local hex = text:gsub("#", ""):gsub("%s", "")
	if #hex == 3 then
		hex = hex:sub(1, 1):rep(2) .. hex:sub(2, 2):rep(2) .. hex:sub(3, 3):rep(2)
	end
	if #hex ~= 6 or hex:find("%X") then
		return nil
	end
	return {
		(tonumber(hex:sub(1, 2), 16) or 0) / 255,
		(tonumber(hex:sub(3, 4), 16) or 0) / 255,
		(tonumber(hex:sub(5, 6), 16) or 0) / 255,
	}
end

local function formatNumber(value: number, digits: number): string
	return string.format("%." .. tostring(digits) .. "f", value)
end

function Widget.create(plugin: Plugin, dock: DockWidgetPluginGui): WidgetHandle
	local presets = PresetStore.load(plugin)
	local selectedPresetName: string? = nil
	local targets: { Instance } = {}
	local config = PresetStore.defaultConfig()
	local boundingRadius = 1
	local pivot = CFrame.new()
	local subjectModel: Model? = nil
	local busy = false
	local alive = true
	local dropdownOpen = false
	local previewDirty = false
	local previewEditable: EditableImage? = nil

	local root = Instance.new("Frame")
	root.Name = "Root"
	root.BackgroundColor3 = COLORS.bg
	root.BorderSizePixel = 0
	root.Size = UDim2.fromScale(1, 1)
	root.Parent = dock

	local scroll = Instance.new("ScrollingFrame")
	scroll.Name = "Form"
	scroll.BackgroundTransparency = 1
	scroll.BorderSizePixel = 0
	scroll.Size = UDim2.new(1, 0, 1, -88)
	scroll.CanvasSize = UDim2.new()
	scroll.AutomaticCanvasSize = Enum.AutomaticSize.Y
	scroll.ScrollBarThickness = 6
	scroll.Parent = root
	padding(scroll, 10)

	local layout = Instance.new("UIListLayout")
	layout.SortOrder = Enum.SortOrder.LayoutOrder
	layout.Padding = UDim.new(0, 8)
	layout.Parent = scroll

	local order = 0
	local function nextOrder(): number
		order += 1
		return order
	end

	local subjectRow = Instance.new("Frame")
	subjectRow.BackgroundTransparency = 1
	subjectRow.Size = UDim2.new(1, 0, 0, 32)
	subjectRow.LayoutOrder = nextOrder()
	subjectRow.Parent = scroll

	local subjectLabel = label(subjectRow, "Subject: (none)", 14, false)
	subjectLabel.Size = UDim2.new(1, -110, 1, 0)

	local useSelectionBtn = button(subjectRow, "Use selection", 32, false)
	useSelectionBtn.Size = UDim2.new(0, 100, 1, 0)
	useSelectionBtn.Position = UDim2.new(1, -100, 0, 0)

	local viewportRow = Instance.new("Frame")
	viewportRow.BackgroundTransparency = 1
	viewportRow.Size = UDim2.new(1, 0, 0, 220)
	viewportRow.LayoutOrder = nextOrder()
	viewportRow.Parent = scroll

	local viewport = Instance.new("ViewportFrame")
	viewport.Name = "PreviewViewport"
	viewport.Active = true
	viewport.BackgroundColor3 = Color3.fromRGB(30, 30, 30)
	viewport.BorderColor3 = COLORS.border
	viewport.Size = UDim2.new(1, -56, 1, 0)
	viewport.Ambient = Color3.fromRGB(200, 200, 200)
	viewport.LightColor = Color3.fromRGB(255, 255, 255)
	viewport.LightDirection = Vector3.new(-1, -1, -1)
	viewport.Parent = viewportRow

	local worldModel = Instance.new("WorldModel")
	worldModel.Parent = viewport

	local viewportCamera = Instance.new("Camera")
	viewportCamera.Parent = viewport
	viewport.CurrentCamera = viewportCamera

	local fitBtn = button(viewportRow, "Fit", 32, false)
	fitBtn.Size = UDim2.new(0, 48, 0, 32)
	fitBtn.Position = UDim2.new(1, -48, 0, 0)

	local emptyHint = label(viewport, "Select a model in the Explorer, then click Use selection.", 13, false)
	emptyHint.Name = "EmptyHint"
	emptyHint.TextColor3 = COLORS.muted
	emptyHint.TextWrapped = true
	emptyHint.TextYAlignment = Enum.TextYAlignment.Center
	emptyHint.Size = UDim2.fromScale(1, 1)
	emptyHint.ZIndex = 2

	local dragHint = label(scroll, "Left-drag orbit  ·  Right-drag pan  ·  Wheel zoom", 12, false)
	dragHint.TextColor3 = COLORS.muted
	dragHint.LayoutOrder = nextOrder()
	local lightingHint = label(scroll, "This view is for aiming. Preview matches the Blender render.", 12, false)
	lightingHint.TextColor3 = COLORS.muted
	lightingHint.TextWrapped = true
	lightingHint.Size = UDim2.new(1, 0, 0, 32)
	lightingHint.LayoutOrder = nextOrder()

	local function section(title: string)
		local item = label(scroll, title, 13, true)
		item.LayoutOrder = nextOrder()
	end

	local function field(title: string): TextBox
		local cell = Instance.new("Frame")
		cell.BackgroundTransparency = 1
		cell.Size = UDim2.new(1, 0, 0, 46)
		cell.LayoutOrder = nextOrder()
		cell.Parent = scroll
		local titleLabel = label(cell, title, 12, false)
		titleLabel.Size = UDim2.new(1, 0, 0, 16)
		titleLabel.TextColor3 = COLORS.muted
		local box = textBox(cell, "", 28)
		box.Position = UDim2.new(0, 0, 0, 18)
		return box
	end

	local function pair(leftTitle: string, rightTitle: string): (TextBox, TextBox)
		local row = Instance.new("Frame")
		row.BackgroundTransparency = 1
		row.Size = UDim2.new(1, 0, 0, 46)
		row.LayoutOrder = nextOrder()
		row.Parent = scroll
		local function cell(titleText: string, xScale: number): TextBox
			local holder = Instance.new("Frame")
			holder.BackgroundTransparency = 1
			holder.Position = UDim2.new(xScale, if xScale > 0 then 3 else 0, 0, 0)
			holder.Size = UDim2.new(0.5, -3, 1, 0)
			holder.Parent = row
			local titleLabel = label(holder, titleText, 12, false)
			titleLabel.Size = UDim2.new(1, 0, 0, 16)
			titleLabel.TextColor3 = COLORS.muted
			local box = textBox(holder, "", 28)
			box.Position = UDim2.new(0, 0, 0, 18)
			return box
		end
		return cell(leftTitle, 0), cell(rightTitle, 0.5)
	end

	section("Camera")
	local fovBox, distanceBox = pair("FOV", "Distance")
	local yawBox, pitchBox = pair("Yaw", "Pitch")
	local rollBox, offsetXBox = pair("Roll", "Position X")
	local offsetYBox, offsetZBox = pair("Position Y", "Position Z")

	section("Background")
	local backgroundColorBox, backgroundTransparencyBox = pair("BackgroundColor", "backgroundTransparency")

	section("Stroke")
	local strokeThicknessBox, strokeColorBox = pair("StrokeThickness", "StrokeColor")

	type ShadowBoxes = {
		toggle: TextButton,
		color: TextBox,
		opacity: TextBox,
		offsetX: TextBox,
		offsetY: TextBox,
		blur: TextBox,
	}

	type GlowBoxes = {
		toggle: TextButton,
		color: TextBox,
		opacity: TextBox,
		size: TextBox,
	}

	local function shadowBlock(title: string): ShadowBoxes
		section(title)
		local row = Instance.new("Frame")
		row.BackgroundTransparency = 1
		row.Size = UDim2.new(1, 0, 0, 28)
		row.LayoutOrder = nextOrder()
		row.Parent = scroll
		local toggle = button(row, "Off", 28, false)
		toggle.Size = UDim2.new(0, 52, 1, 0)
		local colorBox = textBox(row, "#000000", 28)
		colorBox.Position = UDim2.new(0, 58, 0, 0)
		colorBox.Size = UDim2.new(0.5, -32, 1, 0)
		local opacityBox = textBox(row, "Opacity", 28)
		opacityBox.Position = UDim2.new(0.5, 32, 0, 0)
		opacityBox.Size = UDim2.new(0.5, -32, 1, 0)
		local offsetX, offsetY = pair("Offset X", "Offset Y")
		local blurBox = field("Blur")
		return {
			toggle = toggle,
			color = colorBox,
			opacity = opacityBox,
			offsetX = offsetX,
			offsetY = offsetY,
			blur = blurBox,
		}
	end

	local function glowBlock(title: string): GlowBoxes
		section(title)
		local row = Instance.new("Frame")
		row.BackgroundTransparency = 1
		row.Size = UDim2.new(1, 0, 0, 28)
		row.LayoutOrder = nextOrder()
		row.Parent = scroll
		local toggle = button(row, "Off", 28, false)
		toggle.Size = UDim2.new(0, 52, 1, 0)
		local colorBox = textBox(row, "#FFFFFF", 28)
		colorBox.Position = UDim2.new(0, 58, 0, 0)
		colorBox.Size = UDim2.new(1, -168, 1, 0)
		local opacityBox = textBox(row, "Opacity", 28)
		opacityBox.Size = UDim2.new(0, 52, 1, 0)
		opacityBox.Position = UDim2.new(1, -110, 0, 0)
		local sizeBox = textBox(row, "Size", 28)
		sizeBox.Size = UDim2.new(0, 52, 1, 0)
		sizeBox.Position = UDim2.new(1, -52, 0, 0)
		return {
			toggle = toggle,
			color = colorBox,
			opacity = opacityBox,
			size = sizeBox,
		}
	end

	local dropBoxes = shadowBlock("DropShadow")
	local innerShadowBoxes = shadowBlock("InnerShadow")
	local outerGlowBoxes = glowBlock("OuterGlow")
	local innerGlowBoxes = glowBlock("InnerGlow")

	section("Configurations")
	local presetRow = Instance.new("Frame")
	presetRow.BackgroundTransparency = 1
	presetRow.Size = UDim2.new(1, 0, 0, 32)
	presetRow.LayoutOrder = nextOrder()
	presetRow.Parent = scroll

	local dropdownBtn = button(presetRow, "No configuration", 32, false)
	dropdownBtn.Size = UDim2.new(1, -168, 1, 0)
	local presetNameBox = textBox(presetRow, "Name", 32)
	presetNameBox.Size = UDim2.new(0, 80, 1, 0)
	presetNameBox.Position = UDim2.new(1, -160, 0, 0)
	local savePresetBtn = button(presetRow, "Save", 32, false)
	savePresetBtn.Size = UDim2.new(0, 40, 1, 0)
	savePresetBtn.Position = UDim2.new(1, -76, 0, 0)
	local deletePresetBtn = button(presetRow, "Del", 32, false)
	deletePresetBtn.Size = UDim2.new(0, 36, 1, 0)
	deletePresetBtn.Position = UDim2.new(1, -32, 0, 0)

	local dropdownMenu = Instance.new("ScrollingFrame")
	dropdownMenu.Name = "PresetDropdown"
	dropdownMenu.BackgroundColor3 = COLORS.panel
	dropdownMenu.BorderColor3 = COLORS.border
	dropdownMenu.Visible = false
	dropdownMenu.ScrollBarThickness = 6
	dropdownMenu.CanvasSize = UDim2.new()
	dropdownMenu.ZIndex = 20
	dropdownMenu.Parent = dock

	local dropdownList = Instance.new("UIListLayout")
	dropdownList.Padding = UDim.new(0, 2)
	dropdownList.Parent = dropdownMenu

	section("Output")
	local folderBox = field("Folder")
	folderBox.PlaceholderText = "C:\\renders"
	folderBox.Text = PresetStore.loadDirectory(plugin)
	local widthBox, heightBox = pair("Width", "Height")
	local fileNameBox = field("File name")

	local previewFrame = Instance.new("Frame")
	previewFrame.Name = "RenderPreview"
	previewFrame.BackgroundColor3 = Color3.fromRGB(30, 30, 30)
	previewFrame.BorderColor3 = COLORS.border
	previewFrame.Size = UDim2.new(1, -20, 0, 160)
	previewFrame.Position = UDim2.new(0, 10, 1, -236)
	previewFrame.Visible = false
	previewFrame.Parent = root

	local previewImage = Instance.new("ImageLabel")
	previewImage.Name = "Image"
	previewImage.BackgroundTransparency = 1
	previewImage.Size = UDim2.fromScale(1, 1)
	previewImage.ScaleType = Enum.ScaleType.Fit
	previewImage.Parent = previewFrame

	local previewState = label(previewFrame, "", 12, false)
	previewState.TextColor3 = COLORS.muted
	previewState.TextXAlignment = Enum.TextXAlignment.Center
	previewState.Size = UDim2.new(1, 0, 0, 18)
	previewState.Position = UDim2.new(0, 0, 1, -18)
	previewState.ZIndex = 2

	local footer = Instance.new("Frame")
	footer.BackgroundTransparency = 1
	footer.Size = UDim2.new(1, -20, 0, 68)
	footer.Position = UDim2.new(0, 10, 1, -72)
	footer.Parent = root

	local previewBtn = button(footer, "Preview", 32, false)
	previewBtn.Size = UDim2.new(0.5, -4, 0, 32)
	local renderBtn = button(footer, "Render", 32, true)
	renderBtn.Size = UDim2.new(0.5, -4, 0, 32)
	renderBtn.Position = UDim2.new(0.5, 4, 0, 0)

	local statusLabel = label(footer, "Ready.", 13, false)
	statusLabel.TextWrapped = true
	statusLabel.TextColor3 = COLORS.muted
	statusLabel.Position = UDim2.new(0, 0, 0, 36)
	statusLabel.Size = UDim2.new(1, 0, 0, 32)

	local function setStatus(text: string)
		statusLabel.Text = text
	end

	local function markPreviewDirty()
		if previewFrame.Visible then
			previewDirty = true
			previewState.Text = "Preview is out of date."
		end
	end

	local function asRig(): CameraRig.Rig
		return {
			yaw = config.yaw,
			pitch = config.pitch,
			roll = config.roll,
			distance = config.distance,
			fov = config.fov,
			focusOffset = config.focusOffset,
		}
	end

	local function writeRig(rig: CameraRig.Rig)
		config.yaw = rig.yaw
		config.pitch = rig.pitch
		config.roll = rig.roll
		config.distance = rig.distance
		config.fov = rig.fov
		config.focusOffset = rig.focusOffset
	end

	local function paintToggle(toggle: TextButton, enabled: boolean)
		toggle.Text = if enabled then "On" else "Off"
		toggle.BackgroundColor3 = if enabled then COLORS.accent else COLORS.panel
	end

	local function syncShadow(boxes: ShadowBoxes, shadow: PresetStore.Shadow)
		paintToggle(boxes.toggle, shadow.enabled)
		boxes.color.Text = rgbToHex(shadow.color)
		boxes.opacity.Text = formatNumber(shadow.opacity, 2)
		boxes.offsetX.Text = formatNumber(shadow.offsetX, 1)
		boxes.offsetY.Text = formatNumber(shadow.offsetY, 1)
		boxes.blur.Text = formatNumber(shadow.blur, 1)
	end

	local function syncGlow(boxes: GlowBoxes, glow: PresetStore.Glow)
		paintToggle(boxes.toggle, glow.enabled)
		boxes.color.Text = rgbToHex(glow.color)
		boxes.opacity.Text = formatNumber(glow.opacity, 2)
		boxes.size.Text = formatNumber(glow.size, 1)
	end

	local function syncFields()
		local distance, fov, yaw, pitch, roll, ox, oy, oz = CameraRig.rigToDisplayFields(asRig())
		distanceBox.Text = formatNumber(distance, 2)
		fovBox.Text = formatNumber(fov, 1)
		yawBox.Text = formatNumber(yaw, 1)
		pitchBox.Text = formatNumber(pitch, 1)
		rollBox.Text = formatNumber(roll, 1)
		offsetXBox.Text = formatNumber(ox, 2)
		offsetYBox.Text = formatNumber(oy, 2)
		offsetZBox.Text = formatNumber(oz, 2)
		backgroundColorBox.Text = rgbToHex(config.backgroundColor)
		backgroundTransparencyBox.Text = formatNumber(config.backgroundTransparency, 2)
		strokeThicknessBox.Text = formatNumber(config.strokeThickness, 1)
		strokeColorBox.Text = rgbToHex(config.strokeColor)
		widthBox.Text = tostring(config.width)
		heightBox.Text = tostring(config.height)
		syncShadow(dropBoxes, config.dropShadow)
		syncShadow(innerShadowBoxes, config.innerShadow)
		syncGlow(outerGlowBoxes, config.outerGlow)
		syncGlow(innerGlowBoxes, config.innerGlow)
	end

	local function applyRigToViewport()
		if subjectModel then
			CameraRig.applyToCamera(viewportCamera, pivot, asRig())
		end
	end

	local function commitNumber(box: TextBox, fallback: number, minValue: number?, maxValue: number?): number
		local value = tonumber(box.Text)
		if value == nil then
			value = fallback
		end
		if minValue ~= nil then
			value = math.max(minValue, value)
		end
		if maxValue ~= nil then
			value = math.min(maxValue, value)
		end
		return value
	end

	local function commitShadow(boxes: ShadowBoxes, shadow: PresetStore.Shadow)
		shadow.enabled = boxes.toggle.Text == "On"
		local color = hexToRgb(boxes.color.Text)
		if color then
			shadow.color = color
		end
		shadow.opacity = commitNumber(boxes.opacity, shadow.opacity, 0, 1)
		shadow.offsetX = commitNumber(boxes.offsetX, shadow.offsetX)
		shadow.offsetY = commitNumber(boxes.offsetY, shadow.offsetY)
		shadow.blur = commitNumber(boxes.blur, shadow.blur, 0, nil)
	end

	local function commitGlow(boxes: GlowBoxes, glow: PresetStore.Glow)
		glow.enabled = boxes.toggle.Text == "On"
		local color = hexToRgb(boxes.color.Text)
		if color then
			glow.color = color
		end
		glow.opacity = commitNumber(boxes.opacity, glow.opacity, 0, 1)
		glow.size = commitNumber(boxes.size, glow.size, 0, nil)
	end

	local function commitFields()
		local rig = CameraRig.applyDisplayFields(
			asRig(),
			commitNumber(distanceBox, config.distance, nil, nil),
			commitNumber(fovBox, config.fov, nil, nil),
			commitNumber(yawBox, math.deg(config.yaw), nil, nil),
			commitNumber(pitchBox, math.deg(config.pitch), nil, nil),
			commitNumber(rollBox, math.deg(config.roll), nil, nil),
			commitNumber(offsetXBox, config.focusOffset.X, nil, nil),
			commitNumber(offsetYBox, config.focusOffset.Y, nil, nil),
			commitNumber(offsetZBox, config.focusOffset.Z, nil, nil),
			boundingRadius
		)
		writeRig(rig)
		local background = hexToRgb(backgroundColorBox.Text)
		if background then
			config.backgroundColor = background
		end
		config.backgroundTransparency = commitNumber(backgroundTransparencyBox, config.backgroundTransparency, 0, 1)
		config.strokeThickness = commitNumber(strokeThicknessBox, config.strokeThickness, 0, nil)
		local stroke = hexToRgb(strokeColorBox.Text)
		if stroke then
			config.strokeColor = stroke
		end
		commitShadow(dropBoxes, config.dropShadow)
		commitShadow(innerShadowBoxes, config.innerShadow)
		commitGlow(outerGlowBoxes, config.outerGlow)
		commitGlow(innerGlowBoxes, config.innerGlow)
		config.width = math.floor(commitNumber(widthBox, config.width, 16, 4096))
		config.height = math.floor(commitNumber(heightBox, config.height, 16, 4096))
		syncFields()
		applyRigToViewport()
	end

	local watched: { TextBox } = {
		fovBox,
		distanceBox,
		yawBox,
		pitchBox,
		rollBox,
		offsetXBox,
		offsetYBox,
		offsetZBox,
		backgroundColorBox,
		backgroundTransparencyBox,
		strokeThicknessBox,
		strokeColorBox,
		widthBox,
		heightBox,
		dropBoxes.color,
		dropBoxes.opacity,
		dropBoxes.offsetX,
		dropBoxes.offsetY,
		dropBoxes.blur,
		innerShadowBoxes.color,
		innerShadowBoxes.opacity,
		innerShadowBoxes.offsetX,
		innerShadowBoxes.offsetY,
		innerShadowBoxes.blur,
		outerGlowBoxes.color,
		outerGlowBoxes.opacity,
		outerGlowBoxes.size,
		innerGlowBoxes.color,
		innerGlowBoxes.opacity,
		innerGlowBoxes.size,
	}
	for _, box in watched do
		box.FocusLost:Connect(function()
			commitFields()
			markPreviewDirty()
		end)
	end

	local function bindToggle(toggle: TextButton)
		toggle.MouseButton1Click:Connect(function()
			toggle.Text = if toggle.Text == "On" then "Off" else "On"
			commitFields()
			markPreviewDirty()
		end)
	end
	bindToggle(dropBoxes.toggle)
	bindToggle(innerShadowBoxes.toggle)
	bindToggle(outerGlowBoxes.toggle)
	bindToggle(innerGlowBoxes.toggle)

	folderBox.FocusLost:Connect(function()
		PresetStore.saveDirectory(plugin, folderBox.Text)
	end)

	local function clearSubject()
		if subjectModel then
			subjectModel:Destroy()
			subjectModel = nil
		end
		emptyHint.Visible = true
	end

	local function loadSubject(newTargets: { Instance })
		targets = newTargets
		subjectLabel.Text = "Subject: " .. SubjectUtils.displayName(targets)
		clearSubject()
		if #targets == 0 then
			fileNameBox.Text = ""
			return
		end
		fileNameBox.Text = SubjectUtils.sanitizeFileName(targets[1].Name)
		local handle = SubjectUtils.buildSubject(worldModel, targets, CFrame.new())
		if not handle then
			setStatus("Could not build preview.")
			return
		end
		subjectModel = handle.container
		boundingRadius = handle.boundingRadius
		pivot = handle.pivot
		emptyHint.Visible = false
		writeRig(CameraRig.fit(boundingRadius))
		syncFields()
		applyRigToViewport()
		markPreviewDirty()
		setStatus("Subject loaded. Frame it, then click Preview.")
	end

	local function refreshDropdownButton()
		dropdownBtn.Text = selectedPresetName or "No configuration"
	end

	local function closeDropdown()
		dropdownOpen = false
		dropdownMenu.Visible = false
	end

	local function rebuildDropdown()
		for _, child in dropdownMenu:GetChildren() do
			if child:IsA("TextButton") then
				child:Destroy()
			end
		end
		local names = PresetStore.listNames(presets)
		for _, name in names do
			local row = button(dropdownMenu, name, 28, false)
			row.Size = UDim2.new(1, -4, 0, 28)
			row.ZIndex = 21
			row.MouseButton1Click:Connect(function()
				local stored = presets[name]
				if not stored then
					return
				end
				selectedPresetName = name
				config = PresetStore.copy(stored)
				refreshDropdownButton()
				presetNameBox.Text = name
				syncFields()
				applyRigToViewport()
				closeDropdown()
				markPreviewDirty()
				setStatus('Loaded configuration "' .. name .. '".')
			end)
		end
		local height = math.clamp(#names * 30, 32, 160)
		local origin = dropdownBtn.AbsolutePosition - dock.AbsolutePosition
		dropdownMenu.Position = UDim2.fromOffset(origin.X, origin.Y + dropdownBtn.AbsoluteSize.Y)
		dropdownMenu.Size = UDim2.fromOffset(dropdownBtn.AbsoluteSize.X, height)
		dropdownMenu.CanvasSize = UDim2.new(0, 0, 0, #names * 30)
	end

	dropdownBtn.MouseButton1Click:Connect(function()
		dropdownOpen = not dropdownOpen
		if dropdownOpen then
			rebuildDropdown()
			dropdownMenu.Visible = true
		else
			closeDropdown()
		end
	end)

	savePresetBtn.MouseButton1Click:Connect(function()
		commitFields()
		local name = presetNameBox.Text
		if name:match("^%s*$") then
			setStatus("Enter a name to save this configuration.")
			return
		end
		local existed = PresetStore.upsert(plugin, presets, name, config)
		local trimmed = name:match("^%s*(.-)%s*$") or name
		selectedPresetName = trimmed
		refreshDropdownButton()
		setStatus(if existed then 'Updated "' .. trimmed .. '".' else 'Saved "' .. trimmed .. '".')
	end)

	deletePresetBtn.MouseButton1Click:Connect(function()
		local name = selectedPresetName or presetNameBox.Text
		if name == "" then
			setStatus("Select a configuration to delete.")
			return
		end
		if PresetStore.delete(plugin, presets, name) then
			if selectedPresetName == name then
				selectedPresetName = nil
			end
			refreshDropdownButton()
			setStatus('Deleted "' .. name .. '".')
		end
	end)

	fitBtn.MouseButton1Click:Connect(function()
		if not subjectModel then
			return
		end
		writeRig(CameraRig.fit(boundingRadius))
		syncFields()
		applyRigToViewport()
		markPreviewDirty()
	end)

	useSelectionBtn.MouseButton1Click:Connect(function()
		loadSubject(SubjectUtils.collectSelection(Selection))
	end)

	local dragging = false
	local dragButton: Enum.UserInputType? = nil
	local lastPos: Vector3? = nil

	viewport.InputBegan:Connect(function(input)
		if input.UserInputType == Enum.UserInputType.MouseButton1 or input.UserInputType == Enum.UserInputType.MouseButton2 then
			dragging = true
			dragButton = input.UserInputType
			lastPos = input.Position
		end
	end)

	viewport.InputEnded:Connect(function(input)
		if input.UserInputType == dragButton then
			dragging = false
			dragButton = nil
			lastPos = nil
		end
	end)

	viewport.InputChanged:Connect(function(input)
		if not dragging or not lastPos or not subjectModel then
			return
		end
		if input.UserInputType ~= Enum.UserInputType.MouseMovement then
			return
		end
		local delta = input.Position - lastPos
		lastPos = input.Position
		local rig = asRig()
		if dragButton == Enum.UserInputType.MouseButton1 then
			rig = CameraRig.orbitDrag(rig, delta.X, delta.Y, 0.008)
		elseif dragButton == Enum.UserInputType.MouseButton2 then
			rig = CameraRig.panDrag(rig, delta.X, delta.Y, pivot, 0.02)
		end
		writeRig(rig)
		syncFields()
		applyRigToViewport()
		markPreviewDirty()
	end)

	viewport.MouseEnter:Connect(function()
		scroll.ScrollingEnabled = false
	end)
	viewport.MouseLeave:Connect(function()
		scroll.ScrollingEnabled = true
		dragging = false
		dragButton = nil
		lastPos = nil
	end)

	UserInputService.InputChanged:Connect(function(input)
		if not alive or not subjectModel then
			return
		end
		if input.UserInputType ~= Enum.UserInputType.MouseWheel then
			return
		end
		local pos = viewport.AbsolutePosition
		local size = viewport.AbsoluteSize
		local mouse = UserInputService:GetMouseLocation()
		if mouse.X >= pos.X and mouse.X <= pos.X + size.X and mouse.Y >= pos.Y and mouse.Y <= pos.Y + size.Y then
			writeRig(CameraRig.zoom(asRig(), input.Position.Z, boundingRadius))
			syncFields()
			applyRigToViewport()
			markPreviewDirty()
		end
	end)

	local selectionConn = Selection.SelectionChanged:Connect(function()
		subjectLabel.Text = "Subject: " .. SubjectUtils.displayName(SubjectUtils.collectSelection(Selection))
	end)

	local function showPreviewImage(width: number, height: number, rgba: string): string?
		if #rgba ~= width * height * 4 then
			return "Preview image was the wrong size."
		end
		if previewEditable then
			previewEditable:Destroy()
			previewEditable = nil
		end
		local created = AssetService:CreateEditableImage({ Size = Vector2.new(width, height) })
		created:WritePixelsBuffer(Vector2.zero, Vector2.new(width, height), buffer.fromstring(rgba))
		previewImage.ImageContent = Content.fromObject(created)
		previewEditable = created
		previewFrame.Visible = true
		scroll.Size = UDim2.new(1, 0, 1, -248)
		previewDirty = false
		previewState.Text = ""
		return nil
	end

	local function setBusy(isBusy: boolean, previewText: string, renderText: string)
		busy = isBusy
		previewBtn.Text = previewText
		renderBtn.Text = renderText
		previewBtn.AutoButtonColor = not isBusy
		renderBtn.AutoButtonColor = not isBusy
	end

	local function warningText(warnings: { string }): string
		if #warnings == 0 then
			return ""
		end
		return " " .. table.concat(warnings, " ")
	end

	local function run(kind: "preview" | "render")
		if busy then
			return
		end
		if not subjectModel or #targets == 0 then
			setStatus("Select a model or part.")
			return
		end
		local typedFov = tonumber(fovBox.Text)
		if typedFov and (typedFov < 1 or typedFov > 120) then
			setStatus("Field of view must be between 1 and 120.")
			return
		end
		local typedWidth = tonumber(widthBox.Text)
		local typedHeight = tonumber(heightBox.Text)
		if (typedWidth and (typedWidth < 16 or typedWidth > 4096)) or (typedHeight and (typedHeight < 16 or typedHeight > 4096)) then
			setStatus("Width and height must be between 16 and 4096.")
			return
		end
		commitFields()
		local bad = SubjectUtils.findNotArchivable(targets)
		if bad then
			setStatus('"' .. bad.Name .. '" is not archivable, so it cannot be cloned.')
			return
		end
		if config.fov < 1 or config.fov > 120 then
			setStatus("Field of view must be between 1 and 120.")
			return
		end
		if config.width < 16 or config.width > 4096 or config.height < 16 or config.height > 4096 then
			setStatus("Width and height must be between 16 and 4096.")
			return
		end
		local directory = folderBox.Text
		if kind == "render" and directory:match("^%s*$") then
			setStatus("Set an output folder.")
			return
		end
		local model = subjectModel
		if not model then
			setStatus("Select a model or part.")
			return
		end
		setBusy(true, "Working…", "Working…")
		local fileName = SubjectUtils.sanitizeFileName(if fileNameBox.Text == "" then targets[1].Name else fileNameBox.Text)
		local exportConfig = config
		if kind == "preview" then
			local longSide = math.max(config.width, config.height)
			local previewLong = math.min(512, longSide)
			local scale = if longSide > 0 then previewLong / longSide else 1
			exportConfig = PresetStore.scalePixels(config, scale)
			if config.width >= config.height then
				exportConfig.width = previewLong
				exportConfig.height = math.max(1, math.floor(config.height * previewLong / config.width + 0.5))
			else
				exportConfig.height = previewLong
				exportConfig.width = math.max(1, math.floor(config.width * previewLong / config.height + 0.5))
			end
			setStatus("Previewing…")
		else
			exportConfig = PresetStore.copy(config)
			setStatus("Rendering…")
		end

		task.spawn(function()
			local function finish(message: string)
				if not alive then
					return
				end
				setBusy(false, "Preview", "Render")
				setStatus(message)
			end

			local healthy, healthErr = Bridge.health()
			if not healthy then
				finish(healthErr or Bridge.DOWN_MESSAGE)
				return
			end

			local exported, exportErr = SceneExport.build(model, exportConfig, fileName, directory)
			if not exported then
				finish(exportErr or "Could not export the subject.")
				return
			end

			local sessionValue = exported.scene.session
			local session = if typeof(sessionValue) == "string" then sessionValue else ""
			for _, mesh in exported.meshes do
				local uploadErr = Bridge.uploadMesh(session, mesh.meshRef, mesh.positions, mesh.uvs, mesh.indices)
				if uploadErr then
					finish(uploadErr)
					return
				end
			end
			for _, texture in exported.textures do
				local uploadErr =
					Bridge.uploadTexture(session, texture.textureRef, texture.width, texture.height, texture.rgba)
				if uploadErr then
					finish(uploadErr)
					return
				end
			end

			if kind == "preview" then
				local image, previewErr = Bridge.preview(exported.scene)
				if not image then
					finish(previewErr or "Preview failed.")
					return
				end
				local shown, showErr = pcall(function()
					local imageErr = showPreviewImage(image.width, image.height, image.rgba)
					if imageErr then
						error(imageErr)
					end
				end)
				if not shown then
					finish(tostring(showErr))
					return
				end
				finish("Preview ready." .. warningText(exported.warnings) .. warningText(image.warnings))
				return
			end

			local jobId, startErr = Bridge.startRender(exported.scene)
			if not jobId then
				finish(startErr or "Render failed.")
				return
			end
			while alive do
				task.wait(0.5)
				local state, jobErr = Bridge.job(jobId)
				if jobErr or not state then
					finish(jobErr or "Lost contact with the Blender bridge.")
					return
				end
				if state.status == "done" then
					finish("Saved: " .. (state.path or fileName) .. warningText(exported.warnings) .. warningText(state.warnings))
					return
				end
				if state.status == "error" then
					finish(state.error or "Render failed.")
					return
				end
			end
		end)
	end

	previewBtn.MouseButton1Click:Connect(function()
		run("preview")
	end)
	renderBtn.MouseButton1Click:Connect(function()
		run("render")
	end)

	syncFields()
	refreshDropdownButton()

	return {
		destroy = function()
			alive = false
			selectionConn:Disconnect()
			clearSubject()
			if previewEditable then
				previewEditable:Destroy()
				previewEditable = nil
			end
			dropdownMenu:Destroy()
			root:Destroy()
		end,
	}
end

return Widget
