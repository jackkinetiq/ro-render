--!strict

local HttpService = game:GetService("HttpService")

local PresetStore = {}

local PRESET_KEY = "RoRender_Presets_v1"
local DIRECTORY_KEY = "RoRender_OutputDirectory"

export type Shadow = {
	enabled: boolean,
	color: { number },
	opacity: number,
	offsetX: number,
	offsetY: number,
	blur: number,
}

export type Glow = {
	enabled: boolean,
	color: { number },
	opacity: number,
	size: number,
}

export type Config = {
	yaw: number,
	pitch: number,
	roll: number,
	distance: number,
	fov: number,
	focusOffset: Vector3,
	width: number,
	height: number,
	backgroundColor: { number },
	backgroundTransparency: number,
	strokeThickness: number,
	strokeColor: { number },
	dropShadow: Shadow,
	innerShadow: Shadow,
	outerGlow: Glow,
	innerGlow: Glow,
}

local function rgb(r: number, g: number, b: number): { number }
	return { r, g, b }
end

local function defaultShadow(): Shadow
	return {
		enabled = false,
		color = rgb(0, 0, 0),
		opacity = 0.45,
		offsetX = 6,
		offsetY = 6,
		blur = 10,
	}
end

local function defaultInnerShadow(): Shadow
	return {
		enabled = false,
		color = rgb(0, 0, 0),
		opacity = 0.5,
		offsetX = 4,
		offsetY = 4,
		blur = 8,
	}
end

local function defaultOuterGlow(): Glow
	return {
		enabled = false,
		color = rgb(1, 1, 1),
		opacity = 0.8,
		size = 16,
	}
end

local function defaultInnerGlow(): Glow
	return {
		enabled = false,
		color = rgb(1, 1, 1),
		opacity = 0.6,
		size = 12,
	}
end

function PresetStore.defaultConfig(): Config
	return {
		yaw = math.rad(45),
		pitch = math.rad(-25),
		roll = 0,
		distance = 14,
		fov = 30,
		focusOffset = Vector3.zero,
		width = 512,
		height = 512,
		backgroundColor = rgb(1, 1, 1),
		backgroundTransparency = 0,
		strokeThickness = 0,
		strokeColor = rgb(0, 0, 0),
		dropShadow = defaultShadow(),
		innerShadow = defaultInnerShadow(),
		outerGlow = defaultOuterGlow(),
		innerGlow = defaultInnerGlow(),
	}
end

local function num(value: any, fallback: number): number
	local n = tonumber(value)
	if n == nil or n ~= n then
		return fallback
	end
	return n
end

local function colorOf(value: any, fallback: { number }): { number }
	if typeof(value) ~= "table" then
		return { fallback[1], fallback[2], fallback[3] }
	end
	return {
		math.clamp(num(value[1], fallback[1]), 0, 1),
		math.clamp(num(value[2], fallback[2]), 0, 1),
		math.clamp(num(value[3], fallback[3]), 0, 1),
	}
end

local function shadowOf(value: any, fallback: Shadow): Shadow
	if typeof(value) ~= "table" then
		return {
			enabled = fallback.enabled,
			color = { fallback.color[1], fallback.color[2], fallback.color[3] },
			opacity = fallback.opacity,
			offsetX = fallback.offsetX,
			offsetY = fallback.offsetY,
			blur = fallback.blur,
		}
	end
	return {
		enabled = value.enabled == true,
		color = colorOf(value.color, fallback.color),
		opacity = math.clamp(num(value.opacity, fallback.opacity), 0, 1),
		offsetX = num(value.offsetX, fallback.offsetX),
		offsetY = num(value.offsetY, fallback.offsetY),
		blur = math.max(0, num(value.blur, fallback.blur)),
	}
end

local function glowOf(value: any, fallback: Glow): Glow
	if typeof(value) ~= "table" then
		return {
			enabled = fallback.enabled,
			color = { fallback.color[1], fallback.color[2], fallback.color[3] },
			opacity = fallback.opacity,
			size = fallback.size,
		}
	end
	return {
		enabled = value.enabled == true,
		color = colorOf(value.color, fallback.color),
		opacity = math.clamp(num(value.opacity, fallback.opacity), 0, 1),
		size = math.max(0, num(value.size, fallback.size)),
	}
end

function PresetStore.fromTable(data: { [string]: any }): Config
	local defaults = PresetStore.defaultConfig()
	local focus = data.focusOffset
	local focusOffset = Vector3.zero
	if typeof(focus) == "table" then
		focusOffset = Vector3.new(num(focus[1] or focus.x, 0), num(focus[2] or focus.y, 0), num(focus[3] or focus.z, 0))
	elseif typeof(focus) == "Vector3" then
		focusOffset = focus
	end
	return {
		yaw = num(data.yaw, defaults.yaw),
		pitch = num(data.pitch, defaults.pitch),
		roll = num(data.roll, defaults.roll),
		distance = math.max(0.1, num(data.distance, defaults.distance)),
		fov = math.clamp(num(data.fov, defaults.fov), 1, 120),
		focusOffset = focusOffset,
		width = math.clamp(math.floor(num(data.width, defaults.width)), 16, 4096),
		height = math.clamp(math.floor(num(data.height, defaults.height)), 16, 4096),
		backgroundColor = colorOf(data.backgroundColor, defaults.backgroundColor),
		backgroundTransparency = math.clamp(num(data.backgroundTransparency, defaults.backgroundTransparency), 0, 1),
		strokeThickness = math.max(0, num(data.strokeThickness, defaults.strokeThickness)),
		strokeColor = colorOf(data.strokeColor, defaults.strokeColor),
		dropShadow = shadowOf(data.dropShadow, defaults.dropShadow),
		innerShadow = shadowOf(data.innerShadow, defaults.innerShadow),
		outerGlow = glowOf(data.outerGlow, defaults.outerGlow),
		innerGlow = glowOf(data.innerGlow, defaults.innerGlow),
	}
end

function PresetStore.copy(config: Config): Config
	return PresetStore.fromTable(PresetStore.toTable(config))
end

function PresetStore.toTable(config: Config): { [string]: any }
	local function shadowTable(shadow: Shadow): { [string]: any }
		return {
			enabled = shadow.enabled,
			color = { shadow.color[1], shadow.color[2], shadow.color[3] },
			opacity = shadow.opacity,
			offsetX = shadow.offsetX,
			offsetY = shadow.offsetY,
			blur = shadow.blur,
		}
	end
	local function glowTable(glow: Glow): { [string]: any }
		return {
			enabled = glow.enabled,
			color = { glow.color[1], glow.color[2], glow.color[3] },
			opacity = glow.opacity,
			size = glow.size,
		}
	end
	return {
		yaw = config.yaw,
		pitch = config.pitch,
		roll = config.roll,
		distance = config.distance,
		fov = config.fov,
		focusOffset = { config.focusOffset.X, config.focusOffset.Y, config.focusOffset.Z },
		width = config.width,
		height = config.height,
		backgroundColor = { config.backgroundColor[1], config.backgroundColor[2], config.backgroundColor[3] },
		backgroundTransparency = config.backgroundTransparency,
		strokeThickness = config.strokeThickness,
		strokeColor = { config.strokeColor[1], config.strokeColor[2], config.strokeColor[3] },
		dropShadow = shadowTable(config.dropShadow),
		innerShadow = shadowTable(config.innerShadow),
		outerGlow = glowTable(config.outerGlow),
		innerGlow = glowTable(config.innerGlow),
	}
end

function PresetStore.scalePixels(config: Config, scale: number): Config
	local next = PresetStore.copy(config)
	next.strokeThickness *= scale
	next.dropShadow.offsetX *= scale
	next.dropShadow.offsetY *= scale
	next.dropShadow.blur *= scale
	next.innerShadow.offsetX *= scale
	next.innerShadow.offsetY *= scale
	next.innerShadow.blur *= scale
	next.outerGlow.size *= scale
	next.innerGlow.size *= scale
	return next
end

local function decode(raw: string?): { [string]: Config }
	if not raw or raw == "" then
		return {}
	end
	local ok, data = pcall(function()
		return HttpService:JSONDecode(raw)
	end)
	if not ok or typeof(data) ~= "table" then
		return {}
	end
	local presets: { [string]: Config } = {}
	for name, entry in data :: { [string]: any } do
		if typeof(name) == "string" and typeof(entry) == "table" then
			presets[name] = PresetStore.fromTable(entry)
		end
	end
	return presets
end

local function encode(presets: { [string]: Config }): string
	local out: { [string]: any } = {}
	for name, config in presets do
		out[name] = PresetStore.toTable(config)
	end
	return HttpService:JSONEncode(out)
end

function PresetStore.load(plugin: Plugin): { [string]: Config }
	local raw = plugin:GetSetting(PRESET_KEY)
	if typeof(raw) == "string" then
		return decode(raw)
	end
	return {}
end

function PresetStore.save(plugin: Plugin, presets: { [string]: Config })
	plugin:SetSetting(PRESET_KEY, encode(presets))
end

function PresetStore.listNames(presets: { [string]: Config }): { string }
	local names: { string } = {}
	for name in presets do
		table.insert(names, name)
	end
	table.sort(names)
	return names
end

function PresetStore.upsert(plugin: Plugin, presets: { [string]: Config }, name: string, config: Config): boolean
	local trimmed = name:match("^%s*(.-)%s*$") or ""
	if trimmed == "" then
		return false
	end
	local existed = presets[trimmed] ~= nil
	presets[trimmed] = PresetStore.copy(config)
	PresetStore.save(plugin, presets)
	return existed
end

function PresetStore.delete(plugin: Plugin, presets: { [string]: Config }, name: string): boolean
	if presets[name] == nil then
		return false
	end
	presets[name] = nil
	PresetStore.save(plugin, presets)
	return true
end

function PresetStore.loadDirectory(plugin: Plugin): string
	local raw = plugin:GetSetting(DIRECTORY_KEY)
	if typeof(raw) == "string" then
		return raw
	end
	return ""
end

function PresetStore.saveDirectory(plugin: Plugin, directory: string)
	plugin:SetSetting(DIRECTORY_KEY, directory)
end

return PresetStore
