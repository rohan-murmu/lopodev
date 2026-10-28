extends SceneTree
## Load each imported asset scene, check meshes, skeleton and animations, and
## play every expected clip to prove it moves something (not just that it exists).
## Input: res://.pipeline/asset_checks.json {"assets": [{id, scene, min_meshes,
## animations: [clip], skeleton: bool}]}. Output: one ASSET_IMPORT_RESULT JSON
## line per asset, then ASSET_IMPORT_CHECK=PASS|FAIL.


func _initialize() -> void:
	var spec = JSON.parse_string(FileAccess.get_file_as_string("res://.pipeline/asset_checks.json"))
	if typeof(spec) != TYPE_DICTIONARY or not spec.has("assets"):
		print("ASSET_IMPORT_CHECK=FAIL unreadable res://.pipeline/asset_checks.json")
		quit(2)
		return
	var failed := 0
	for item in spec["assets"]:
		var result := _check(item)
		if result["status"] != "PASS":
			failed += 1
		print("ASSET_IMPORT_RESULT ", JSON.stringify(result))
	print("ASSET_IMPORT_CHECK=", "PASS" if failed == 0 else "FAIL")
	quit(0 if failed == 0 else 1)


func _check(item: Dictionary) -> Dictionary:
	var result := {"id": item["id"], "status": "FAIL", "detail": "", "playback_status": "NOT RUN",
		"playback": ""}
	var packed = load(item["scene"])
	if not packed is PackedScene:
		result["detail"] = "cannot load %s" % item["scene"]
		return result
	var node: Node = packed.instantiate()
	root.add_child(node)
	var meshes := node.find_children("*", "MeshInstance3D", true, false)
	var surfaces := 0
	for mesh_instance in meshes:
		if mesh_instance.mesh != null:
			surfaces += mesh_instance.mesh.get_surface_count()
	var skeletons := node.find_children("*", "Skeleton3D", true, false)
	var players := node.find_children("*", "AnimationPlayer", true, false)
	var clips: Array[String] = []
	for player in players:
		for clip in player.get_animation_list():
			clips.append(String(clip))
	var problems: Array[String] = []
	if meshes.size() < int(item.get("min_meshes", 1)) or surfaces == 0:
		problems.append("meshes=%d surfaces=%d" % [meshes.size(), surfaces])
	if item.get("skeleton", false) and skeletons.is_empty():
		problems.append("no Skeleton3D")
	var played: Array[String] = []
	var still: Array[String] = []
	var absent: Array[String] = []
	for wanted in item.get("animations", []):
		var found := ""
		var owner: AnimationPlayer = null
		for player in players:
			for clip in player.get_animation_list():
				if String(clip).to_lower() == String(wanted).to_lower():
					found = String(clip)
					owner = player
		if owner == null:
			absent.append(wanted)
			continue
		owner.play(found)
		owner.advance(0.0)
		var before := _pose(node, skeletons)
		owner.advance(min(owner.get_animation(found).length * 0.5, 0.5))
		if _pose(node, skeletons) != before:
			played.append(found)
		else:
			still.append(found)
		owner.stop()
	if not absent.is_empty():
		problems.append("missing clips %s (have %s)" % [absent, clips])
	if not item.get("animations", []).is_empty():
		result["playback_status"] = "PASS" if absent.is_empty() and still.is_empty() else "FAIL"
		result["playback"] = "moved: %s; static: %s; missing: %s" % [played, still, absent]
	if not still.is_empty():
		problems.append("clips do not move anything: %s" % [still])
	result["meshes"] = meshes.size()
	result["surfaces"] = surfaces
	result["skeletons"] = skeletons.size()
	result["clips"] = clips
	result["status"] = "PASS" if problems.is_empty() else "FAIL"
	result["detail"] = "; ".join(problems) if not problems.is_empty() else \
		"meshes=%d surfaces=%d skeletons=%d clips=%d" % [meshes.size(), surfaces, skeletons.size(), clips.size()]
	node.queue_free()
	return result


func _pose(node: Node, skeletons: Array) -> String:
	var parts: PackedStringArray = []
	for skeleton in skeletons:
		for bone in skeleton.get_bone_count():
			var q: Quaternion = skeleton.get_bone_pose_rotation(bone)
			parts.append("%.3f,%.3f,%.3f,%.3f" % [q.x, q.y, q.z, q.w])
			parts.append(str(skeleton.get_bone_pose_position(bone).snappedf(0.001)))
	for child in node.find_children("*", "Node3D", true, false):
		parts.append(str(child.transform.origin.snappedf(0.001)) + str(child.basis.get_euler().snappedf(0.001)))
	return ";".join(parts)
