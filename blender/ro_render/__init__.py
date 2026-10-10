"""ro-render bridge. Start it from the 3D View sidebar, then render from Studio."""

import bpy

from . import server

bl_info = {
    "name": "ro-render",
    "author": "ro-render",
    "version": (0, 1, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > ro-render",
    "description": "Renders subjects sent by the ro-render Studio plugin",
    "category": "Render",
}


class RORENDER_OT_start(bpy.types.Operator):
    bl_idname = "ro_render.start"
    bl_label = "Start bridge"
    bl_description = "Listen on 127.0.0.1:28082 for the Studio plugin"

    def execute(self, context):
        try:
            server.start()
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        if not bpy.app.timers.is_registered(server.pump):
            bpy.app.timers.register(server.pump, persistent=True)
        self.report({"INFO"}, "ro-render bridge listening on port 28082")
        return {"FINISHED"}


class RORENDER_OT_stop(bpy.types.Operator):
    bl_idname = "ro_render.stop"
    bl_label = "Stop bridge"

    def execute(self, context):
        server.stop()
        if bpy.app.timers.is_registered(server.pump):
            bpy.app.timers.unregister(server.pump)
        return {"FINISHED"}


class RORENDER_PT_panel(bpy.types.Panel):
    bl_label = "ro-render"
    bl_idname = "RORENDER_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "ro-render"

    def draw(self, context):
        layout = self.layout
        if server.is_running():
            layout.label(text="Listening on port 28082")
            layout.operator("ro_render.stop", text="Stop bridge")
        else:
            layout.label(text="Bridge is stopped")
            layout.operator("ro_render.start", text="Start bridge")


_CLASSES = (RORENDER_OT_start, RORENDER_OT_stop, RORENDER_PT_panel)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    if server.is_running():
        server.stop()
    if bpy.app.timers.is_registered(server.pump):
        bpy.app.timers.unregister(server.pump)
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
