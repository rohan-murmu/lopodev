# Main Scene Node Map - prop_poc

Scene: `res://scenes/Main.tscn`
Purpose: presentation scene proving `sm_crate.glb` imports and renders.

| Node | Type | Parent | Responsibility |
|---|---|---|---|
| `Main` | Node3D | root | Scene script, camera framing, crate rotation |
| `WorldEnvironment` | WorldEnvironment | Main | Dark background, ambient fill, light fog |
| `Sun` | DirectionalLight3D | Main | Key light with shadows |
| `Ground` | MeshInstance3D | Main | 20x20 m matte ground plane |
| `Prop_Crate` | Node3D (GLB instance) | Main | Imported `sm_crate.glb` scene |
| `Camera3D` | Camera3D | Main | Three-quarter view of the crate |
| `HUD` | CanvasLayer | Main | Explains the PoC |
| `HUD/Title` | Label | HUD | On-screen caption |

Runtime behavior: `scripts/poc_runtime.gd` frames the crate once in `_ready` and
rotates `Prop_Crate` around +Y at 0.6 rad/s in `_process`.

Expected content gate target: `Prop_Crate`, with at least one MeshInstance3D,
two materials, and positive AABB size.

Animation check scene: `res://scenes/AnimCheck.tscn` instances `sm_gem.glb` as
`Prop_Gem` and expects the imported `anim_spin` clip.
