--!strict

local SubjectUtils = {}

export type SubjectHandle = {
	container: Model,
	boundingRadius: number,
	pivot: CFrame,
}

function SubjectUtils.collectSelection(selectionService: Selection): { Instance }
	local targets: { Instance } = {}
	for _, inst in selectionService:Get() do
		table.insert(targets, inst)
	end
	return targets
end

function SubjectUtils.displayName(targets: { Instance }): string
	if #targets == 0 then
		return "(none)"
	end
	if #targets == 1 then
		return targets[1].Name
	end
	return targets[1].Name .. " +" .. tostring(#targets - 1)
end

function SubjectUtils.findNotArchivable(targets: { Instance }): Instance?
	for _, inst in targets do
		if not inst.Archivable then
			return inst
		end
		for _, desc in inst:GetDescendants() do
			if not desc.Archivable then
				return desc
			end
		end
	end
	return nil
end

local function moveContainerToPivot(container: Model, targetPivot: CFrame)
	local boundsCFrame = container:GetBoundingBox()
	local delta = targetPivot.Position - boundsCFrame.Position
	for _, desc in container:GetDescendants() do
		if desc:IsA("BasePart") then
			-- Keep the posed character still. A second PivotTo would slide the
			-- bounds center off the origin the camera orbits.
			desc.Anchored = true
			desc.CFrame = desc.CFrame + delta
		end
	end
	container.WorldPivot = targetPivot
end

function SubjectUtils.buildSubject(parent: Instance, targets: { Instance }, worldPivot: CFrame?): SubjectHandle?
	if #targets == 0 then
		return nil
	end

	local container = Instance.new("Model")
	container.Name = "RoRenderSubject"
	container.Parent = parent

	for _, target in targets do
		local clone = target:Clone()
		if clone then
			clone.Parent = container
		end
	end

	local _, size = container:GetBoundingBox()
	local radius = math.max(size.X, size.Y, size.Z) / 2
	if radius < 0.01 then
		radius = 1
	end

	local pivot = worldPivot or CFrame.new()
	moveContainerToPivot(container, pivot)

	return {
		container = container,
		boundingRadius = radius,
		pivot = pivot,
	}
end

function SubjectUtils.sanitizeFileName(name: string): string
	local sanitized = name:gsub("[^%w%-_%.]", "_")
	if sanitized == "" or sanitized == "." or sanitized == ".." then
		sanitized = "render"
	end
	return sanitized
end

return SubjectUtils
