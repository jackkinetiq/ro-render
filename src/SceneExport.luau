--!strict

local AssetService = game:GetService("AssetService")
local HttpService = game:GetService("HttpService")

local CameraRig = require(script.Parent.CameraRig)
local PresetStore = require(script.Parent.PresetStore)

local SceneExport = {}

export type MeshPayload = {
	meshRef: string,
	positions: string,
	uvs: string,
	indices: string,
}

export type TexturePayload = {
	textureRef: string,
	width: number,
	height: number,
	rgba: string,
}

export type ExportResult = {
	scene: { [string]: any },
	meshes: { MeshPayload },
	textures: { TexturePayload },
	warnings: { string },
}

local SHIRT_PARTS = {
	Torso = true,
	UpperTorso = true,
	["Left Arm"] = true,
	["Right Arm"] = true,
	LeftUpperArm = true,
	LeftLowerArm = true,
	LeftHand = true,
	RightUpperArm = true,
	RightLowerArm = true,
	RightHand = true,
}

local PANTS_PARTS = {
	["Left Leg"] = true,
	["Right Leg"] = true,
	LowerTorso = true,
	LeftUpperLeg = true,
	LeftLowerLeg = true,
	LeftFoot = true,
	RightUpperLeg = true,
	RightLowerLeg = true,
	RightFoot = true,
}

type CachedMesh = {
	positions: { Vector3 },
	uvs: { Vector2 },
	indices: { number },
	center: Vector3,
	extent: Vector3,
}

local function packF32(values: { number }): string
	local buf = buffer.create(#values * 4)
	for index, value in values do
		buffer.writef32(buf, (index - 1) * 4, value)
	end
	return buffer.tostring(buf)
end

local function packU32(values: { number }): string
	local buf = buffer.create(#values * 4)
	for index, value in values do
		buffer.writeu32(buf, (index - 1) * 4, value)
	end
	return buffer.tostring(buf)
end

local function cframeComponents(cf: CFrame): { number }
	local x, y, z, r00, r01, r02, r10, r11, r12, r20, r21, r22 = cf:GetComponents()
	return { r00, r01, r02, r10, r11, r12, r20, r21, r22, x, y, z }
end

local function vector3(v: Vector3): { number }
	return { v.X, v.Y, v.Z }
end

local function assetId(uri: string?): string?
	if uri == nil or uri == "" then
		return nil
	end
	return uri:match("(%d+)")
end

local function asArray(value: any): { any }?
	if typeof(value) ~= "table" then
		return nil
	end
	if #value > 0 then
		return value
	end
	local arr = {}
	for _, entry in value do
		table.insert(arr, entry)
	end
	if #arr == 0 then
		return nil
	end
	return arr
end

local function tryVector2(mesh: EditableMesh, reader: () -> Vector2): Vector2?
	local ok, value = pcall(reader)
	if ok and typeof(value) == "Vector2" then
		return value
	end
	return nil
end

local function uvFor(mesh: EditableMesh, vertexId: any, faceId: any, cornerIndex: number, faceUvs: { any }?): Vector2
	local direct = tryVector2(mesh, function()
		return (mesh :: any):GetUV(vertexId)
	end)
	if direct then
		return direct
	end
	if faceUvs and faceUvs[cornerIndex] ~= nil then
		local uvId = faceUvs[cornerIndex]
		local fromFace = tryVector2(mesh, function()
			return (mesh :: any):GetUV(uvId)
		end)
		if fromFace then
			return fromFace
		end
	end
	local perCorner = tryVector2(mesh, function()
		return (mesh :: any):GetVertexFaceUV(vertexId, faceId)
	end)
	if perCorner then
		return perCorner
	end
	return Vector2.zero
end

local function boundsOf(positions: { Vector3 }): (Vector3, Vector3)
	local minV = Vector3.new(math.huge, math.huge, math.huge)
	local maxV = Vector3.new(-math.huge, -math.huge, -math.huge)
	for _, position in positions do
		minV = minV:Min(position)
		maxV = maxV:Max(position)
	end
	local extent = maxV - minV
	if extent.X < 1e-5 then
		extent = Vector3.new(1e-5, extent.Y, extent.Z)
	end
	if extent.Y < 1e-5 then
		extent = Vector3.new(extent.X, 1e-5, extent.Z)
	end
	if extent.Z < 1e-5 then
		extent = Vector3.new(extent.X, extent.Y, 1e-5)
	end
	return (minV + maxV) / 2, extent
end

local function triangulate(mesh: EditableMesh): CachedMesh?
	local positions: { Vector3 } = {}
	local uvs: { Vector2 } = {}
	local indices: { number } = {}
	local faces = asArray(mesh:GetFaces())
	if not faces then
		return nil
	end
	for _, faceId in faces do
		local verts = asArray(mesh:GetFaceVertices(faceId))
		if verts and #verts >= 3 then
			local faceUvs: { any }? = nil
			pcall(function()
				faceUvs = asArray((mesh :: any):GetFaceUVs(faceId))
			end)
			for corner = 2, #verts - 1 do
				local corners = { 1, corner, corner + 1 }
				for _, cornerIndex in corners do
					local vertexId = verts[cornerIndex]
					table.insert(positions, mesh:GetPosition(vertexId))
					table.insert(uvs, uvFor(mesh, vertexId, faceId, cornerIndex, faceUvs))
					table.insert(indices, #positions - 1)
				end
			end
		end
	end
	if #positions == 0 then
		return nil
	end
	local center, extent = boundsOf(positions)
	return {
		positions = positions,
		uvs = uvs,
		indices = indices,
		center = center,
		extent = extent,
	}
end

local function loadEditableMesh(content: any): (any, string?)
	local ok, mesh = pcall(function()
		return AssetService:CreateEditableMeshAsync(content)
	end)
	if not ok then
		return nil, tostring(mesh)
	end
	if mesh == nil then
		return nil, "Studio did not return mesh geometry."
	end
	-- EditableMesh is an Object, not an Instance.
	if typeof(mesh) ~= "Instance" and typeof(mesh) ~= "Object" then
		return nil, "Studio did not return mesh geometry."
	end
	local isMeshOk, isMesh = pcall(function()
		return (mesh :: any):IsA("EditableMesh")
	end)
	if isMeshOk and isMesh then
		return mesh, nil
	end
	return nil, "Studio did not return mesh geometry."
end

local function meshIsLocked(message: string): boolean
	local lower = string.lower(message)
	return string.find(lower, "permission", 1, true) ~= nil
		or string.find(lower, "fork", 1, true) ~= nil
		or string.find(lower, "not allowed", 1, true) ~= nil
end

local function contentFromUri(uri: string): any?
	if uri == "" then
		return nil
	end
	local ok, content = pcall(function()
		return Content.fromUri(uri)
	end)
	if ok then
		return content
	end
	return nil
end

local function readMesh(cache: { [string]: CachedMesh }, key: string, contents: { any }): (CachedMesh?, string?)
	local cached = cache[key]
	if cached then
		return cached, nil
	end
	local lastError: string? = nil
	for _, content in contents do
		if content ~= nil then
			local editable, readErr = loadEditableMesh(content)
			if editable then
				local mesh = triangulate(editable)
				editable:Destroy()
				if mesh then
					cache[key] = mesh
					return mesh, nil
				end
				lastError = "The mesh had no triangles."
			elseif readErr then
				lastError = readErr
			end
		end
	end
	return nil, lastError
end

local function packMesh(mesh: CachedMesh, transform: (Vector3) -> Vector3): (string, string, string)
	local flatPos = table.create(#mesh.positions * 3)
	local flatUv = table.create(#mesh.uvs * 2)
	for _, position in mesh.positions do
		local transformed = transform(position)
		table.insert(flatPos, transformed.X)
		table.insert(flatPos, transformed.Y)
		table.insert(flatPos, transformed.Z)
	end
	for _, uv in mesh.uvs do
		table.insert(flatUv, uv.X)
		table.insert(flatUv, uv.Y)
	end
	return packF32(flatPos), packF32(flatUv), packU32(mesh.indices)
end

local function downsampleRgba(rgba: string, width: number, height: number, maxEdge: number): (string, number, number)
	local longEdge = math.max(width, height)
	if longEdge <= maxEdge or maxEdge < 1 or #rgba ~= width * height * 4 then
		return rgba, width, height
	end
	local newWidth = math.max(1, math.floor(width * maxEdge / longEdge))
	local newHeight = math.max(1, math.floor(height * maxEdge / longEdge))
	local src = buffer.fromstring(rgba)
	local out = buffer.create(newWidth * newHeight * 4)
	for y = 0, newHeight - 1 do
		local sourceY = math.min(height - 1, math.floor(y * height / newHeight))
		for x = 0, newWidth - 1 do
			local sourceX = math.min(width - 1, math.floor(x * width / newWidth))
			buffer.copy(out, (y * newWidth + x) * 4, src, (sourceY * width + sourceX) * 4, 4)
		end
	end
	return buffer.tostring(out), newWidth, newHeight
end

local function pixelsToRgba(pix: buffer, width: number, height: number): string?
	local pixels = width * height
	local byteLen = buffer.len(pix)
	if byteLen == pixels * 4 then
		return buffer.tostring(pix)
	end
	if byteLen == pixels * 16 then
		local out = buffer.create(pixels * 4)
		for pixel = 0, pixels - 1 do
			for channel = 0, 3 do
				local sample = buffer.readf32(pix, pixel * 16 + channel * 4)
				buffer.writeu8(out, pixel * 4 + channel, math.clamp(math.floor(sample * 255 + 0.5), 0, 255))
			end
		end
		return buffer.tostring(out)
	end
	return nil
end

local function captureImage(
	cache: { [string]: TexturePayload },
	sourceKey: string,
	loader: () -> EditableImage?,
	maxEdge: number?
): TexturePayload?
	local existing = cache[sourceKey]
	if existing then
		return existing
	end
	local ok, image = pcall(loader)
	if not ok or typeof(image) ~= "Instance" or not image:IsA("EditableImage") then
		return nil
	end
	local size = image.Size
	local width = math.floor(size.X)
	local height = math.floor(size.Y)
	local readOk, pix = pcall(function()
		return image:ReadPixelsBuffer(Vector2.zero, size)
	end)
	image:Destroy()
	if not readOk or typeof(pix) ~= "buffer" or width < 1 or height < 1 then
		return nil
	end
	local rgba = pixelsToRgba(pix, width, height)
	if not rgba then
		return nil
	end
	if maxEdge ~= nil then
		rgba, width, height = downsampleRgba(rgba, width, height, maxEdge)
	end
	local payload: TexturePayload = {
		textureRef = "tex-" .. tostring(#cache + 1) .. "-" .. HttpService:GenerateGUID(false):sub(1, 8),
		width = width,
		height = height,
		rgba = rgba,
	}
	-- The ref above uses #cache before insert, so two misses can collide if called nested.
	-- Refs only need to be unique inside one export; the table length is stable here.
	cache[sourceKey] = payload
	return payload
end

local function captureUri(cache: { [string]: TexturePayload }, uri: string?, maxEdge: number?): TexturePayload?
	if uri == nil or uri == "" or uri == "rbxassetid://0" then
		return nil
	end
	return captureImage(cache, uri .. ":" .. tostring(maxEdge or 0), function()
		local content = contentFromUri(uri)
		if content == nil then
			error("bad uri")
		end
		return AssetService:CreateEditableImageAsync(content)
	end, maxEdge)
end

local function captureContent(cache: { [string]: TexturePayload }, key: string, content: any, maxEdge: number?): TexturePayload?
	if content == nil then
		return nil
	end
	return captureImage(cache, key, function()
		return AssetService:CreateEditableImageAsync(content)
	end, maxEdge)
end

local function clothingTemplates(model: Model): (string?, string?)
	local shirt: string? = nil
	local pants: string? = nil
	for _, desc in model:GetDescendants() do
		if desc:IsA("Shirt") and desc.ShirtTemplate ~= "" then
			shirt = desc.ShirtTemplate
		elseif desc:IsA("Pants") and desc.PantsTemplate ~= "" then
			pants = desc.PantsTemplate
		end
	end
	return shirt, pants
end

local function partTexture(part: BasePart, shirtUri: string?, pantsUri: string?, cache: { [string]: TexturePayload }, warnings: { string }): (string?, string?)
	local meshPart = if part:IsA("MeshPart") then part else nil
	local special = part:FindFirstChildWhichIsA("SpecialMesh")
	local surface = part:FindFirstChildWhichIsA("SurfaceAppearance")
	local uri: string? = nil
	if meshPart and meshPart.TextureID ~= "" then
		uri = meshPart.TextureID
	elseif special and special.TextureId ~= "" then
		uri = special.TextureId
	end
	if uri == nil and surface then
		local colorMap = (surface :: any).ColorMap
		if typeof(colorMap) == "string" and colorMap ~= "" then
			uri = colorMap
		elseif colorMap ~= nil then
			local image = captureContent(cache, "colormap:" .. part:GetFullName(), colorMap)
			if image then
				return image.textureRef, nil
			end
		end
	end
	if uri == nil then
		for _, child in part:GetChildren() do
			if child:IsA("Decal") and child.Texture ~= "" then
				uri = child.Texture
				break
			elseif child:IsA("Texture") and child.Texture ~= "" then
				uri = child.Texture
				break
			end
		end
	end
	if uri == nil and shirtUri and SHIRT_PARTS[part.Name] then
		uri = shirtUri
	end
	if uri == nil and pantsUri and PANTS_PARTS[part.Name] then
		uri = pantsUri
	end
	if uri == nil then
		return nil, nil
	end
	local image = captureUri(cache, uri)
	if image then
		return image.textureRef, nil
	end
	local id = assetId(uri)
	if id then
		return nil, id
	end
	table.insert(warnings, 'Could not read the texture on "' .. part.Name .. '".')
	return nil, nil
end

local function meshContentsFor(part: BasePart): ({ any }, string?, string)
	local contents = {}
	local fallbackId: string? = nil
	local key = part:GetFullName()
	if part:IsA("MeshPart") then
		local meshContentOk, meshContent = pcall(function()
			return (part :: MeshPart).MeshContent
		end)
		if meshContentOk and meshContent ~= nil then
			table.insert(contents, meshContent)
		end
		if part.MeshId ~= "" then
			local content = contentFromUri(part.MeshId)
			if content then
				table.insert(contents, content)
			end
			fallbackId = assetId(part.MeshId)
			key = part.MeshId
		end
	end
	local special = part:FindFirstChildWhichIsA("SpecialMesh")
	if special and special.MeshType == Enum.MeshType.FileMesh and special.MeshId ~= "" then
		local content = contentFromUri(special.MeshId)
		if content then
			table.insert(contents, content)
		end
		fallbackId = assetId(special.MeshId)
		key = special.MeshId
	end
	return contents, fallbackId, key
end

local function primitiveKind(part: BasePart): string?
	local special = part:FindFirstChildWhichIsA("SpecialMesh")
	if part:IsA("MeshPart") then
		return nil
	end
	if special and special.MeshType == Enum.MeshType.FileMesh and special.MeshId ~= "" then
		return nil
	end
	if part:IsA("UnionOperation") then
		return "Block"
	end
	if part:IsA("WedgePart") then
		return "Wedge"
	end
	if part:IsA("CornerWedgePart") then
		return "CornerWedge"
	end
	if special then
		local meshType = special.MeshType
		if meshType == Enum.MeshType.Sphere or meshType == Enum.MeshType.Head then
			return "Ball"
		elseif meshType == Enum.MeshType.Cylinder then
			return "Cylinder"
		elseif meshType == Enum.MeshType.Wedge then
			return "Wedge"
		else
			return "Block"
		end
	end
	if part:IsA("Part") then
		if part.Shape == Enum.PartType.Ball then
			return "Ball"
		elseif part.Shape == Enum.PartType.Cylinder then
			return "Cylinder"
		elseif part.Shape == Enum.PartType.Wedge then
			return "Wedge"
		elseif part.Shape == Enum.PartType.CornerWedge then
			return "CornerWedge"
		end
	end
	return "Block"
end

local function rigFromConfig(config: PresetStore.Config): CameraRig.Rig
	return {
		yaw = config.yaw,
		pitch = config.pitch,
		roll = config.roll,
		distance = config.distance,
		fov = config.fov,
		focusOffset = config.focusOffset,
	}
end

local function effectsPayload(config: PresetStore.Config): { [string]: any }
	local function shadow(entry: PresetStore.Shadow): { [string]: any }
		return {
			enabled = entry.enabled,
			color = entry.color,
			opacity = entry.opacity,
			offset = { entry.offsetX, entry.offsetY },
			blur = entry.blur,
		}
	end
	local function glow(entry: PresetStore.Glow): { [string]: any }
		return {
			enabled = entry.enabled,
			color = entry.color,
			opacity = entry.opacity,
			size = entry.size,
		}
	end
	return {
		backgroundColor = config.backgroundColor,
		backgroundTransparency = config.backgroundTransparency,
		stroke = {
			thickness = config.strokeThickness,
			color = config.strokeColor,
		},
		dropShadow = shadow(config.dropShadow),
		innerShadow = shadow(config.innerShadow),
		outerGlow = glow(config.outerGlow),
		innerGlow = glow(config.innerGlow),
	}
end

local function colorChannels(color: Color3): { number }
	return { color.R, color.G, color.B }
end

local function sequencePeak(sequence: NumberSequence): number
	local peak = 0
	for _, keypoint in sequence.Keypoints do
		peak = math.max(peak, keypoint.Value)
	end
	return peak
end

local function sequenceFloor(sequence: NumberSequence): number
	local floor = 1
	for _, keypoint in sequence.Keypoints do
		floor = math.min(floor, keypoint.Value)
	end
	return floor
end

local function sequenceColor(sequence: ColorSequence): { number }
	local chosen = sequence.Keypoints[1]
	for _, keypoint in sequence.Keypoints do
		if keypoint.Time <= 0.35 then
			chosen = keypoint
		end
	end
	return colorChannels(chosen.Value)
end

local function emitterPosition(emitter: ParticleEmitter): Vector3?
	local parent = emitter.Parent
	if parent and parent:IsA("Attachment") then
		return parent.WorldPosition
	end
	if parent and parent:IsA("BasePart") then
		return parent.Position
	end
	if parent and parent:IsA("Model") then
		return parent:GetPivot().Position
	end
	return nil
end

local function particleRecords(model: Model, cache: { [string]: TexturePayload }): { any }
	local records = {}
	for _, desc in model:GetDescendants() do
		if desc:IsA("ParticleEmitter") and desc.Enabled and desc.Rate > 0 and sequenceFloor(desc.Transparency) < 1 then
			local position = emitterPosition(desc)
			local size = sequencePeak(desc.Size)
			if position and size > 0 then
				local life = (desc.Lifetime.Min + desc.Lifetime.Max) * 0.5
				local record: { [string]: any } = {
					name = desc.Name,
					position = vector3(position),
					color = sequenceColor(desc.Color),
					size = size,
					rate = desc.Rate,
					life = life,
					speed = (desc.Speed.Min + desc.Speed.Max) * 0.5,
					lightEmission = desc.LightEmission,
					brightness = desc.Brightness,
					count = math.clamp(math.floor(desc.Rate * life * 0.5 + 0.5), 3, 12),
				}
				local image = captureUri(cache, desc.Texture, 256)
				if image then
					record.textureRef = image.textureRef
				end
				table.insert(records, record)
			end
		end
	end
	return records
end

local function effectNumber(instance: Instance, prop: string): number?
	local ok, value = pcall(function()
		return (instance :: any)[prop]
	end)
	if ok and typeof(value) == "number" then
		return value
	end
	return nil
end

local function lightingPayload(): { [string]: any }
	local lighting = game:GetService("Lighting")
	local sun = Vector3.yAxis
	pcall(function()
		sun = lighting:GetSunDirection()
	end)
	local payload: { [string]: any } = {
		ambient = colorChannels(lighting.Ambient),
		outdoorAmbient = colorChannels(lighting.OutdoorAmbient),
		brightness = lighting.Brightness,
		exposure = lighting.ExposureCompensation,
		sunDirection = vector3(sun),
		shadowSoftness = lighting.ShadowSoftness,
		environmentDiffuse = lighting.EnvironmentDiffuseScale,
		environmentSpecular = lighting.EnvironmentSpecularScale,
		globalShadows = lighting.GlobalShadows,
		colorShiftTop = colorChannels(lighting.ColorShift_Top),
		colorShiftBottom = colorChannels(lighting.ColorShift_Bottom),
		sunAngularSize = 21,
		fog = {
			color = colorChannels(lighting.FogColor),
			start = lighting.FogStart,
			["end"] = lighting.FogEnd,
		},
	}
	local sky = lighting:FindFirstChildWhichIsA("Sky")
	if sky then
		local angular = effectNumber(sky, "SunAngularSize")
		if angular then
			payload.sunAngularSize = angular
		end
	end
	local atmosphere = lighting:FindFirstChildWhichIsA("Atmosphere")
	if atmosphere then
		payload.atmosphere = {
			density = atmosphere.Density,
			offset = atmosphere.Offset,
			glare = atmosphere.Glare,
			haze = atmosphere.Haze,
			color = colorChannels(atmosphere.Color),
			decay = colorChannels(atmosphere.Decay),
		}
	end
	local correction = lighting:FindFirstChildWhichIsA("ColorCorrectionEffect")
	if correction and correction.Enabled then
		payload.colorCorrection = {
			brightness = correction.Brightness,
			contrast = correction.Contrast,
			saturation = correction.Saturation,
			tint = colorChannels(correction.TintColor),
		}
	end
	local bloom = lighting:FindFirstChildWhichIsA("BloomEffect")
	if bloom and bloom.Enabled and bloom.Intensity > 0 then
		payload.bloom = {
			intensity = bloom.Intensity,
			size = bloom.Size,
			threshold = bloom.Threshold,
		}
	end
	local blur = lighting:FindFirstChildWhichIsA("BlurEffect")
	if blur and blur.Enabled and blur.Size > 0 then
		payload.blur = {
			size = blur.Size,
		}
	end
	local depth = lighting:FindFirstChildWhichIsA("DepthOfFieldEffect")
	if depth and depth.Enabled then
		payload.depthOfField = {
			focusDistance = depth.FocusDistance,
			inFocusRadius = depth.InFocusRadius,
			nearIntensity = depth.NearIntensity,
			farIntensity = depth.FarIntensity,
		}
	end
	local rays = lighting:FindFirstChildWhichIsA("SunRaysEffect")
	if rays and rays.Enabled and rays.Intensity > 0 then
		payload.sunRays = {
			intensity = rays.Intensity,
			spread = rays.Spread,
		}
	end
	return payload
end

function SceneExport.build(
	model: Model,
	config: PresetStore.Config,
	fileName: string,
	directory: string
): (ExportResult?, string?)
	local cameraCf, focusCf = CameraRig.getCameraCFrame(CFrame.identity, rigFromConfig(config))
	local cameraPos = cameraCf.Position
	local target = focusCf.Position
	local up = cameraCf.UpVector
	local shirtUri, pantsUri = clothingTemplates(model)
	local meshCache: { [string]: CachedMesh } = {}
	local textureCache: { [string]: TexturePayload } = {}
	local meshes: { MeshPayload } = {}
	local warnings: { string } = {}
	local parts: { any } = {}
	local meshCount = 0

	for _, desc in model:GetDescendants() do
		if desc:IsA("BasePart") and desc.Transparency < 1 then
			local special = desc:FindFirstChildWhichIsA("SpecialMesh")
			local cf = desc.CFrame
			local size = desc.Size
			if special and primitiveKind(desc) ~= nil then
				cf = cf * CFrame.new(special.Offset)
				if special.MeshType == Enum.MeshType.Cylinder then
					-- Part cylinders run along X. A SpecialMesh cylinder runs along Y.
					size = Vector3.new(size.Y * special.Scale.Y, size.X * special.Scale.X, size.Z * special.Scale.Z)
					cf = cf * CFrame.Angles(0, 0, math.rad(90))
				else
					size = Vector3.new(size.X * special.Scale.X, size.Y * special.Scale.Y, size.Z * special.Scale.Z)
				end
			end

			local record: { [string]: any } = {
				name = desc.Name,
				cframe = cframeComponents(cf),
				size = vector3(size),
				color = { desc.Color.R, desc.Color.G, desc.Color.B },
				material = desc.Material.Name,
				transparency = desc.Transparency,
			}

			local textureRef, textureId = partTexture(desc, shirtUri, pantsUri, textureCache, warnings)
			if textureRef then
				record.textureRef = textureRef
			elseif textureId then
				record.textureId = textureId
			end

			local kind = primitiveKind(desc)
			if desc:IsA("UnionOperation") then
				table.insert(warnings, 'Union "' .. desc.Name .. '" was sent as a box.')
			end

			if kind then
				record.class = kind
			else
				local contents, fallbackId, cacheKey = meshContentsFor(desc)
				local cached, meshErr = readMesh(meshCache, cacheKey, contents)
				if cached then
					meshCount += 1
					local meshRef = "mesh-" .. tostring(meshCount)
					local scale = Vector3.one
					local offset = Vector3.zero
					local fit = desc:IsA("MeshPart")
					if special and not desc:IsA("MeshPart") then
						scale = special.Scale
						offset = special.Offset
						fit = false
					end
					local positions, uvs, indices = packMesh(cached, function(position: Vector3): Vector3
						if fit then
							-- MeshParts are centered on the part and stretched to Size.
							return Vector3.new(
								(position.X - cached.center.X) / cached.extent.X * size.X,
								(position.Y - cached.center.Y) / cached.extent.Y * size.Y,
								(position.Z - cached.center.Z) / cached.extent.Z * size.Z
							)
						end
						-- File meshes keep their authored origin, then Scale and Offset.
						return Vector3.new(position.X * scale.X, position.Y * scale.Y, position.Z * scale.Z) + offset
					end)
					table.insert(meshes, {
						meshRef = meshRef,
						positions = positions,
						uvs = uvs,
						indices = indices,
					})
					record.class = "Mesh"
					record.meshRef = meshRef
					record.fitToSize = false
				elseif meshErr and meshIsLocked(meshErr) then
					-- A private mesh cannot be downloaded either, and that failure used to cancel the render.
					local assetNote = if fallbackId then " Asset " .. fallbackId .. "." else ""
					table.insert(
						warnings,
						'"'
							.. desc.Name
							.. '" is not shared for reading.'
							.. assetNote
							.. " Ask the owner to allow forking. It was sent as a box."
					)
					record.class = "Block"
				elseif fallbackId then
					record.class = "Mesh"
					record.meshId = fallbackId
					record.fitToSize = desc:IsA("MeshPart")
					if special and not desc:IsA("MeshPart") then
						record.meshScale = vector3(special.Scale)
						record.meshOffset = vector3(special.Offset)
						record.fitToSize = false
					end
				else
					local detail = if meshErr then " " .. meshErr else ""
					table.insert(warnings, 'Could not read the mesh on "' .. desc.Name .. '".' .. detail .. " It was sent as a box.")
					record.class = "Block"
				end
			end

			table.insert(parts, record)
		end
	end

	if #parts == 0 then
		return nil, "The selection has no visible parts."
	end

	local particles = particleRecords(model, textureCache)
	local lighting = lightingPayload()
	local textures: { TexturePayload } = {}
	for _, payload in textureCache do
		table.insert(textures, payload)
	end

	local scene = {
		session = HttpService:GenerateGUID(false),
		subjectName = model.Name,
		fileName = fileName,
		output = {
			directory = directory,
			width = config.width,
			height = config.height,
		},
		camera = {
			position = vector3(cameraPos),
			target = vector3(target),
			up = vector3(up),
			fov = config.fov,
		},
		effects = effectsPayload(config),
		lighting = lighting,
		particles = particles,
		parts = parts,
	}

	return {
		scene = scene,
		meshes = meshes,
		textures = textures,
		warnings = warnings,
	}, nil
end

return SceneExport
