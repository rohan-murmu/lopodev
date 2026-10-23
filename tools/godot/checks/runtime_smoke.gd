extends SceneTree
## Runtime gate: load the scene, process real frames, assert observable state.
## Env: SCENE_PATH, TARGET_NODE, TARGET_ANIM, FRAMES, EXPECT_ROTATION,
##      EXPECT_MOVEMENT, MIN_ROTATION_RAD, MIN_MOVEMENT_M, EXPECT_ANIM_PLAYING

var failures: Array[String] = []
var target: Node3D = null
var initial_rotation := Quaternion.IDENTITY
var initial_position := Vector3.ZERO
var initial_captured := false
var frames_processed := 0
var frame_limit := 30
var finished := false


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
	frame_limit = int(_env("FRAMES", "30"))
	var scene_path := _env("SCENE_PATH",
		str(ProjectSettings.get_setting("application/run/main_scene", "")))
	var target_name := _env("TARGET_NODE", "Prop_Crate")

	if scene_path == "":
		_fail("no scene configured")
		_finish()
		return
	var packed := load(scene_path)
	if not (packed is PackedScene):
		_fail("failed to load PackedScene: %s" % scene_path)
		_finish()
		return

	var instance: Node = (packed as PackedScene).instantiate()
	if instance == null:
		_fail("instantiate() returned null")
		_finish()
		return
	root.add_child(instance)

	var found := instance.find_child(target_name, true, false) if target_name != "" else null
	if found == null and target_name == "":
		found = _find_first_mesh(instance)
	if found == null:
		_fail("target node not found: %s" % target_name)
		instance.print_tree_pretty()
		instance.free()
		_finish()
		return
	if not (found is Node3D):
		_fail("target is not Node3D: %s" % found.get_class())
		instance.free()
		_finish()
		return

	target = found as Node3D
	process_frame.connect(_on_process_frame)


func _on_process_frame() -> void:
	if finished:
		return
	frames_processed += 1
	if not initial_captured:
		if target == null or not is_instance_valid(target) or not target.is_inside_tree():
			_fail("target is not inside the tree on the first processed frame")
			_finish()
			return
		initial_rotation = target.global_transform.basis.get_rotation_quaternion()
		initial_position = target.global_position
		initial_captured = true
	if frames_processed < frame_limit:
		return

	if target == null or not is_instance_valid(target) or not target.is_inside_tree():
		_fail("target became invalid during runtime frames")
		_finish()
		return

	if _env("EXPECT_ROTATION", "0") == "1":
		var current := target.global_transform.basis.get_rotation_quaternion()
		var angle := initial_rotation.angle_to(current)
		if angle < float(_env("MIN_ROTATION_RAD", "0.01")):
			_fail("expected rotation change; observed %.6f rad" % angle)

	if _env("EXPECT_MOVEMENT", "0") == "1":
		var distance := initial_position.distance_to(target.global_position)
		if distance < float(_env("MIN_MOVEMENT_M", "0.01")):
			_fail("expected movement; observed %.6f m" % distance)

	var expected_anim := _env("TARGET_ANIM")
	if expected_anim != "":
		var player := _find_animation_player(target)
		if player == null:
			player = _find_animation_player(root)
		if player == null:
			_fail("TARGET_ANIM set but no AnimationPlayer found")
		else:
			for clip in expected_anim.split(",", false):
				var name := clip.strip_edges()
				if name != "" and not player.has_animation(name):
					_fail("animation missing at runtime: %s" % name)
			if _env("EXPECT_ANIM_PLAYING", "0") == "1" and not player.is_playing():
				_fail("expected AnimationPlayer to be playing")

	_finish()


func _finish() -> void:
	if finished:
		return
	finished = true
	var status := "PASS" if failures.is_empty() else "FAIL"
	var report := {
		"status": status,
		"scene": _env("SCENE_PATH",
			str(ProjectSettings.get_setting("application/run/main_scene", ""))),
		"target": target.name if target != null else "",
		"frames_processed": frames_processed,
		"failures": failures,
		"generated_at_utc": Time.get_datetime_string_from_system(true),
	}
	print(JSON.stringify(report, "  "))
	print("RUNTIME_SMOKE=%s" % status)
	quit(0 if status == "PASS" else 1)
