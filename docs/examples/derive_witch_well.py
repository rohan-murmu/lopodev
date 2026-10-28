"""Example derive script: turn a plain water well into a witch's well.

Run with:
  lopodev assets derive --project projects/<slug> --from sm_water_well --id sm_witch_well \
      --script docs/examples/derive_witch_well.py

`edit(ctx)` may use any Blender API through ctx.bpy; lib_edit helpers are shortcuts.
Part names come from the source asset: inspect them first with ctx.parts().
"""

import math


def edit(ctx):
    ctx.log(f"source parts: {[p['name'] for p in ctx.parts()]}")

    # Dark, mossy, uneven stones.
    stones = ctx.find("stone|wall|ring|brick")
    ctx.recolor(stones, (0.16, 0.2, 0.14), roughness=0.95)
    ctx.noise_displace(stones, strength=0.04, scale=0.25, subdivide=1)

    # Glowing green potion water.
    water = ctx.find("water", required=False)
    if water:
        ctx.set_material(water, ctx.material("witch_water", (0.25, 1.0, 0.35), roughness=0.05, emission=4.0))

    # Weathered dark wood frame and a crooked roof.
    wood = ctx.find("post|beam|roof|wood|frame", required=False)
    if wood:
        ctx.recolor(wood, (0.12, 0.08, 0.1))
    roof = ctx.find("roof", required=False)
    if roof:
        ctx.place(roof, rotation=(0.0, math.radians(6), math.radians(45)))

    # Hanging bones and a skull on the rim, a lantern with a sickly glow.
    bone = ctx.material("bone", (0.85, 0.82, 0.7), roughness=0.6)
    for index, x in enumerate((-0.35, 0.0, 0.35)):
        ctx.add("box", f"HangingBone{index}", size=(0.05, 0.05, 0.35), location=(x, 0.0, 1.75), material=bone)
    ctx.add("sphere", "Skull", size=(0.22, 0.22, 0.22), location=(0.55, -0.45, 0.98), material=bone)
    ctx.add("box", "LanternBody", size=(0.16, 0.16, 0.22), location=(-0.75, -0.2, 1.75),
            material=ctx.material("lantern_glow", (0.6, 1.0, 0.3), emission=6.0))

    ctx.set_origin_ground()
