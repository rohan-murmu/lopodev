extends SceneTree
## Content gate: instantiate the main scene and verify imported assets.
## Run via: godot --headless --path <project> --script res://.pipeline/validate_project.gd
## Env: SCENE_PATH, TARGET_NODE, TARGET_GLB, TARGET_ANIM, REQUIRE_MATERIAL

var failures: Array[String] = []
var warnings: Array[String] = []


func _env(name: String, fallback: String = "") -> String:
	var value := OS.get_environment(name)
	return value if value != "" else fallback


func _fail(message: String) -> void:
	failures.append(message)


func _find_first_mesh(node: Node) -> MeshInstance3D:
	if node is MeshInstance3D:
		return node
	for child in node.get_children():
		var found := _find_first_mesh(child)
		if found != null:
			return found
	return null


func _find_animation_player(node: Node) -> AnimationPlayer:
	if node is AnimationPlayer:
		return node
	for child in node.get_children():
		var found := _find_animation_player(child)
		if found != null:
			return found
	return null


func _initialize() -> void:
	var scene_path := _env("SCENE_PATH",
		str(ProjectSettings.get_setting("application/run/main_scene", "")))
	var target_name := _env("TARGET_NODE")
	var target_glb := _env("TARGET_GLB")
	var expected_anims := _env("TARGET_ANIM")
	var require_material := _env("REQUIRE_MATERIAL", "1") == "1"

	var report := {
		"status": "FAIL",
		"scene": scene_path,
		"target_node": target_name,
		"target_glb": target_glb,
		"mesh_surfaces": 0,
		"materials": 0,
		"aabb_size": [],
		"animations_available": [],
		"failures": failures,
		"warnings": warnings,
	}

	if scene_path == "":
		_fail("no SCENE_PATH and no main scene configured")
	if target_glb != "" and not FileAccess.file_exists(target_glb):
		_fail("TARGET_GLB does not exist: %s" % target_glb)

	var packed: Resource = null
	if scene_path != "":
		packed = load(scene_path)
		if packed == null:
			_fail("failed to load scene: %s" % scene_path)
		elif not (packed is PackedScene):
			_fail("resource is not a PackedScene: %s" % scene_path)

	var instance: Node = null
	if packed is PackedScene:
		instance = (packed as PackedScene).instantiate()
		if instance == null:
			_fail("PackedScene.instantiate() returned null")
		else:
			root.add_child(instance)
			report["scene_root"] = instance.name

	var target: Node = null
	if instance != null:
		if target_name != "":
			target = instance.find_child(target_name, true, false)
			if target == null:
				_fail("target node not found: %s" % target_name)
		else:
			target = _find_first_mesh(instance)

	if target != null:
		report["target_found"] = true
		report["target_class"] = target.get_class()
		var mesh_instance: MeshInstance3D = target as MeshInstance3D
		if mesh_instance == null:
			mesh_instance = _find_first_mesh(target)
		if mesh_instance == null:
			_fail("no MeshInstance3D found under target %s" % target.name)
		elif mesh_instance.mesh == null:
			_fail("target mesh is null")
		else:
			var mesh: Mesh = mesh_instance.mesh
			var surfaces := mesh.get_surface_count()
			report["mesh_surfaces"] = surfaces
			if surfaces <= 0:
				_fail("mesh has zero surfaces")
			var material_count := 0
			for surface in range(surfaces):
				if mesh.surface_get_material(surface) != null:
					material_count += 1
			report["materials"] = material_count
			if require_material and material_count == 0:
				_fail("no materials assigned to mesh surfaces")
			var aabb := mesh.get_aabb()
			report["aabb_size"] = [aabb.size.x, aabb.size.y, aabb.size.z]
			if aabb.size.length() < 0.001:
				_fail("mesh AABB is degenerate: %s" % aabb.size)
	else:
		report["target_found"] = false

	if expected_anims != "":
		var player := _find_animation_player(instance) if instance != null else null
		if player == null:
			_fail("TARGET_ANIM set but no AnimationPlayer found")
		else:
			var available := player.get_animation_list()
			report["animations_available"] = Array(available)
			for clip in expected_anims.split(",", false):
				var name := clip.strip_edges()
				if name != "" and not player.has_animation(name):
					_fail("expected animation not imported: %s (available: %s)"
						% [name, ", ".join(Array(available))])

	if instance != null:
		report["node_count"] = instance.get_child_count(true)

	report["status"] = "PASS" if failures.is_empty() else "FAIL"
	report["generated_at_utc"] = Time.get_datetime_string_from_system(true)
	print(JSON.stringify(report, "  "))
	print("PROJECT_VALIDATION=%s" % report["status"])

	if instance != null:
		instance.free()
	quit(0 if failures.is_empty() else 1)
