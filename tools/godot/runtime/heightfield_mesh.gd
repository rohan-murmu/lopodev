@tool
extends MeshInstance3D
## Builds the visible terrain from the sibling HeightMapShape3D, so collision,
## navigation and visuals share one heightfield. Copied into projects by
## tools/godot/world_to_tscn.py; regenerate rather than edit.


func _ready() -> void:
	var holder := get_parent().get_node_or_null("Shape") as CollisionShape3D
	if holder == null or not holder.shape is HeightMapShape3D:
		push_error("heightfield_mesh: sibling Shape with HeightMapShape3D not found")
		return
	var field := holder.shape as HeightMapShape3D
	var w := field.map_width
	var d := field.map_depth
	var data := field.map_data
	var tool := SurfaceTool.new()
	tool.begin(Mesh.PRIMITIVE_TRIANGLES)
	var ox := (w - 1) / 2.0
	var oz := (d - 1) / 2.0
	for j in d - 1:
		for i in w - 1:
			var corners := [Vector2i(i, j), Vector2i(i + 1, j), Vector2i(i + 1, j + 1), Vector2i(i, j + 1)]
			var points: Array[Vector3] = []
			for c in corners:
				points.append(Vector3(c.x - ox, data[c.y * w + c.x], c.y - oz))
			for index in [0, 1, 2, 0, 2, 3]:
				tool.set_uv(Vector2(points[index].x, points[index].z) * 0.25)
				tool.add_vertex(points[index])
	tool.generate_normals()
	mesh = tool.commit()
