"""Validation helpers for color data in glTF and GLB conversion output."""
import json
import struct
from pathlib import Path


def read_gltf_document(path: Path) -> dict:
    """Read the JSON document from a .gltf or version 2 .glb file."""
    if path.suffix.lower() == ".gltf":
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Could not read converted glTF JSON: {exc}") from exc

    try:
        data = path.read_bytes()
    except OSError as exc:
        raise RuntimeError(f"Could not read converted GLB: {exc}") from exc

    if len(data) < 20:
        raise RuntimeError("The converter produced an incomplete GLB file.")

    magic, version, declared_length = struct.unpack_from("<4sII", data)
    if magic != b"glTF" or version != 2 or declared_length != len(data):
        raise RuntimeError("The converter produced an invalid GLB 2.0 file.")

    offset = 12
    while offset + 8 <= len(data):
        chunk_length, chunk_type = struct.unpack_from("<II", data, offset)
        offset += 8
        chunk_end = offset + chunk_length
        if chunk_end > len(data):
            raise RuntimeError("The converter produced a truncated GLB chunk.")
        if chunk_type == 0x4E4F534A:
            try:
                return json.loads(data[offset:chunk_end].decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise RuntimeError(f"Could not read converted GLB JSON: {exc}") from exc
        offset = chunk_end

    raise RuntimeError("The converter produced a GLB without a JSON document.")


def has_color_data(document: dict) -> bool:
    """Check whether a mesh uses vertex colors or a visibly colored material."""
    materials = document.get("materials", [])
    for mesh in document.get("meshes", []):
        for primitive in mesh.get("primitives", []):
            if "COLOR_0" in primitive.get("attributes", {}):
                return True

            material_index = primitive.get("material")
            if not isinstance(material_index, int) or not 0 <= material_index < len(materials):
                continue

            material = materials[material_index]
            pbr = material.get("pbrMetallicRoughness", {})
            if pbr.get("baseColorTexture") is not None:
                return True

            base_color = pbr.get("baseColorFactor", [1, 1, 1, 1])
            if (
                isinstance(base_color, list)
                and len(base_color) >= 3
                and any(abs(component - 1) > 1e-6 for component in base_color[:3])
            ):
                return True

            emissive = material.get("emissiveFactor", [0, 0, 0])
            if (
                isinstance(emissive, list)
                and len(emissive) >= 3
                and any(abs(component) > 1e-6 for component in emissive[:3])
            ):
                return True
    return False


def require_color_data(path: Path) -> None:
    """Reject conversions that would otherwise silently display as white."""
    if not has_color_data(read_gltf_document(path)):
        raise RuntimeError(
            "The conversion produced geometry without material colors or vertex colors. "
            "The original JT colors could not be preserved, so an uncolored model was not returned."
        )
