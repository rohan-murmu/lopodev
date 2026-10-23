"""Report the actual installed Blender API surface used by this pipeline."""

from __future__ import annotations

import json
import os
import struct
import sys
import tempfile

import addon_utils
import bpy


def main() -> int:
    report: dict = {
        "blender_version": bpy.app.version_string,
        "python_version": sys.version.split()[0],
        "executable": bpy.app.binary_path,
        "gltf_addon": None,
        "gltf_operator": False,
        "action_slots": None,
        "exporter_defaults": {},
    }

    enabled, _ = addon_utils.check("io_scene_gltf2")
    report["gltf_addon"] = bool(enabled)

    probe_action = bpy.data.actions.new("__api_report_probe__")
    report["action_slots"] = hasattr(probe_action, "slots")
    bpy.data.actions.remove(probe_action)

    if hasattr(bpy.ops.export_scene, "gltf"):
        report["gltf_operator"] = True
        properties = bpy.ops.export_scene.gltf.get_rna_type().properties
        for name in (
            "export_format",
            "use_selection",
            "export_apply",
            "export_yup",
            "export_materials",
            "export_extras",
            "export_animations",
            "export_animation_mode",
            "export_force_sampling",
            "export_nla_strips",
            "export_frame_range",
            "export_skins",
            "export_def_bones",
        ):
            if name in properties.keys():
                prop = properties[name]
                try:
                    default = prop.default
                except (AttributeError, TypeError):
                    default = None
                report["exporter_defaults"][name] = default

    if report["gltf_operator"]:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.mesh.primitive_cube_add(size=1.0)
        with tempfile.TemporaryDirectory(prefix="gltf_probe_") as tmp:
            probe = os.path.join(tmp, "probe.glb")
            bpy.ops.export_scene.gltf(filepath=probe, export_format="GLB")
            with open(probe, "rb") as handle:
                header = handle.read(12)
            magic, version, length = struct.unpack("<III", header)
            report["probe_export"] = {
                "bytes": os.path.getsize(probe),
                "magic_ok": magic == 0x46546C67,
                "version": version,
                "declared_length": length,
            }
    else:
        report["probe_export"] = None

    print("API_REPORT_BEGIN")
    print(json.dumps(report, indent=2))
    print("API_REPORT_END")

    ok = (report["gltf_addon"] and report["gltf_operator"]
          and report["probe_export"] and report["probe_export"]["magic_ok"]
          and report["probe_export"]["bytes"] > 0)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
