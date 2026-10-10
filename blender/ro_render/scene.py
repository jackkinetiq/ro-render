"""Build a subject in its own scene, render a cutout, and composite the effects."""

import math
import os
import tempfile

import bpy
from mathutils import Matrix, Vector

from . import mesh_import
from .compositor import composite_png

_CREATED = "ro_render"


def _engine_names(scene) -> set[str]:
    return {item.identifier for item in scene.render.bl_rna.properties["engine"].enum_items}


def _use_engine(scene, preview: bool):
    available = _engine_names(scene)
    if preview:
        for name in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
            if name in available:
                scene.render.engine = name
                return
    if "CYCLES" in available and not preview:
        scene.render.engine = "CYCLES"
        return
    for name in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "CYCLES"):
        if name in available:
            scene.render.engine = name
            return


def _roblox_to_blender(vector) -> Vector:
    x, y, z = vector
    return Vector((x, -z, y))


def _matrix_from_cframe(components: list) -> Matrix:
    r00, r01, r02, r10, r11, r12, r20, r21, r22, x, y, z = components
    right = _roblox_to_blender((r00, r10, r20))
    up = _roblox_to_blender((r01, r11, r21))
    back = _roblox_to_blender((r02, r12, r22))
    position = _roblox_to_blender((x, y, z))
    return Matrix((
        (right.x, up.x, back.x, position.x),
        (right.y, up.y, back.y, position.y),
        (right.z, up.z, back.z, position.z),
        (0.0, 0.0, 0.0, 1.0),
    ))


def _camera_matrix(position: Vector, target: Vector, up: Vector) -> Matrix:
    forward = target - position
    if forward.length < 1e-6:
        forward = Vector((0.0, -1.0, 0.0))
    forward.normalize()
    z_axis = -forward
    x_axis = up.cross(z_axis)
    if x_axis.length < 1e-6:
        x_axis = Vector((1.0, 0.0, 0.0)).cross(z_axis)
    x_axis.normalize()
    y_axis = z_axis.cross(x_axis).normalized()
    return Matrix((
        (x_axis.x, y_axis.x, z_axis.x, position.x),
        (x_axis.y, y_axis.y, z_axis.y, position.y),
        (x_axis.z, y_axis.z, z_axis.z, position.z),
        (0.0, 0.0, 0.0, 1.0),
    ))


def _link(collection, data, name: str):
    obj = bpy.data.objects.new(name, data)
    collection.objects.link(obj)
    return obj


def _mesh_from_lists(name: str, positions, uvs, indices) -> bpy.types.Mesh:
    faces = []
    for index in range(0, len(indices) - 2, 3):
        faces.append((int(indices[index]), int(indices[index + 1]), int(indices[index + 2])))
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([tuple(p) for p in positions], [], faces)
    mesh.update()
    if len(uvs) == len(positions):
        layer = mesh.uv_layers.new(name="UVMap")
        for poly in mesh.polygons:
            for loop_index in poly.loop_indices:
                vertex = mesh.loops[loop_index].vertex_index
                u, v = uvs[vertex]
                layer.data[loop_index].uv = (float(u), 1.0 - float(v))
    for poly in mesh.polygons:
        poly.use_smooth = True
    return mesh


def _primitive(kind: str, size) -> bpy.types.Mesh:
    hx, hy, hz = size[0] / 2, size[1] / 2, size[2] / 2
    hx, hy, hz = max(hx, 1e-4), max(hy, 1e-4), max(hz, 1e-4)
    if kind == "Ball":
        segments = 24
        rings = 16
        positions = []
        for ring in range(rings + 1):
            v = ring / rings
            phi = v * math.pi
            for segment in range(segments):
                u = segment / segments
                theta = u * math.tau
                positions.append((
                    math.sin(phi) * math.cos(theta) * hx,
                    math.cos(phi) * hy,
                    math.sin(phi) * math.sin(theta) * hz,
                ))
        indices = []
        for ring in range(rings):
            for segment in range(segments):
                a = ring * segments + segment
                b = ring * segments + (segment + 1) % segments
                c = a + segments
                d = b + segments
                indices.extend((a, c, b, b, c, d))
        return _mesh_from_lists(kind, positions, [(0, 0)] * len(positions), indices)
    if kind == "Cylinder":
        segments = 24
        positions = []
        for x in (-hx, hx):
            for segment in range(segments):
                angle = math.tau * segment / segments
                positions.append((x, math.cos(angle) * hy, math.sin(angle) * hz))
        positions.append((-hx, 0, 0))
        positions.append((hx, 0, 0))
        indices = []
        for segment in range(segments):
            nxt = (segment + 1) % segments
            indices.extend((segment, nxt, nxt + segments, segment, nxt + segments, segment + segments))
            indices.extend((len(positions) - 2, nxt, segment))
            indices.extend((len(positions) - 1, segment + segments, nxt + segments))
        return _mesh_from_lists(kind, positions, [(0, 0)] * len(positions), indices)
    if kind == "Wedge":
        positions = [
            (-hx, -hy, -hz),
            (hx, -hy, -hz),
            (-hx, -hy, hz),
            (hx, -hy, hz),
            (-hx, hy, hz),
            (hx, hy, hz),
        ]
        indices = [
            0, 2, 1, 1, 2, 3,
            2, 4, 3, 3, 4, 5,
            0, 4, 2,
            1, 3, 5,
            0, 1, 5, 0, 5, 4,
        ]
        return _mesh_from_lists(kind, positions, [(0, 0)] * len(positions), indices)
    if kind == "CornerWedge":
        positions = [
            (-hx, -hy, -hz),
            (hx, -hy, -hz),
            (-hx, -hy, hz),
            (hx, -hy, hz),
            (hx, hy, hz),
        ]
        indices = [0, 2, 1, 1, 2, 3, 1, 3, 4, 0, 1, 4, 0, 4, 2, 2, 4, 3]
        return _mesh_from_lists(kind, positions, [(0, 0)] * len(positions), indices)
    positions = [
        (-hx, -hy, -hz),
        (hx, -hy, -hz),
        (hx, hy, -hz),
        (-hx, hy, -hz),
        (-hx, -hy, hz),
        (hx, -hy, hz),
        (hx, hy, hz),
        (-hx, hy, hz),
    ]
    indices = [
        0, 2, 1, 0, 3, 2,
        4, 5, 6, 4, 6, 7,
        0, 1, 5, 0, 5, 4,
        1, 2, 6, 1, 6, 5,
        2, 3, 7, 2, 7, 6,
        3, 0, 4, 3, 4, 7,
    ]
    return _mesh_from_lists("Block", positions, [(0, 0)] * len(positions), indices)


def _set_input(node, names: tuple[str, ...], value):
    for name in names:
        socket = node.inputs.get(name)
        if socket is not None:
            socket.default_value = value
            return


def _material(name: str, color, material_name: str, transparency: float, image):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    if hasattr(mat, "use_backface_culling"):
        mat.use_backface_culling = False
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    rgb = (color[0], color[1], color[2], 1.0)
    _set_input(bsdf, ("Base Color",), rgb)
    _set_input(bsdf, ("Alpha",), 1.0 - transparency)
    metallic = 1.0 if material_name in ("Metal", "Diamond", "Foil", "CorrodedMetal") else 0.0
    roughness = {
        "Metal": 0.25,
        "Diamond": 0.05,
        "SmoothPlastic": 0.18,
        "Neon": 0.4,
        "Wood": 0.55,
        "Grass": 0.8,
    }.get(material_name, 0.45)
    _set_input(bsdf, ("Metallic",), metallic)
    _set_input(bsdf, ("Roughness",), roughness)
    if material_name == "Neon":
        _set_input(bsdf, ("Emission Color", "Emission"), rgb)
        _set_input(bsdf, ("Emission Strength",), 4.0)
    if image is not None:
        tex = mat.node_tree.nodes.new("ShaderNodeTexImage")
        tex.image = image
        mat.node_tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    if transparency > 0.001:
        if hasattr(mat, "surface_render_method"):
            mat.surface_render_method = "BLENDED"
        if hasattr(mat, "blend_method"):
            mat.blend_method = "BLEND"
    return mat


def _image_from_rgba(name: str, width: int, height: int, rgba: bytes):
    import numpy as np

    image = bpy.data.images.new(name, width, height, alpha=True)
    pixels = np.frombuffer(rgba, dtype=np.uint8).reshape(height, width, 4).astype(np.float32) / 255.0
    pixels = np.flipud(pixels)
    image.pixels.foreach_set(pixels.reshape(-1))
    image.pack()
    return image


def _image_from_bytes(name: str, data: bytes):
    suffix = ".jpg" if data.startswith(b"\xff\xd8") else ".png"
    handle, path = tempfile.mkstemp(suffix=suffix, prefix="ro_render_")
    os.write(handle, data)
    os.close(handle)
    try:
        image = bpy.data.images.load(path)
        image.pack()
        return image
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def _resolve_mesh(part: dict, meshes: dict) -> dict:
    if part.get("meshRef"):
        payload = meshes.get(part["meshRef"])
        if not payload:
            raise RuntimeError(f'Could not read the mesh on "{part.get("name", "part")}".')
        return mesh_import.decode_packed(payload)
    if part.get("meshId"):
        try:
            downloaded = mesh_import.download_mesh(str(part["meshId"]))
        except Exception as exc:
            raise RuntimeError(f'Could not read the mesh on "{part.get("name", "part")}".') from exc
        scale = part.get("meshScale")
        offset = part.get("meshOffset")
        if part.get("fitToSize"):
            return mesh_import.fit_to_size(downloaded, part.get("size") or [1, 1, 1], scale, offset)
        return mesh_import.apply_scale_offset(downloaded, scale, offset)
    raise RuntimeError(f'Could not read the mesh on "{part.get("name", "part")}".')


def _resolve_texture(part: dict, textures: dict):
    if part.get("textureRef"):
        payload = textures.get(part["textureRef"])
        if not payload:
            return None
        import base64

        rgba = base64.b64decode(payload["rgbaBase64"])
        return _image_from_rgba(part["textureRef"], int(payload["width"]), int(payload["height"]), rgba)
    if part.get("textureId"):
        try:
            data = mesh_import.download_asset(str(part["textureId"]))
        except Exception:
            return None
        return _image_from_bytes("tex-" + str(part["textureId"]), data)
    return None


def _add_lights(collection, camera_pos: Vector, target: Vector, up: Vector):
    forward = target - camera_pos
    distance = max(forward.length, 1.0)
    if forward.length > 1e-6:
        forward.normalize()
    else:
        forward = Vector((0.0, -1.0, 0.0))
    right = forward.cross(up)
    if right.length < 1e-6:
        right = Vector((1.0, 0.0, 0.0))
    right.normalize()
    energy = 40.0 * distance * distance
    specs = (
        ("Key", camera_pos + right * distance * 0.45 + up * distance * 0.35, energy, (1.0, 0.97, 0.92), 2.5),
        ("Fill", camera_pos - right * distance * 0.7 + up * distance * 0.1, energy * 0.35, (0.85, 0.9, 1.0), 4.0),
        ("Rim", target - forward * distance * 0.85 + up * distance * 0.45, energy * 0.55, (1.0, 1.0, 1.0), 1.5),
    )
    for name, location, power, color, size in specs:
        light = bpy.data.lights.new(name, "AREA")
        light.energy = power
        light.color = color
        light.size = size
        obj = _link(collection, light, name)
        obj.location = location
        direction = target - location
        obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def _output_path(payload: dict) -> str:
    output = payload.get("output") or {}
    directory = output.get("directory") or ""
    if not directory:
        raise RuntimeError("Set an output folder.")
    os.makedirs(directory, exist_ok=True)
    file_name = payload.get("fileName") or payload.get("subjectName") or "render"
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in file_name).strip("._")
    if safe in ("", ".", ".."):
        safe = "render"
    return os.path.join(directory, safe + ".png")


def _render_png(scene, path: str):
    scene.render.filepath = path
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.color_depth = "8"
    window = bpy.context.window
    screen = bpy.context.screen
    area = next((item for item in (screen.areas if screen else []) if item.type == "VIEW_3D"), None)
    override = {"scene": scene}
    if window:
        override["window"] = window
    if area:
        override["area"] = area
        region = next((item for item in area.regions if item.type == "WINDOW"), None)
        if region:
            override["region"] = region
    try:
        with bpy.context.temp_override(**override):
            bpy.ops.render.render(write_still=True)
    except Exception:
        if window:
            window.scene = scene
        bpy.ops.render.render(write_still=True)


def run(kind: str, payload: dict, meshes: dict, textures: dict) -> dict:
    preview = kind == "preview"
    window = bpy.context.window
    previous = window.scene if window else bpy.context.scene
    scene = bpy.data.scenes.new(_CREATED)
    collection = bpy.data.collections.new(_CREATED)
    created_images = []
    handle = None
    temp_path = None
    try:
        if window:
            window.scene = scene
        scene.collection.children.link(collection)
        output = payload.get("output") or {}
        width = max(16, int(output.get("width") or 512))
        height = max(16, int(output.get("height") or 512))
        scene.render.resolution_x = width
        scene.render.resolution_y = height
        scene.render.resolution_percentage = 100
        scene.render.film_transparent = True
        scene.render.use_compositing = False
        _use_engine(scene, preview)
        if scene.render.engine == "CYCLES":
            scene.cycles.samples = 32 if preview else 128
            try:
                scene.cycles.use_denoising = True
            except Exception:
                pass
        else:
            eevee = getattr(scene, "eevee", None)
            if eevee and hasattr(eevee, "taa_render_samples"):
                eevee.taa_render_samples = 16 if preview else 64

        camera_info = payload.get("camera") or {}
        camera_pos = _roblox_to_blender(camera_info.get("position") or (0, 2, 14))
        target = _roblox_to_blender(camera_info.get("target") or (0, 2, 0))
        up = _roblox_to_blender(camera_info.get("up") or (0, 1, 0))
        if up.length < 1e-6:
            up = Vector((0.0, 0.0, 1.0))
        up.normalize()
        camera_data = bpy.data.cameras.new("Camera")
        camera_data.sensor_fit = "VERTICAL"
        camera_data.angle = math.radians(float(camera_info.get("fov") or 30))
        camera_data.clip_start = 0.01
        camera_data.clip_end = 100000
        camera = _link(collection, camera_data, "Camera")
        camera.matrix_world = _camera_matrix(camera_pos, target, up)
        scene.camera = camera
        _add_lights(collection, camera_pos, target, up)

        for index, part in enumerate(payload.get("parts") or []):
            kind_name = part.get("class") or "Block"
            if kind_name == "Mesh":
                geometry = _resolve_mesh(part, meshes)
                mesh = _mesh_from_lists(part.get("name") or f"Part{index}", geometry["positions"], geometry["uvs"], geometry["indices"])
            else:
                mesh = _primitive(kind_name, part.get("size") or [1, 1, 1])
            image = _resolve_texture(part, textures)
            if image is not None:
                created_images.append(image)
            mat = _material(
                part.get("name") or f"Part{index}",
                part.get("color") or [1, 1, 1],
                part.get("material") or "Plastic",
                float(part.get("transparency") or 0),
                image,
            )
            mesh.materials.append(mat)
            obj = _link(collection, mesh, part.get("name") or f"Part{index}")
            components = part.get("cframe")
            if components and len(components) == 12:
                obj.matrix_world = _matrix_from_cframe(components)

        handle, temp_path = tempfile.mkstemp(suffix=".png", prefix="ro_render_")
        os.close(handle)
        handle = None
        _render_png(scene, temp_path)
        with open(temp_path, "rb") as rendered:
            png = composite_png(rendered.read(), payload.get("effects") or {})
        if preview:
            from .image_io import decode_png

            out_w, out_h, rgba = decode_png(png)
            return {"width": out_w, "height": out_h, "rgba": rgba}
        destination = _output_path(payload)
        with open(destination, "wb") as saved:
            saved.write(png)
        return {"path": destination}
    finally:
        if handle is not None:
            os.close(handle)
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
        if window:
            window.scene = previous
        try:
            _cleanup_scene(scene, collection, created_images)
        except Exception:
            import traceback

            traceback.print_exc()


def _cleanup_scene(scene, collection, created_images):
    objects = list(collection.objects)
    datablocks = [obj.data for obj in objects]
    for obj in objects:
        bpy.data.objects.remove(obj, do_unlink=True)
    for block in datablocks:
        if block is None:
            continue
        if isinstance(block, bpy.types.Mesh):
            materials = [mat for mat in block.materials if mat]
            if block.users == 0:
                bpy.data.meshes.remove(block)
            for mat in materials:
                if mat.users == 0:
                    bpy.data.materials.remove(mat)
        elif block.users == 0 and isinstance(block, bpy.types.Camera):
            bpy.data.cameras.remove(block)
        elif block.users == 0 and isinstance(block, bpy.types.Light):
            bpy.data.lights.remove(block)
    for image in created_images:
        if image.users == 0:
            bpy.data.images.remove(image)
    try:
        scene.collection.children.unlink(collection)
    except Exception:
        pass
    bpy.data.collections.remove(collection)
    bpy.data.scenes.remove(scene)
