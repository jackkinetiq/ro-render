--!strict

local HttpService = game:GetService("HttpService")

local Bridge = {}

local BASE = "http://127.0.0.1:28082"
Bridge.DOWN_MESSAGE = "Blender bridge is not running. Start it on port 28082."

local ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"

local lookup: { [string]: number } = {}
for index = 1, #ALPHABET do
	lookup[ALPHABET:sub(index, index)] = index - 1
end

function Bridge.base64Encode(data: string): string
	local out = table.create(math.ceil(#data / 3))
	local count = 0
	local length = #data
	local i = 1
	while i <= length do
		local a = string.byte(data, i) :: number
		local b = if i + 1 <= length then string.byte(data, i + 1) else nil
		local c = if i + 2 <= length then string.byte(data, i + 2) else nil
		local n = a * 65536 + (b or 0) * 256 + (c or 0)
		local c1 = math.floor(n / 262144) % 64
		local c2 = math.floor(n / 4096) % 64
		local c3 = math.floor(n / 64) % 64
		local c4 = n % 64
		count += 1
		local third = if b then ALPHABET:sub(c3 + 1, c3 + 1) else "="
		local fourth = if c then ALPHABET:sub(c4 + 1, c4 + 1) else "="
		out[count] = ALPHABET:sub(c1 + 1, c1 + 1) .. ALPHABET:sub(c2 + 1, c2 + 1) .. third .. fourth
		i += 3
	end
	return table.concat(out)
end

function Bridge.base64Decode(data: string): string
	data = data:gsub("%s", "")
	local groups = math.floor(#data / 4)
	local buf = buffer.create(groups * 3)
	local written = 0
	for group = 0, groups - 1 do
		local i = group * 4 + 1
		local c1 = lookup[data:sub(i, i)] or 0
		local c2 = lookup[data:sub(i + 1, i + 1)] or 0
		local s3 = data:sub(i + 2, i + 2)
		local s4 = data:sub(i + 3, i + 3)
		local c3 = lookup[s3]
		local c4 = lookup[s4]
		local n = c1 * 262144 + c2 * 4096 + (c3 or 0) * 64 + (c4 or 0)
		buffer.writeu8(buf, written, math.floor(n / 65536) % 256)
		written += 1
		if s3 ~= "=" and c3 then
			buffer.writeu8(buf, written, math.floor(n / 256) % 256)
			written += 1
		end
		if s4 ~= "=" and c4 then
			buffer.writeu8(buf, written, n % 256)
			written += 1
		end
	end
	return buffer.tostring(buf):sub(1, written)
end

local function request(method: string, path: string, body: string?): (any?, string?)
	local ok, response = pcall(function()
		return HttpService:RequestAsync({
			Url = BASE .. path,
			Method = method,
			Headers = { ["Content-Type"] = "application/json" },
			Body = body,
		})
	end)
	if not ok or typeof(response) ~= "table" then
		return nil, Bridge.DOWN_MESSAGE
	end
	if response.StatusCode == 0 or response.Success == false and (response.StatusCode == nil or response.StatusCode == 0) then
		return nil, Bridge.DOWN_MESSAGE
	end
	local decoded: any = nil
	if typeof(response.Body) == "string" and response.Body ~= "" then
		local parsed, payload = pcall(function()
			return HttpService:JSONDecode(response.Body)
		end)
		if parsed then
			decoded = payload
		end
	end
	if response.Success ~= true and (response.StatusCode < 200 or response.StatusCode >= 300) then
		local message = Bridge.DOWN_MESSAGE
		if typeof(decoded) == "table" and typeof(decoded.error) == "string" then
			message = decoded.error
		elseif response.StatusCode ~= 0 then
			message = "Bridge returned HTTP " .. tostring(response.StatusCode)
		end
		return decoded, message
	end
	if typeof(decoded) == "table" and decoded.ok == false then
		return decoded, if typeof(decoded.error) == "string" then decoded.error else "Bridge request failed."
	end
	return decoded, nil
end

-- Must match ADDON_VERSION in blender/ro_render/version.py.
Bridge.ADDON_VERSION = 2

function Bridge.health(): (boolean, string?)
	local payload, err = request("GET", "/health", nil)
	if err or typeof(payload) ~= "table" or payload.ok ~= true then
		return false, err or Bridge.DOWN_MESSAGE
	end
	local version = if typeof(payload.version) == "number" then payload.version else 1
	if version < Bridge.ADDON_VERSION then
		return false, "Blender is still running an older ro-render add-on. Restart Blender, then start the bridge again."
	end
	return true, nil
end

function Bridge.uploadMesh(session: string, meshRef: string, positions: string, uvs: string, indices: string): string?
	local body = HttpService:JSONEncode({
		session = session,
		meshRef = meshRef,
		positions = Bridge.base64Encode(positions),
		uvs = Bridge.base64Encode(uvs),
		indices = Bridge.base64Encode(indices),
	})
	local _, err = request("POST", "/mesh", body)
	return err
end

function Bridge.uploadTexture(session: string, textureRef: string, width: number, height: number, rgba: string): string?
	local body = HttpService:JSONEncode({
		session = session,
		textureRef = textureRef,
		width = width,
		height = height,
		rgbaBase64 = Bridge.base64Encode(rgba),
	})
	local _, err = request("POST", "/texture", body)
	return err
end

export type PreviewImage = {
	width: number,
	height: number,
	rgba: string,
	warnings: { string },
}

function Bridge.preview(scene: { [string]: any }): (PreviewImage?, string?)
	local payload, err = request("POST", "/preview", HttpService:JSONEncode(scene))
	if err or typeof(payload) ~= "table" then
		return nil, err or "Preview failed."
	end
	if typeof(payload.rgbaBase64) ~= "string" or typeof(payload.width) ~= "number" or typeof(payload.height) ~= "number" then
		return nil, "Preview did not return an image."
	end
	local warnings = {}
	if typeof(payload.warnings) == "table" then
		for _, message in payload.warnings do
			if typeof(message) == "string" then
				table.insert(warnings, message)
			end
		end
	end
	return {
		width = payload.width,
		height = payload.height,
		rgba = Bridge.base64Decode(payload.rgbaBase64),
		warnings = warnings,
	}, nil
end

function Bridge.startRender(scene: { [string]: any }): (string?, string?)
	local payload, err = request("POST", "/render", HttpService:JSONEncode(scene))
	if err or typeof(payload) ~= "table" then
		return nil, err or "Render failed."
	end
	if typeof(payload.jobId) ~= "string" then
		return nil, "Render did not return a job."
	end
	return payload.jobId, nil
end

export type JobState = {
	status: string,
	path: string?,
	error: string?,
	warnings: { string },
}

function Bridge.job(jobId: string): (JobState?, string?)
	local payload, err = request("GET", "/jobs/" .. jobId, nil)
	if err or typeof(payload) ~= "table" then
		return nil, err or "Lost contact with the Blender bridge."
	end
	local warnings = {}
	if typeof(payload.warnings) == "table" then
		for _, message in payload.warnings do
			if typeof(message) == "string" then
				table.insert(warnings, message)
			end
		end
	end
	return {
		status = if typeof(payload.status) == "string" then payload.status else "error",
		path = if typeof(payload.path) == "string" then payload.path else nil,
		error = if typeof(payload.error) == "string" then payload.error else nil,
		warnings = warnings,
	}, nil
end

return Bridge
