extends SceneTree
## Bake the world's navigation mesh and prove agents can travel where the
## design says: every Enemy_* marker to the player spawn, and the player spawn
## to every Objective_*. Usage:
##   godot --headless --path <dir> --script res://.pipeline/nav_check.gd -- res://scenes/World.tscn
## Prints NAV_PATH lines and NAV_CHECK=PASS|FAIL. Fails if nothing was baked.

var scene_path := "res://scenes/World.tscn"


func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	if args.size() > 0:
		scene_path = args[0]
	_run()


func _run() -> void:
	var packed = load(scene_path)
	if not packed is PackedScene:
		print("NAV_CHECK=FAIL cannot load ", scene_path)
		quit(2)
		return
	var world: Node = packed.instantiate()
	root.add_child(world)
	var region := world.find_children("*", "NavigationRegion3D", true, false)
	if region.is_empty():
		print("NAV_CHECK=FAIL no NavigationRegion3D")
		quit(1)
		return
	var nav: NavigationRegion3D = region[0]
	var markers := world.get_node_or_null("Markers")
	var spawn: Node3D = null
	var pairs: Array = []
	if markers:
		for child in markers.get_children():
			if child.name.begins_with("Spawn_") and spawn == null:
				spawn = child
	if spawn == null:
		print("NAV_CHECK=FAIL no Spawn_* marker")
		quit(1)
		return
	await physics_frame
	var map := nav.get_navigation_map()
	nav.bake_navigation_mesh(false)
	var polygons := nav.navigation_mesh.get_polygon_count() if nav.navigation_mesh else 0
	print("NAV_POLYGONS=", polygons)
	if polygons == 0:
		print("NAV_CHECK=FAIL navigation mesh baked empty")
		quit(1)
		return
	# The server applies the baked mesh asynchronously; wait until the map has
	# a polygon under the spawn (bounded) instead of a fixed number of frames.
	var waited := 0
	while waited < 600:
		await physics_frame
		waited += 1
		if NavigationServer3D.map_get_iteration_id(map) == 0:
			continue
		var probe := NavigationServer3D.map_get_closest_point(map, spawn.global_position)
		if Vector2(probe.x - spawn.global_position.x, probe.z - spawn.global_position.z).length() < 1.5:
			break
	for i in 2:
		await physics_frame
	print("NAV_SYNC_FRAMES=", waited)
	for child in markers.get_children():
		if child.name.begins_with("Enemy_"):
			pairs.append([child, spawn])
		elif child.name.begins_with("Objective_"):
			pairs.append([spawn, child])
	var failed := 0
	for pair in pairs:
		var from: Vector3 = pair[0].global_position
		var to: Vector3 = pair[1].global_position
		var start := NavigationServer3D.map_get_closest_point(map, from)
		var goal := NavigationServer3D.map_get_closest_point(map, to)
		var path := NavigationServer3D.map_get_path(map, start, goal, true)
		var snapped_ok := Vector2(start.x - from.x, start.z - from.z).length() < 1.5 \
			and Vector2(goal.x - to.x, goal.z - to.z).length() < 1.5
		var ok := path.size() >= 2 and path[path.size() - 1].distance_to(goal) < 0.5 and snapped_ok
		var length := 0.0
		for i in range(1, path.size()):
			length += path[i - 1].distance_to(path[i])
		print("NAV_PATH %s -> %s %s points=%d length=%.1f" % [pair[0].name, pair[1].name,
			"PASS" if ok else "FAIL", path.size(), length])
		if not ok:
			failed += 1
	print("NAV_CHECK=", "PASS" if failed == 0 and pairs.size() > 0 else "FAIL", " pairs=", pairs.size())
	quit(0 if failed == 0 and pairs.size() > 0 else 1)
