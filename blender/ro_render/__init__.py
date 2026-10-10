"""ro-render bridge. Start it from the 3D View sidebar, then render from Studio."""

import importlib
import sys

import bpy

# Blender only reloads this file when the add-on is reinstalled or re-enabled.
# Submodules stay cached, so an update would keep rendering with the old code.
_restart_bridge = False
if "server" in locals():
    _old_server = sys.modules.get(__name__ + ".server")
    if _old_server is not None:
        _restart_bridge = _old_server.is_running()
        _old_server.stop()
        if bpy.app.timers.is_registered(_old_server.pump):
            bpy.app.timers.unregister(_old_server.pump)
    for _name in ("version", "image_io", "mesh_import", "compositor", "scene", "server"):
        _module = sys.modules.get(f"{__name__}.{_name}")
        if _module is not None:
            importlib.reload(_module)

from . import server, version

bl_info = {
    "name": "ro-render",
    "author": "ro-render",
    "version": (0, 2, 0),
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
        layout.label(text=f"Add-on {version.ADDON_VERSION}")
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
    if _restart_bridge:
        try:
            server.start()
            if not bpy.app.timers.is_registered(server.pump):
                bpy.app.timers.register(server.pump, persistent=True)
        except Exception as exc:
            print("[ro-render] Could not restart the bridge:", exc)


def unregister():
    if server.is_running():
        server.stop()
    if bpy.app.timers.is_registered(server.pump):
        bpy.app.timers.unregister(server.pump)
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
