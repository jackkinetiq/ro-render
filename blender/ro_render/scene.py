"""Build a subject in its own scene, render a cutout, and composite the effects."""

import math
import os
import tempfile

import bpy
from mathutils import Matrix, Vector

from . import mesh_import
from .compositor import (
    apply_fog,
    bloom_linear,
    blur_radius_px,
    blur_straight,
    composite,
    focus_blur_radius,
    grade,
    rgba_bytes,
    studio_environment,
    sun_rays_linear,
    tonemap_display,
)
from .image_io import encode_png

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


def _srgb_channel(value: float) -> float:
    value = min(max(float(value), 0.0), 1.0)
    if value <= 0.04045:
        return value / 12.92
    return ((value + 0.055) / 1.055) ** 2.4


def _linear_color(color, alpha: float = 1.0):
    channels = list(color or (1, 1, 1))
    while len(channels) < 3:
        channels.append(1)
    return (
        _srgb_channel(channels[0]),
        _srgb_channel(channels[1]),
        _srgb_channel(channels[2]),
        alpha,
    )


def _material(name: str, color, material_name: str, transparency: float, image, specular: float = 0.5):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    if hasattr(mat, "use_backface_culling"):
        mat.use_backface_culling = False
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    rgb = _linear_color(color)
    _set_input(bsdf, ("Base Color",), rgb)
    _set_input(bsdf, ("Alpha",), 1.0 - transparency)
    metallic = 1.0 if material_name in ("Metal", "Diamond", "Foil", "CorrodedMetal") else 0.0
    roughness = {
        "Metal": 0.25,
        "Diamond": 0.05,
        "SmoothPlastic": 0.38,
        "Neon": 0.4,
        "Wood": 0.55,
        "Grass": 0.8,
    }.get(material_name, 0.45)
    _set_input(bsdf, ("Metallic",), metallic)
    _set_input(bsdf, ("Roughness",), roughness)
    _set_input(bsdf, ("Specular IOR Level", "Specular"), max(0.0, min(float(specular), 1.0)))
    if material_name == "Neon":
        # Studio Neon is unlit. A lit base color lets the sun turn #FF5438 into grey.
        _set_input(bsdf, ("Base Color",), (0.0, 0.0, 0.0, 1.0))
        _set_input(bsdf, ("Emission Color", "Emission"), rgb)
        # Above about 3, the green and blue of #FF5438 clip and the color turns yellow-white.
        _set_input(bsdf, ("Emission Strength",), 2.8)
        _set_input(bsdf, ("Roughness",), 1.0)
        _set_input(bsdf, ("Specular IOR Level", "Specular"), 0.0)
    if image is not None:
        tex = mat.node_tree.nodes.new("ShaderNodeTexImage")
        tex.image = image
        if material_name == "Neon":
            tint = mat.node_tree.nodes.new("ShaderNodeVectorMath")
            tint.operation = "MULTIPLY"
            tint.inputs[1].default_value = rgb[:3]
            mat.node_tree.links.new(tex.outputs["Color"], tint.inputs[0])
            emission = bsdf.inputs.get("Emission Color") or bsdf.inputs.get("Emission")
            if emission is not None:
                mat.node_tree.links.new(tint.outputs[0], emission)
        else:
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
    encoded = pixels[..., :3]
    linear = np.where(encoded <= 0.04045, encoded / 12.92, ((encoded + 0.055) / 1.055) ** 2.4)
    pixels = np.concatenate((linear, pixels[..., 3:4]), axis=-1)
    pixels = np.flipud(pixels)
    try:
        image.colorspace_settings.name = "Non-Color"
    except Exception:
        pass
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


class MeshReadError(Exception):
    def __init__(self, part_name: str, reason: str):
        self.part_name = part_name
        self.reason = reason
        super().__init__(reason)


def _resolve_mesh(part: dict, meshes: dict) -> dict:
    name = part.get("name") or "part"
    try:
        if part.get("meshRef"):
            payload = meshes.get(part["meshRef"])
            if not payload:
                raise RuntimeError("The mesh was not uploaded.")
            return mesh_import.decode_packed(payload)
        if part.get("meshId"):
            downloaded = mesh_import.download_mesh(str(part["meshId"]))
            scale = part.get("meshScale")
            offset = part.get("meshOffset")
            if part.get("fitToSize"):
                return mesh_import.fit_to_size(downloaded, part.get("size") or [1, 1, 1], scale, offset)
            return mesh_import.apply_scale_offset(downloaded, scale, offset)
        raise RuntimeError("The mesh has no geometry.")
    except MeshReadError:
        raise
    except Exception as exc:
        reason = str(exc).strip().splitlines()
        raise MeshReadError(name, reason[-1] if reason else "Could not read the mesh.") from exc


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


def _match_studio_color(scene, lighting: dict):
    # AgX lifts blacks and turns saturated reds grey. Studio's picture is sRGB.
    view = scene.view_settings.bl_rna.properties["view_transform"].enum_items
    available = {item.identifier for item in view}
    for name in ("Standard", "Khronos PBR Neutral", "Raw"):
        if name in available:
            scene.view_settings.view_transform = name
            break
    look = scene.view_settings.bl_rna.properties["look"].enum_items
    if any(item.identifier == "None" for item in look):
        scene.view_settings.look = "None"
    scene.view_settings.exposure = float(lighting.get("exposure") or 0)
    scene.view_settings.gamma = 1.0


def _studio_world(lighting: dict):
    # No skybox download. The fill color comes from the time of day, atmosphere,
    # and outdoor ambient. Strength is calibrated so dark colors stay dark.
    sky, strength, _sun_energy = studio_environment(lighting)
    world = bpy.data.worlds.new("ro_render_world")
    world.use_nodes = True
    background = world.node_tree.nodes.get("Background")
    if background is not None:
        _set_input(background, ("Color",), _linear_color(sky))
        _set_input(background, ("Strength",), max(0.0, strength))
    return world


def _add_lights(collection, lighting: dict):
    sun_direction = _roblox_to_blender(lighting.get("sunDirection") or (0, 1, 0))
    if sun_direction.length < 1e-6:
        sun_direction = Vector((0.0, 0.0, 1.0))
    sun_direction.normalize()
    light = bpy.data.lights.new("Sun", "SUN")
    _sky, _strength, sun_energy = studio_environment(lighting)
    light.energy = sun_energy
    light.color = (1.0, 1.0, 1.0)
    angular = float(lighting.get("sunAngularSize") or 11)
    softness = float(lighting.get("shadowSoftness") or 0)
    light.angle = math.radians(max(0.5, min(angular + softness * 8.0, 40.0)))
    if hasattr(light, "use_shadow"):
        light.use_shadow = lighting.get("globalShadows") is not False
    obj = _link(collection, light, "Sun")
    obj.rotation_euler = (-sun_direction).to_track_quat("-Z", "Y").to_euler()


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


def _render_still(scene, path: str):
    scene.render.filepath = path
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


def _texture_payload(textures: dict, ref):
    if not ref:
        return None
    payload = textures.get(ref)
    if not payload:
        return None
    import base64

    try:
        rgba = base64.b64decode(payload["rgbaBase64"])
        width = int(payload["width"])
        height = int(payload["height"])
    except Exception:
        return None
    if len(rgba) != width * height * 4:
        return None
    return rgba, width, height


def _soft_disk_image(created_images: list):
    import numpy as np

    size = 64
    y, x = np.mgrid[0:size, 0:size]
    distance = np.sqrt((x + 0.5 - size / 2) ** 2 + (y + 0.5 - size / 2) ** 2) / (size / 2)
    alpha = np.clip(1.0 - distance, 0.0, 1.0) ** 2
    rgba = np.zeros((size, size, 4), dtype=np.uint8)
    rgba[..., 0:3] = 255
    rgba[..., 3] = np.clip(alpha * 255.0 + 0.5, 0, 255).astype(np.uint8)
    image = _image_from_rgba("ro_render_particle", size, size, rgba.tobytes())
    created_images.append(image)
    return image


def _card_mesh(size: float):
    half = max(float(size), 1e-3) / 2
    positions = [(-half, -half, 0), (half, -half, 0), (half, half, 0), (-half, half, 0)]
    uvs = [(0, 1), (1, 1), (1, 0), (0, 0)]
    indices = [0, 1, 2, 0, 2, 3, 0, 2, 1, 0, 3, 2]
    return _mesh_from_lists("Particle", positions, uvs, indices)


def _sprite_material(name: str, color, image, light_emission: float, brightness: float):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    if hasattr(mat, "use_backface_culling"):
        mat.use_backface_culling = False
    if hasattr(mat, "surface_render_method"):
        mat.surface_render_method = "BLENDED"
    if hasattr(mat, "blend_method"):
        mat.blend_method = "BLEND"
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    output = nodes.get("Material Output")
    rgb = _linear_color(color)
    emission_amount = max(0.0, min(float(light_emission), 1.0))
    if emission_amount >= 0.5:
        emission = nodes.new("ShaderNodeEmission")
        strength = min(16.0, max(0.0, float(brightness)) * (1.0 + emission_amount * 7.0))
        _set_input(emission, ("Color",), rgb)
        _set_input(emission, ("Strength",), strength)
        transparent = nodes.new("ShaderNodeBsdfTransparent")
        mix = nodes.new("ShaderNodeMixShader")
        if image is not None:
            tex = nodes.new("ShaderNodeTexImage")
            tex.image = image
            tint = nodes.new("ShaderNodeVectorMath")
            tint.operation = "MULTIPLY"
            tint.inputs[1].default_value = rgb[:3]
            links.new(tex.outputs["Color"], tint.inputs[0])
            links.new(tint.outputs[0], emission.inputs[0])
            links.new(tex.outputs["Alpha"], mix.inputs[0])
        else:
            mix.inputs[0].default_value = 1.0
        links.new(transparent.outputs[0], mix.inputs[1])
        links.new(emission.outputs[0], mix.inputs[2])
        surface = output.inputs["Surface"]
        for link in list(surface.links):
            links.remove(link)
        links.new(mix.outputs[0], surface)
        return mat
    bsdf = nodes.get("Principled BSDF")
    _set_input(bsdf, ("Base Color",), rgb)
    _set_input(bsdf, ("Roughness",), 0.55)
    _set_input(bsdf, ("Specular IOR Level", "Specular"), 0.1)
    _set_input(bsdf, ("Emission Color", "Emission"), rgb)
    _set_input(bsdf, ("Emission Strength",), max(0.0, float(brightness)) * emission_amount * 4.0)
    if image is not None:
        tex = nodes.new("ShaderNodeTexImage")
        tex.image = image
        links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
        alpha = bsdf.inputs.get("Alpha")
        if alpha is not None:
            links.new(tex.outputs["Alpha"], alpha)
    return mat


def _add_particles(collection, particles: list, textures: dict, camera, created_images: list):
    if not particles:
        return
    right = camera.matrix_world.col[0].xyz.normalized()
    up = camera.matrix_world.col[1].xyz.normalized()
    toward_camera = camera.matrix_world.col[2].xyz.normalized()
    soft = None
    for index, particle in enumerate(particles):
        image = None
        decoded = _texture_payload(textures, particle.get("textureRef"))
        if decoded is not None:
            rgba, width, height = decoded
            image = _image_from_rgba(particle.get("textureRef") or f"particle-{index}", width, height, rgba)
            created_images.append(image)
        else:
            if soft is None:
                soft = _soft_disk_image(created_images)
            image = soft
        size = max(float(particle.get("size") or 1), 0.05)
        speed = max(float(particle.get("speed") or 0), 0.0)
        life = max(float(particle.get("life") or 0), 0.0)
        radius = max(size * 0.35, min(speed * life * 0.2, size * 3.0))
        count = max(1, min(int(particle.get("count") or 1), 16))
        origin = _roblox_to_blender(particle.get("position") or (0, 0, 0))
        material = _sprite_material(
            particle.get("name") or f"Particle{index}",
            particle.get("color") or [1, 1, 1],
            image,
            float(particle.get("lightEmission") or 0),
            float(particle.get("brightness") if particle.get("brightness") is not None else 1),
        )
        for card in range(count):
            mesh = _card_mesh(size * (0.75 + (card % 5) * 0.1))
            mesh.materials.append(material)
            obj = _link(collection, mesh, particle.get("name") or f"Particle{index}")
            try:
                obj.visible_shadow = False
            except Exception:
                pass
            if count == 1:
                offset = Vector((0.0, 0.0, 0.0))
            else:
                angle = card * 2.399963
                ring = radius * math.sqrt((card + 0.5) / count)
                offset = right * math.cos(angle) * ring + up * math.sin(angle) * ring
            position = origin + offset + toward_camera * (0.04 * (card + 1))
            obj.matrix_world = Matrix((
                (right.x, up.x, toward_camera.x, position.x),
                (right.y, up.y, toward_camera.y, position.y),
                (right.z, up.z, toward_camera.z, position.z),
                (0.0, 0.0, 0.0, 1.0),
            ))


def _load_linear_exr(path: str):
    import numpy as np

    image = bpy.data.images.load(path, check_existing=False)
    try:
        # OpenEXR is already scene linear. Retagging the colorspace would encode it again.
        width, height = int(image.size[0]), int(image.size[1])
        raw = np.empty(width * height * 4, dtype=np.float32)
        image.pixels.foreach_get(raw)
        picture = np.flipud(raw.reshape(height, width, 4))
        associated = getattr(image, "alpha_mode", "STRAIGHT") == "PREMUL"
        return picture, associated
    finally:
        bpy.data.images.remove(image)


def _straighten(picture, associated: bool):
    import numpy as np

    if not associated:
        return picture
    alpha = picture[..., 3:4]
    out = picture.copy()
    out[..., :3] = np.where(alpha > 1e-4, picture[..., :3] / np.maximum(alpha, 1e-4), 0.0)
    return out


def _render_linear(scene):
    """Render a scene-linear cutout so bloom can see light above 1."""
    handle, path = tempfile.mkstemp(suffix=".exr", prefix="ro_render_")
    os.close(handle)
    try:
        scene.render.filepath = path
        scene.render.image_settings.file_format = "OPEN_EXR"
        scene.render.image_settings.color_mode = "RGBA"
        scene.render.image_settings.color_depth = "16"
        _render_still(scene, path)
        return _load_linear_exr(path)
    finally:
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass


def _sun_screen(scene, camera, lighting: dict):
    direction = _roblox_to_blender(lighting.get("sunDirection") or (0, 1, 0))
    if direction.length < 1e-6:
        return None
    from bpy_extras.object_utils import world_to_camera_view

    point = camera.matrix_world.translation + direction.normalized() * 1000.0
    ndc = world_to_camera_view(scene, camera, point)
    if ndc.z <= 0:
        return None
    return [float(ndc.x), float(ndc.y)]


def _finish_picture(picture, lighting: dict, effects: dict, camera_distance: float) -> bytes:
    picture = bloom_linear(picture, lighting.get("bloom"))
    picture = sun_rays_linear(picture, lighting.get("sunRays"), lighting.get("sunScreen"))
    picture = apply_fog(picture, lighting.get("fog"), camera_distance)
    display = tonemap_display(picture, float(lighting.get("exposure") or 0))
    height, width = display.shape[:2]
    long_side = max(width, height)
    radius = focus_blur_radius(camera_distance, lighting.get("depthOfField"), long_side)
    radius = max(radius, blur_radius_px(lighting.get("blur"), long_side))
    display = blur_straight(display, radius)
    raw = rgba_bytes(display)
    graded = grade(raw, width, height, lighting.get("colorCorrection"))
    return encode_png(width, height, composite(graded, width, height, effects))


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
        lighting = payload.get("lighting") or {}
        _match_studio_color(scene, lighting)
        scene.world = _studio_world(lighting)
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
        _add_lights(collection, lighting)
        try:
            lighting["sunScreen"] = _sun_screen(scene, camera, lighting)
        except Exception:
            lighting["sunScreen"] = None
        camera_distance = (camera_pos - target).length

        warnings = []
        for index, part in enumerate(payload.get("parts") or []):
            kind_name = part.get("class") or "Block"
            if kind_name == "Mesh":
                try:
                    geometry = _resolve_mesh(part, meshes)
                    mesh = _mesh_from_lists(part.get("name") or f"Part{index}", geometry["positions"], geometry["uvs"], geometry["indices"])
                except MeshReadError as exc:
                    warnings.append(f'Could not read the mesh on "{exc.part_name}". {exc.reason} It was sent as a box.')
                    mesh = _primitive("Block", part.get("size") or [1, 1, 1])
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
                0.22 * float(lighting.get("environmentSpecular") if lighting.get("environmentSpecular") is not None else 1),
            )
            mesh.materials.append(mat)
            obj = _link(collection, mesh, part.get("name") or f"Part{index}")
            components = part.get("cframe")
            if components and len(components) == 12:
                obj.matrix_world = _matrix_from_cframe(components)
        _add_particles(collection, payload.get("particles") or [], textures, camera, created_images)

        try:
            picture, associated = _render_linear(scene)
            picture = _straighten(picture, associated)
            png = _finish_picture(picture, lighting, payload.get("effects") or {}, camera_distance)
        except Exception:
            warnings.append("Bloom was skipped because the high-range render could not be read.")
            handle, temp_path = tempfile.mkstemp(suffix=".png", prefix="ro_render_")
            os.close(handle)
            handle = None
            scene.render.image_settings.file_format = "PNG"
            scene.render.image_settings.color_mode = "RGBA"
            scene.render.image_settings.color_depth = "8"
            _render_still(scene, temp_path)
            with open(temp_path, "rb") as rendered:
                from .compositor import composite_png

                png = composite_png(rendered.read(), payload.get("effects") or {}, lighting.get("colorCorrection"))
        if preview:
            from .image_io import decode_png

            out_w, out_h, rgba = decode_png(png)
            return {"width": out_w, "height": out_h, "rgba": rgba, "warnings": warnings}
        destination = _output_path(payload)
        with open(destination, "wb") as saved:
            saved.write(png)
        return {"path": destination, "warnings": warnings}
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
    world = scene.world
    if world is not None and world.name == "ro_render_world":
        scene.world = None
        if world.users == 0:
            bpy.data.worlds.remove(world)
    for image in created_images:
        if image.users == 0:
            bpy.data.images.remove(image)
    try:
        scene.collection.children.unlink(collection)
    except Exception:
        pass
    bpy.data.collections.remove(collection)
    bpy.data.scenes.remove(scene)
