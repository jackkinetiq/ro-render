"""Roblox geometry: packed buffers from Studio, and .mesh files from the asset host."""

import json
import re
import struct
import urllib.error
import urllib.request

_ASSET = "https://assetdelivery.roblox.com/v1/asset/?id={}"


def decode_packed(payload: dict) -> dict:
    import base64

    import numpy as np

    positions = np.frombuffer(base64.b64decode(payload["positions"]), dtype="<f4").reshape(-1, 3)
    uvs = np.frombuffer(base64.b64decode(payload.get("uvs") or b""), dtype="<f4")
    if uvs.size == 0:
        uvs = np.zeros((len(positions), 2), dtype=np.float32)
    else:
        uvs = uvs.reshape(-1, 2)
    indices = np.frombuffer(base64.b64decode(payload["indices"]), dtype="<u4")
    return {"positions": positions, "uvs": uvs, "indices": indices}


def _parse_v1(text: str) -> dict:
    numbers = [float(item) for item in re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", text)]
    stride = None
    # A leading face count sits in front of either 8-float (uv.xy) or 9-float (uv.xyz) vertices.
    for candidate in (9, 8):
        if len(numbers) >= candidate * 3 and (len(numbers) - 1) % candidate == 0:
            numbers = numbers[1:]
            stride = candidate
            break
        if len(numbers) >= candidate * 3 and len(numbers) % candidate == 0:
            stride = candidate
            break
    if stride is None:
        raise ValueError("Could not parse the mesh file.")
    verts = len(numbers) // stride
    positions = []
    uvs = []
    for index in range(verts):
        base = index * stride
        positions.append(tuple(numbers[base : base + 3]))
        uvs.append(tuple(numbers[base + 6 : base + 8]))
    return {"positions": positions, "uvs": uvs, "indices": list(range(verts))}


def _version_major(version: str) -> int:
    number = version.replace("version", "").strip()
    return int(number.split(".", 1)[0])


def _read_vertices(body: bytes, start: int, count: int, stride: int):
    if count < 0 or stride < 12 or start + count * stride > len(body):
        raise ValueError("Could not parse the mesh file.")
    positions = []
    uvs = []
    for index in range(count):
        offset = start + index * stride
        positions.append(struct.unpack_from("<fff", body, offset))
        if stride >= 32:
            uvs.append(struct.unpack_from("<ff", body, offset + 24))
        else:
            uvs.append((0.0, 0.0))
    return positions, uvs, start + count * stride


def _read_faces(body: bytes, start: int, face_count: int, lod_count: int = 0):
    if face_count <= 0 or start + face_count * 12 > len(body):
        raise ValueError("Could not parse the mesh file.")
    indices = []
    for index in range(face_count):
        indices.extend(struct.unpack_from("<III", body, start + index * 12))
    cursor = start + face_count * 12
    if lod_count >= 2 and cursor + lod_count * 4 <= len(body):
        lods = struct.unpack_from("<" + "I" * lod_count, body, cursor)
        begin = int(lods[0])
        end = int(lods[1])
        if 0 <= begin < end <= face_count:
            indices = indices[begin * 3 : end * 3]
    if not indices:
        raise ValueError("Could not parse the mesh file.")
    return indices


def _mesh(positions, uvs, indices) -> dict:
    if not positions or not indices:
        raise ValueError("Could not parse the mesh file.")
    return {"positions": positions, "uvs": uvs, "indices": indices}


def _parse_v2(body: bytes, major: int) -> dict:
    if major >= 3:
        header_size, vertex_size, _face_size, _lod_size, lod_count, vertex_count, face_count = struct.unpack_from(
            "<HBBHHII", body, 0
        )
    else:
        header_size, vertex_size, _face_size, vertex_count, face_count = struct.unpack_from("<HBBII", body, 0)
        lod_count = 0
    if header_size < 12 or vertex_size < 12:
        raise ValueError("Could not parse the mesh file.")
    positions, uvs, cursor = _read_vertices(body, header_size, vertex_count, vertex_size)
    indices = _read_faces(body, cursor, face_count, lod_count)
    return _mesh(positions, uvs, indices)


def _parse_v4(body: bytes) -> dict:
    header_size = struct.unpack_from("<H", body, 0)[0]
    if header_size < 24 or header_size > len(body):
        raise ValueError("Could not parse the mesh file.")
    _lod_type, vertex_count, face_count, lod_count, bone_count = struct.unpack_from("<HIIHH", body, 2)
    positions, uvs, cursor = _read_vertices(body, header_size, vertex_count, 40)
    if bone_count > 0:
        cursor += vertex_count * 8
    indices = _read_faces(body, cursor, face_count, lod_count)
    return _mesh(positions, uvs, indices)


def _parse_chunks(body: bytes) -> dict:
    position = 0
    core = None
    while position + 16 <= len(body):
        name = body[position : position + 8].split(b"\x00", 1)[0]
        chunk_version, size = struct.unpack_from("<II", body, position + 8)
        data_start = position + 16
        data_end = data_start + size
        if data_end > len(body):
            break
        data = body[data_start:data_end]
        position = data_end
        if name == b"COREMESH":
            core = (chunk_version, data)
    if core is None:
        raise ValueError("Could not parse the mesh file.")
    chunk_version, data = core
    if chunk_version != 1:
        raise ValueError("This mesh is compressed, so Studio has to be allowed to read it.")
    vertex_count = struct.unpack_from("<I", data, 0)[0]
    positions, uvs, cursor = _read_vertices(data, 4, vertex_count, 40)
    face_count = struct.unpack_from("<I", data, cursor)[0]
    indices = _read_faces(data, cursor + 4, face_count, 0)
    return _mesh(positions, uvs, indices)


def parse_mesh_bytes(data: bytes) -> dict:
    if data.startswith(b"version "):
        newline = data.find(b"\n")
        version = data[:newline].decode("ascii", "replace").strip()
        body = data[newline + 1 :]
        major = _version_major(version)
        if major == 1:
            mesh = _parse_v1(body.decode("utf-8", "replace"))
            if version == "version 1.00":
                mesh["positions"] = [(p[0] * 0.5, p[1] * 0.5, p[2] * 0.5) for p in mesh["positions"]]
            mesh["uvs"] = [(u, 1.0 - v) for u, v in mesh["uvs"]]
            return mesh
        if major in (2, 3):
            return _parse_v2(body, major)
        if major in (4, 5):
            return _parse_v4(body)
        if major >= 6:
            return _parse_chunks(body)
    if data[:1] in (b"{", b"["):
        raise ValueError("Asset host returned a document instead of a mesh.")
    raise ValueError("Could not parse the mesh file.")


def _fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "ro-render"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def download_asset(asset_id: str) -> bytes:
    try:
        data = _fetch(_ASSET.format(asset_id))
    except urllib.error.HTTPError as exc:
        detail = exc.read(200).decode("utf-8", "replace")
        if exc.code == 401 or "Authentication required" in detail:
            raise RuntimeError("Studio is not allowed to read this mesh, and it is not public.") from exc
        raise RuntimeError(f"Asset host returned HTTP {exc.code}.") from exc
    if data[:1] in (b"{", b"["):
        try:
            payload = json.loads(data.decode("utf-8"))
        except json.JSONDecodeError:
            payload = None
        location = payload.get("location") if isinstance(payload, dict) else None
        if location:
            data = _fetch(location)
    return data


def download_mesh(asset_id: str) -> dict:
    return parse_mesh_bytes(download_asset(asset_id))


def fit_to_size(mesh: dict, size: list, scale=None, offset=None) -> dict:
    """Center a downloaded mesh on the part and stretch it to Size."""
    positions = mesh["positions"]
    if len(positions) == 0:
        return mesh
    xs = [p[0] for p in positions]
    ys = [p[1] for p in positions]
    zs = [p[2] for p in positions]
    center = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, (min(zs) + max(zs)) / 2)
    extent = (max(max(xs) - min(xs), 1e-5), max(max(ys) - min(ys), 1e-5), max(max(zs) - min(zs), 1e-5))
    mesh_scale = scale or (1, 1, 1)
    mesh_offset = offset or (0, 0, 0)
    fitted = []
    for position in positions:
        fitted.append((
            (position[0] - center[0]) / extent[0] * size[0] * mesh_scale[0] + mesh_offset[0],
            (position[1] - center[1]) / extent[1] * size[1] * mesh_scale[1] + mesh_offset[1],
            (position[2] - center[2]) / extent[2] * size[2] * mesh_scale[2] + mesh_offset[2],
        ))
    return {"positions": fitted, "uvs": mesh["uvs"], "indices": mesh["indices"]}


def apply_scale_offset(mesh: dict, scale, offset) -> dict:
    scale = scale or (1, 1, 1)
    offset = offset or (0, 0, 0)
    positions = [
        (p[0] * scale[0] + offset[0], p[1] * scale[1] + offset[1], p[2] * scale[2] + offset[2]) for p in mesh["positions"]
    ]
    return {"positions": positions, "uvs": mesh["uvs"], "indices": mesh["indices"]}
