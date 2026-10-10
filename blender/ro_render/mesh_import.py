"""Roblox geometry: packed buffers from Studio, and .mesh files from the asset host."""

import json
import re
import struct
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


def _parse_binary(body: bytes) -> dict:
    if len(body) < 12:
        raise ValueError("Could not parse the mesh file.")
    header_size, vertex_size, face_size, vertex_count, face_count = struct.unpack_from("<HBBII", body, 0)
    if header_size < 12 or vertex_size < 12 or face_size < 12:
        raise ValueError("Could not parse the mesh file.")
    start = header_size
    positions = []
    uvs = []
    for index in range(vertex_count):
        offset = start + index * vertex_size
        px, py, pz = struct.unpack_from("<fff", body, offset)
        positions.append((px, py, pz))
        if vertex_size >= 32:
            u, v = struct.unpack_from("<ff", body, offset + 24)
            uvs.append((u, v))
        else:
            uvs.append((0.0, 0.0))
    face_start = start + vertex_count * vertex_size
    indices = []
    for index in range(face_count):
        offset = face_start + index * face_size
        indices.extend(struct.unpack_from("<III", body, offset))
    if not positions or not indices:
        raise ValueError("Could not parse the mesh file.")
    return {"positions": positions, "uvs": uvs, "indices": indices}


def parse_mesh_bytes(data: bytes) -> dict:
    if data.startswith(b"version "):
        newline = data.find(b"\n")
        version = data[:newline].decode("ascii", "replace").strip()
        body = data[newline + 1 :]
        if version == "version 1.00":
            return _parse_v1(body.decode("utf-8", "replace"))
        if version.startswith("version "):
            return _parse_binary(body)
    if data[:1] == b"{" or data[:1] == b"[":
        raise ValueError("Asset host returned a document instead of a mesh.")
    raise ValueError("Could not parse the mesh file.")


def _fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "ro-render"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def download_asset(asset_id: str) -> bytes:
    data = _fetch(_ASSET.format(asset_id))
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
