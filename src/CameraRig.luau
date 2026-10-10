--!strict
--[[
	Orbit camera shared by the viewport and the Blender render.
	Orientation is yaw / pitch / roll. Position is the focus offset from the
	subject pivot, plus how far back the camera sits.
]]

export type Rig = {
	yaw: number,
	pitch: number,
	roll: number,
	distance: number,
	fov: number,
	focusOffset: Vector3,
}

local CameraRig = {}

local PITCH_LIMIT = math.rad(89)
local MIN_FOV = 1
local MAX_FOV = 120

function CameraRig.default(): Rig
	return {
		yaw = math.rad(45),
		pitch = math.rad(-25),
		roll = 0,
		distance = 14,
		fov = 30,
		focusOffset = Vector3.zero,
	}
end

function CameraRig.fit(boundingRadius: number): Rig
	local fov = 30
	local halfFov = math.rad(fov / 2)
	local distance = boundingRadius / math.tan(halfFov)
	if distance < boundingRadius * 0.05 then
		distance = boundingRadius * 0.05
	end
	return {
		yaw = math.rad(45),
		pitch = math.rad(-25),
		roll = 0,
		distance = distance,
		fov = fov,
		focusOffset = Vector3.zero,
	}
end

function CameraRig.clampFov(fov: number): number
	return math.clamp(fov, MIN_FOV, MAX_FOV)
end

function CameraRig.minDistance(boundingRadius: number): number
	return math.max(boundingRadius * 0.05, 0.1)
end

function CameraRig.getFocusWorld(pivot: CFrame, rig: Rig): Vector3
	return (pivot * CFrame.new(rig.focusOffset)).Position
end

function CameraRig.getCameraCFrame(pivot: CFrame, rig: Rig): (CFrame, CFrame)
	local focusPos = CameraRig.getFocusWorld(pivot, rig)
	local orbit = CFrame.fromEulerAnglesYXZ(rig.pitch, rig.yaw, 0)
	local cameraPos = focusPos - orbit.LookVector * rig.distance
	local base = CFrame.lookAt(cameraPos, focusPos)
	local cameraCFrame = base * CFrame.Angles(0, 0, rig.roll)
	local focusCFrame = CFrame.new(focusPos)
	return cameraCFrame, focusCFrame
end

function CameraRig.applyToCamera(camera: Camera, pivot: CFrame, rig: Rig)
	local cameraCFrame, focusCFrame = CameraRig.getCameraCFrame(pivot, rig)
	camera.CFrame = cameraCFrame
	camera.Focus = focusCFrame
	camera.FieldOfView = CameraRig.clampFov(rig.fov)
end

function CameraRig.orbitDrag(rig: Rig, deltaX: number, deltaY: number, sensitivity: number): Rig
	local next = table.clone(rig)
	next.yaw = rig.yaw - deltaX * sensitivity
	next.pitch = math.clamp(rig.pitch - deltaY * sensitivity, -PITCH_LIMIT, PITCH_LIMIT)
	return next
end

function CameraRig.panDrag(rig: Rig, deltaX: number, deltaY: number, pivot: CFrame, sensitivity: number): Rig
	local cameraCFrame = CameraRig.getCameraCFrame(pivot, rig)
	local worldDelta = (-cameraCFrame.RightVector * deltaX + cameraCFrame.UpVector * deltaY) * sensitivity
	local objectDelta = pivot:VectorToObjectSpace(worldDelta)
	local next = table.clone(rig)
	next.focusOffset = rig.focusOffset + objectDelta
	return next
end

function CameraRig.zoom(rig: Rig, direction: number, boundingRadius: number): Rig
	local factor = if direction > 0 then 0.9 else 1.1
	local next = table.clone(rig)
	next.distance = math.max(CameraRig.minDistance(boundingRadius), rig.distance * factor)
	return next
end

function CameraRig.rigToDisplayFields(rig: Rig): (number, number, number, number, number, number, number, number)
	return rig.distance,
		rig.fov,
		math.deg(rig.yaw),
		math.deg(rig.pitch),
		math.deg(rig.roll),
		rig.focusOffset.X,
		rig.focusOffset.Y,
		rig.focusOffset.Z
end

function CameraRig.applyDisplayFields(
	rig: Rig,
	distance: number,
	fov: number,
	yawDeg: number,
	pitchDeg: number,
	rollDeg: number,
	offsetX: number,
	offsetY: number,
	offsetZ: number,
	boundingRadius: number
): Rig
	local next = table.clone(rig)
	next.distance = math.max(CameraRig.minDistance(boundingRadius), distance)
	next.fov = CameraRig.clampFov(fov)
	next.yaw = math.rad(yawDeg)
	next.pitch = math.clamp(math.rad(pitchDeg), -PITCH_LIMIT, PITCH_LIMIT)
	next.roll = math.rad(rollDeg)
	next.focusOffset = Vector3.new(offsetX, offsetY, offsetZ)
	return next
end

return CameraRig
