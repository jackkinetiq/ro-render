--!strict

local Widget = require(script.Parent.Widget)

local toolbar = plugin:CreateToolbar("ro-render")
local toggleButton = toolbar:CreateButton(
	"ro-render",
	"Frame a model and render it through Blender",
	"rbxassetid://6031097225"
)

local dock = plugin:CreateDockWidgetPluginGui(
	"RoRenderDock",
	DockWidgetPluginGuiInfo.new(Enum.InitialDockState.Right, false, false, 360, 720, 320, 480)
)
dock.Title = "ro-render"

local widgetHandle: Widget.WidgetHandle? = nil

local function ensureWidget()
	if widgetHandle then
		return
	end
	widgetHandle = Widget.create(plugin, dock)
end

toggleButton.Click:Connect(function()
	ensureWidget()
	dock.Enabled = not dock.Enabled
end)

plugin.Unloading:Connect(function()
	if widgetHandle then
		widgetHandle.destroy()
		widgetHandle = nil
	end
end)
